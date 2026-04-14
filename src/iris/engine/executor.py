"""Pipeline executor and top-level run_pipeline API."""
from __future__ import annotations

import re as _re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from tqdm.auto import tqdm

from iris.engine.ast import ExprNode, OverlayGroup, PipelineItem, WindowDirective
from iris.engine.cache import PipelineCache
from iris.engine.parser import DSLParser
from iris.engine.registry import OpRegistry
from iris.engine.type_system import DIRECT_BANK_OPS, TYPE_TRANSITIONS
from iris.engine.types import (
    MEABank, MEATrace, PipelineContext, RTBank, RTTrace,
    SpikeTrain, _SpikeBankIntermediate,
)


class PipelineExecutor:
    """Execute parsed pipeline items with caching, type checking, and auto-plot."""

    def __init__(self, registry: OpRegistry, cache: PipelineCache,
                 ctx: PipelineContext, ops_cfg: Dict[str, Dict],
                 source_loaders: Dict[str, Callable],
                 get_recording_duration_ms: Optional[Callable] = None):
        self.registry = registry
        self.cache = cache
        self.ctx = ctx
        self.ops_cfg = ops_cfg
        self.source_loaders = source_loaders
        self.get_recording_duration_ms = get_recording_duration_ms
        self._timings: List[Dict] = []

    def run(self, items: List[PipelineItem], plot: bool = True) -> List[Tuple[PipelineItem, Any]]:
        results: List[Tuple[PipelineItem, Any]] = []

        for i, item in enumerate(items):
            step_t0 = time.perf_counter()

            if isinstance(item, WindowDirective):
                if item.is_full:
                    if self.get_recording_duration_ms is None:
                        raise ValueError(
                            "window[full] requires get_recording_duration_ms callback to be provided"
                        )
                    duration_ms = self.get_recording_duration_ms(self.ctx)
                    self.ctx.window_ms = (0.0, duration_ms)
                    self._log(f"[window] full (0.00 - {duration_ms:.2f} ms)")
                else:
                    self.ctx.window_ms = (item.start_ms, item.end_ms)
                    self._log(f"[window] {item.start_ms:.2f} - {item.end_ms:.2f} ms")
                results.append((item, None))

            elif isinstance(item, ExprNode):
                label = self._make_label(item)
                self._log(f"[step {i}] {label}")
                result = self._execute_expression(item)
                results.append((item, result))
                elapsed = time.perf_counter() - step_t0
                self._timings.append({"step": i, "label": label, "time": elapsed})
                self._log(f"  -> {type(result).__name__} ({elapsed:.2f}s)")
                if plot:
                    last_op = item.ops[-1].op_name if item.ops else None
                    self._auto_plot(result, last_op, label, item)

            elif isinstance(item, OverlayGroup):
                labels = [self._make_label(e) for e in item.expressions]
                self._log(f"[step {i}] overlay: {labels}")
                step_results = []
                for expr in item.expressions:
                    step_results.append(self._execute_expression(expr))
                results.append((item, step_results))
                elapsed = time.perf_counter() - step_t0
                self._timings.append({"step": i, "label": f"overlay({len(labels)})", "time": elapsed})
                self._log(f"  -> overlay complete ({elapsed:.2f}s)")
                if plot:
                    overlay_fn = self.registry.get_overlay_plot()
                    if overlay_fn:
                        overlay_fn(step_results, labels, self.ctx)

        return results

    def _execute_expression(self, expr: ExprNode) -> Any:
        window_ms = self.ctx.window_ms
        margin = self._compute_margin_for_chain(expr)

        # Check cache for longest prefix
        prefix_len, cached = self.cache.find_longest_prefix(
            window_ms, expr, self.ops_cfg, margin
        )

        if prefix_len == len(expr.ops):
            self._log(f"    cache hit (full)")
            return cached

        if prefix_len >= 0 and cached is not None:
            current = cached
            start_idx = prefix_len
            self._log(f"    cache hit (prefix len={prefix_len})")
        else:
            current = self._load_source(expr.source, margin)
            start_idx = 0
            source_key = self.cache.make_prefix_key(
                window_ms, expr.source, [], self.ops_cfg, margin
            )
            self.cache.mem_put(source_key, current)

        for i in range(start_idx, len(expr.ops)):
            op = expr.ops[i]
            current = self._apply_op(op, current)
            prefix_key = self.cache.make_prefix_key(
                window_ms, expr.source, expr.ops[:i + 1], self.ops_cfg, margin
            )
            self.cache.mem_put(prefix_key, current)
            self.cache.disk_put_result(prefix_key, current)

        return current

    def _load_source(self, source, margin_samples: int = 0) -> Any:
        loader_key = source.source_type
        if loader_key not in self.source_loaders:
            raise KeyError(
                f"No source loader registered for '{loader_key}'. "
                f"Available: {list(self.source_loaders.keys())}"
            )
        return self.source_loaders[loader_key](source.source_id, self.ctx, margin_samples)

    def _apply_op(self, op, current: Any) -> Any:
        if op.inner_expr is not None:
            return self._apply_function_op(op, current)

        op_name = op.op_name
        input_type = type(current)

        # Validate type transition
        output_type = self.registry.validate_type_transition(op_name, input_type)

        # Handle MEABank vectorization for ops that expect MEATrace
        if (input_type == MEABank and MEATrace in TYPE_TRANSITIONS.get(op_name, {})
                and op_name not in DIRECT_BANK_OPS):
            return self._apply_op_to_bank(op, current)

        # Handle RTBank vectorization for ops that expect RTTrace
        if input_type == RTBank and RTTrace in TYPE_TRANSITIONS.get(op_name, {}):
            return self._apply_op_to_rt_bank(op, current)

        # Merge params: ops_cfg defaults + per-call overrides
        params = {**self.ops_cfg.get(op_name, {}), **op.kwargs_overrides}
        handler = self.registry.get_op(op_name)
        result = handler(current, self.ctx, **params)

        if not isinstance(result, output_type):
            raise TypeError(
                f"Op '{op_name}' handler returned {type(result).__name__}, "
                f"expected {output_type.__name__}"
            )
        return result

    def _apply_op_to_bank(self, op, bank: MEABank) -> Any:
        """Apply an op per-channel across an MEABank."""
        op_name = op.op_name
        single_output_type = TYPE_TRANSITIONS[op_name][MEATrace]
        params = {**self.ops_cfg.get(op_name, {}), **op.kwargs_overrides}
        handler = self.registry.get_op(op_name)

        n_channels = bank.traces.shape[0]
        results = []
        desc = f"  {op_name} ({n_channels} ch)"
        for i in tqdm(range(n_channels), desc=desc, leave=False):
            single = MEATrace(
                data=bank.traces[i],
                fs_hz=bank.fs_hz,
                channel_idx=bank.channel_ids[i],
                window_samples=bank.window_samples,
                margin_left=bank.margin_left,
                margin_right=bank.margin_right,
            )
            results.append(handler(single, self.ctx, **params))

        if single_output_type == MEATrace:
            return MEABank(
                traces=np.array([r.data for r in results]),
                fs_hz=bank.fs_hz,
                channel_ids=bank.channel_ids,
                locations=bank.locations,
                window_samples=bank.window_samples,
                margin_left=0,
                margin_right=0,
                label=op_name,
            )
        elif single_output_type == SpikeTrain:
            return _SpikeBankIntermediate(
                spike_trains=results,
                fs_hz=bank.fs_hz,
                channel_ids=bank.channel_ids,
                locations=bank.locations,
                window_samples=bank.window_samples,
            )
        elif single_output_type == RTTrace:
            return RTBank(
                traces=np.array([r.data for r in results]),
                fs_hz=bank.fs_hz,
                channel_ids=bank.channel_ids,
                locations=bank.locations,
                window_samples=results[0].window_samples,
                label=op_name,
            )
        else:
            raise TypeError(f"Unexpected output type {single_output_type} from bank vectorization")

    def _apply_op_to_rt_bank(self, op, bank: RTBank) -> Any:
        """Apply an op per-channel across an RTBank."""
        op_name = op.op_name
        single_output_type = TYPE_TRANSITIONS[op_name][RTTrace]
        params = {**self.ops_cfg.get(op_name, {}), **op.kwargs_overrides}
        handler = self.registry.get_op(op_name)

        n_channels = bank.traces.shape[0]
        results = []
        desc = f"  {op_name} ({n_channels} ch)"
        for i in tqdm(range(n_channels), desc=desc, leave=False):
            single = RTTrace(
                data=bank.traces[i],
                fs_hz=bank.fs_hz,
                channel_idx=bank.channel_ids[i],
                window_samples=bank.window_samples,
            )
            results.append(handler(single, self.ctx, **params))

        if single_output_type == RTTrace:
            return RTBank(
                traces=np.array([r.data for r in results]),
                fs_hz=bank.fs_hz,
                channel_ids=bank.channel_ids,
                locations=bank.locations,
                window_samples=bank.window_samples,
                label=op_name,
            )
        elif single_output_type == SpikeTrain:
            return _SpikeBankIntermediate(
                spike_trains=results,
                fs_hz=bank.fs_hz,
                channel_ids=bank.channel_ids,
                locations=bank.locations,
                window_samples=bank.window_samples,
            )
        else:
            raise TypeError(f"Unexpected output type {single_output_type} from RTBank vectorization")

    def _apply_function_op(self, op, left: Any) -> Any:
        right = self._execute_expression(op.inner_expr)
        params = {**self.ops_cfg.get(op.op_name, {}), **op.kwargs_overrides}
        handler = self.registry.get_op(op.op_name)
        return handler(left, right, self.ctx, **params)

    def _compute_margin_for_chain(self, expr: ExprNode) -> int:
        margin = 0
        for op in expr.ops:
            params = {**self.ops_cfg.get(op.op_name, {}), **op.kwargs_overrides}
            calc = self.registry.get_margin_calculator(op.op_name)
            if calc:
                margin = max(margin, calc(params, self.ctx))
            if op.inner_expr:
                margin = max(margin, self._compute_margin_for_chain(op.inner_expr))
        return margin

    def _auto_plot(self, result: Any, last_op: Optional[str], label: str,
                   expr: Optional[ExprNode] = None) -> None:
        # Store current expression in context for plot handlers
        self.ctx.current_expr = expr
        plot_fn = self.registry.get_plot(type(result))
        if plot_fn:
            if self.ctx.save_plots and self.ctx.output_dir:
                out = Path(self.ctx.output_dir)
                out.mkdir(parents=True, exist_ok=True)
                _counter = [0]
                _orig_show = plt.show

                def _saving_show(*a, **kw):
                    safe = _re.sub(r'[^\w\-]', '_', label)[:80]
                    fig = plt.gcf()
                    plot_path = out / f"{safe}_{_counter[0]}.png"
                    fig.savefig(str(plot_path), dpi=150, bbox_inches='tight')
                    _counter[0] += 1
                    # Sidecar provenance JSON next to every saved plot
                    try:
                        from iris.plot_sessions import write_provenance_sidecar
                        write_provenance_sidecar(plot_path, self.ctx)
                    except Exception as e:
                        if self.ctx.verbose:
                            print(f"  [provenance sidecar skipped: {e}]")
                    plt.close(fig)

                plt.show = _saving_show
                try:
                    plot_fn(result, self.ctx, last_op)
                finally:
                    plt.show = _orig_show
            else:
                plot_fn(result, self.ctx, last_op)

    def _make_label(self, expr: ExprNode) -> str:
        parts = [f"{expr.source.source_type}({expr.source.source_id})"]
        for op in expr.ops:
            if op.kwargs_overrides:
                kw = ", ".join(f"{k}={v}" for k, v in op.kwargs_overrides.items())
                parts.append(f"{op.op_name}({kw})")
            elif op.inner_expr:
                inner_label = self._make_label(op.inner_expr)
                parts.append(f"{op.op_name}({inner_label})")
            else:
                parts.append(op.op_name)
        return ".".join(parts)

    def _log(self, msg: str) -> None:
        if self.ctx.verbose:
            print(msg)

    @property
    def timings(self) -> List[Dict]:
        return list(self._timings)


def run_pipeline(
    paths_cfg: Dict[str, str],
    ops_cfg: Dict[str, Dict],
    pipeline_cfg: List,
    registry: OpRegistry,
    source_loaders: Dict[str, Callable],
    globals_cfg: Dict[str, Any] = None,
    mea_fs_hz: float = 20000.0,
    rtsort_fs_hz: float = 20000.0,
    verbose: bool = True,
    plot: bool = True,
    get_recording_duration_ms: Optional[Callable] = None,
) -> List[Tuple[PipelineItem, Any]]:
    """Main entry point: parse DSL, build context, execute pipeline."""
    # Parse globals_cfg
    if globals_cfg is None:
        globals_cfg = {}

    # Extract window_ms from globals_cfg and prepend to pipeline
    if 'window_ms' in globals_cfg:
        window_val = globals_cfg['window_ms']
        if window_val == 'full':
            window_item = "window_ms[full]"
        else:
            start, end = window_val
            window_item = f"window_ms[{start}, {end}]"
        pipeline_cfg = [window_item] + list(pipeline_cfg)

    # Extract cache flags
    memory_cache = globals_cfg.get('memory_cache', True)
    disk_cache = globals_cfg.get('disk_cache', True)

    # Extract show_ops_params flag
    show_ops_params = globals_cfg.get('show_ops_params', False)
    save_plots = globals_cfg.get('save_plots', False)

    interactive_plots = globals_cfg.get('interactive_plots', False)
    plt.rcParams['figure.dpi'] = 72 if interactive_plots else 100
    try:
        ip = get_ipython()
        if ip is not None:
            ip.run_line_magic('matplotlib', 'widget' if interactive_plots else 'inline')
    except NameError:
        pass

    ctx = PipelineContext(
        paths=paths_cfg,
        window_ms=(0.0, 0.0),
        mea_fs_hz=mea_fs_hz,
        rtsort_fs_hz=rtsort_fs_hz,
        output_dir=paths_cfg.get("output_dir"),
        cache_dir=paths_cfg.get("cache_dir"),
        verbose=verbose,
        ops_cfg=ops_cfg,
        show_ops_params=show_ops_params,
        interactive_plots=interactive_plots,
        memory_cache=memory_cache,
        disk_cache=disk_cache,
        save_plots=save_plots,
        plot_backend=globals_cfg.get("plot_backend"),
    )

    cache = PipelineCache(cache_dir=ctx.cache_dir, source_paths=paths_cfg,
                          memory_cache=memory_cache, disk_cache=disk_cache)
    ctx.cache = cache
    parser = DSLParser()
    items = parser.parse_pipeline(pipeline_cfg)
    executor = PipelineExecutor(registry, cache, ctx, ops_cfg, source_loaders, get_recording_duration_ms)

    t0 = time.perf_counter()
    results = executor.run(items, plot=plot)
    elapsed = time.perf_counter() - t0

    if verbose:
        print("=" * 70)
        print("PIPELINE COMPLETE")
        print("=" * 70)
        print(f"  Steps: {len(results)}")
        print(f"  Total time: {elapsed:.2f}s ({elapsed / 60:.1f} min)")
        stats = cache.stats
        print(f"  Cache: {stats['hits']} hits, {stats['misses']} misses, {stats['disk_hits']} disk hits")
        if executor.timings:
            print("  Step timings:")
            for t in executor.timings:
                print(f"    [{t['step']}] {t['label']}: {t['time']:.2f}s")

    return results
