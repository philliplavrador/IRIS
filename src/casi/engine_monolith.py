"""
Config-driven DAG pipeline engine for neuroscience signal processing.

This module provides the infrastructure for parsing a DSL-based pipeline
configuration, building an execution DAG with prefix caching, enforcing
type compatibility, and auto-plotting results.

It also contains all op handlers, source loaders, plot handlers, and the
registry factory (create_registry) so that all operation logic lives in
one place.
"""
from __future__ import annotations

import gc
import hashlib
import json
import pickle
import re
import time

import torch
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Optional, Sequence, Tuple, Union,
)

import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d, percentile_filter
from scipy.signal import (
    butter, convolve, correlate, filtfilt, find_peaks,
    iirnotch, sosfiltfilt, spectrogram as _scipy_spectrogram, tf2sos,
)
from spikeinterface.extractors import MaxwellRecordingExtractor
from tqdm.auto import tqdm


# ════════════════════════════════════════════════════════════════════════════════
# DATA TYPE DATACLASSES
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class PipelineContext:
    """Immutable context for a pipeline run."""
    paths: Dict[str, str]
    window_ms: Tuple[float, float]
    mea_fs_hz: float = 20000.0
    rtsort_fs_hz: float = 20000.0
    output_dir: Optional[str] = None
    cache_dir: Optional[str] = None
    verbose: bool = True
    ops_cfg: Dict[str, Dict] = field(default_factory=dict)
    current_expr: Optional['ExprNode'] = None
    show_ops_params: bool = False
    interactive_plots: bool = False
    memory_cache: bool = True
    disk_cache: bool = True
    save_plots: bool = False
    plot_backend: Optional[str] = None
    cache: Optional[Any] = None

    @property
    def window_samples_mea(self) -> Tuple[int, int]:
        s, e = self.window_ms
        fs = self.mea_fs_hz
        return (int(s * fs / 1000), int(e * fs / 1000))

    @property
    def window_samples_rtsort(self) -> Tuple[int, int]:
        s, e = self.window_ms
        fs = self.rtsort_fs_hz
        return (int(s * fs / 1000), int(e * fs / 1000))


@dataclass
class MEATrace:
    """Single-channel MEA voltage trace (raw or filtered)."""
    data: np.ndarray
    fs_hz: float
    channel_idx: int
    window_samples: Tuple[int, int]
    margin_left: int = 0
    margin_right: int = 0
    label: str = ""

    @property
    def trimmed_data(self) -> np.ndarray:
        if self.margin_left == 0 and self.margin_right == 0:
            return self.data
        end = len(self.data) - self.margin_right if self.margin_right > 0 else len(self.data)
        return self.data[self.margin_left:end]


@dataclass
class MEABank:
    """Collection of MEA traces (all channels)."""
    traces: np.ndarray          # (n_channels, n_samples)
    fs_hz: float
    channel_ids: np.ndarray
    locations: np.ndarray       # (n_channels, 2)
    window_samples: Tuple[int, int]
    margin_left: int = 0
    margin_right: int = 0
    label: str = ""


@dataclass
class CATrace:
    """Calcium imaging trace (single ROI), interpolated to MEA grid."""
    data: np.ndarray
    fs_hz: float
    trace_idx: int
    window_samples: Tuple[int, int]
    original_data: Optional[np.ndarray] = None
    original_frames: Optional[np.ndarray] = None
    baseline: Optional[np.ndarray] = None
    label: str = ""


@dataclass
class RTTrace:
    """RTSort model output trace (single channel)."""
    data: np.ndarray
    fs_hz: float
    channel_idx: int
    window_samples: Tuple[int, int]
    label: str = ""


@dataclass
class RTBank:
    """Collection of RTSort model output traces (all channels)."""
    traces: np.ndarray          # (n_channels, n_samples) — logits
    fs_hz: float
    channel_ids: np.ndarray
    locations: np.ndarray       # (n_channels, 2)
    window_samples: Tuple[int, int]
    label: str = ""


@dataclass
class SpikeTrain:
    """Result of spike detection or RT thresholding."""
    spike_indices: np.ndarray
    spike_values: np.ndarray
    threshold_curve: np.ndarray
    source_signal: np.ndarray
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    num_spikes: int = 0
    label: str = ""

    def __post_init__(self):
        self.num_spikes = len(self.spike_indices)


@dataclass
class SimCalcium:
    """Simulated calcium trace from spike train convolution."""
    data: np.ndarray
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    spike_indices: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    label: str = ""


@dataclass
class SimCalciumBank:
    """Collection of SimCalcium traces (one per MEA channel)."""
    traces: np.ndarray          # (n_channels, n_samples)
    fs_hz: float
    channel_ids: np.ndarray
    locations: np.ndarray
    electrode_info: List[Dict]
    window_samples: Tuple[int, int]
    label: str = ""


@dataclass
class CorrelationResult:
    """Result of x_corr operation."""
    correlations: np.ndarray
    best_idx: int
    best_corr: float
    electrode_info: List[Dict]
    ca_trace_idx: int
    x_coords: np.ndarray
    y_coords: np.ndarray
    ca_signal: np.ndarray
    best_sim_trace: np.ndarray
    window_samples: Tuple[int, int]
    fs_hz: float
    label: str = ""
    pct_masked: Optional[np.ndarray] = None  # (n_channels,) % saturation per electrode, or None


@dataclass
class _SpikeBankIntermediate:
    """Internal: collection of SpikeTrain results, one per MEA channel."""
    spike_trains: List[SpikeTrain]
    fs_hz: float
    channel_ids: np.ndarray
    locations: np.ndarray
    window_samples: Tuple[int, int]


@dataclass
class SpikePCA:
    """PCA projection of spike waveforms with outlier flagging."""
    spike_indices: np.ndarray           # (n_spikes,) sample indices of valid spikes
    spike_values: np.ndarray            # (n_spikes,) amplitude at each spike
    waveforms: np.ndarray               # (n_spikes, snippet_len) voltage snippets
    pca_projections: np.ndarray         # (n_spikes, n_components) PC scores
    pca_components: np.ndarray          # (n_components, snippet_len) principal axes
    explained_variance_ratio: np.ndarray # (n_components,) variance fraction per PC
    centroid: np.ndarray                # (n_components,) mean PC-space location
    distances: np.ndarray               # (n_spikes,) Euclidean distance from centroid
    outlier_mask: np.ndarray            # (n_spikes,) bool — True = flagged outlier
    source_signal: np.ndarray           # pass-through for spike_curate → gcamp_sim
    threshold_curve: np.ndarray         # pass-through for spike_curate
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    n_outliers: int = 0
    label: str = "spike_pca"

    def __post_init__(self):
        self.n_outliers = int(np.sum(self.outlier_mask))


@dataclass
class Spectrogram:
    """Time-frequency representation from scipy.signal.spectrogram."""
    frequencies: np.ndarray       # Frequency bins (Hz)
    times: np.ndarray            # Time bins (ms)
    power: np.ndarray            # Power spectral density (2D: freq x time)
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    label: str = "spectrogram"


@dataclass
class FreqPowerTraces:
    """Power vs time extracted at specific frequencies from a Spectrogram."""
    times: np.ndarray                      # Time bins (ms), shape (T,)
    freq_traces: Dict[float, np.ndarray]   # {actual_hz: power_vs_time}
    broadband_power: np.ndarray            # Mean power over broadband range, shape (T,)
    broadband_range_hz: Tuple[float, float]
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    label: str = "freq_traces"


@dataclass
class SaturationReport:
    """Per-channel saturation episode summary for all MEA channels."""
    channel_ids: np.ndarray
    locations: np.ndarray
    samples_masked: np.ndarray   # (n_channels,) masked sample count per channel
    total_samples: int
    window_samples: Tuple[int, int]
    fs_hz: float
    label: str = "saturation_survey"
    plot_type: str = "histogram"  # "histogram", "scatter", or "survival"


# ════════════════════════════════════════════════════════════════════════════════
# TYPE SYSTEM
# ════════════════════════════════════════════════════════════════════════════════
#
# ADDING A NEW OP: TYPE_TRANSITIONS is one of six touch points. See the
# "Adding a new operation" checklist in docs/operations.md. Any op the
# analysis agent adds autonomously must hit all six: this dict, a handler
# function below, a register_op() call in create_registry(), a defaults
# entry in configs/ops.yaml, a documentation section in docs/operations.md,
# and a type-transition test in tests/test_op_registry.py.

DataType = type

TYPE_TRANSITIONS: Dict[str, Dict[DataType, DataType]] = {
    "butter_bandpass":     {MEATrace: MEATrace,   MEABank: MEABank},
    "notch_filter":        {MEATrace: MEATrace,   MEABank: MEABank},
    "saturation_mask":     {MEATrace: MEATrace,   MEABank: MEABank},
    "constant_rms":        {MEATrace: SpikeTrain, MEABank: _SpikeBankIntermediate},
    "sliding_rms":         {MEATrace: SpikeTrain, MEABank: _SpikeBankIntermediate},
    "spike_pca":           {SpikeTrain: SpikePCA},
    "spike_curate":        {},  # validated separately (function-op: SpikePCA + CATrace → SpikeTrain)
    "baseline_correction": {CATrace: CATrace},
    "rt_detect":           {MEATrace: RTTrace},
    "sigmoid":             {RTTrace: RTTrace,   RTBank: RTBank},
    "rt_thresh":           {RTTrace: SpikeTrain, RTBank: _SpikeBankIntermediate},
    "gcamp_sim":           {SpikeTrain: SimCalcium, _SpikeBankIntermediate: SimCalciumBank},
    "spectrogram":         {MEATrace: Spectrogram},
    "freq_traces":         {MEATrace: FreqPowerTraces},
    "amp_gain_correction": {MEATrace: MEATrace, MEABank: MEABank},
    "saturation_survey":   {MEABank: SaturationReport},
    "x_corr":              {},  # validated separately
}

# Ops that handle MEABank directly (no per-channel vectorization) despite supporting MEATrace.
DIRECT_BANK_OPS: set = {"saturation_mask"}


# ════════════════════════════════════════════════════════════════════════════════
# OP REGISTRY
# ════════════════════════════════════════════════════════════════════════════════

class OpRegistry:
    """Registry mapping op names to handler functions and their type signatures."""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._margin_calculators: Dict[str, Callable] = {}
        self._plot_handlers: Dict[DataType, Callable] = {}
        self._overlay_plot_handler: Optional[Callable] = None

    def register_op(self, name: str, handler: Callable) -> None:
        if name not in TYPE_TRANSITIONS:
            raise ValueError(
                f"Unknown op name '{name}'. Valid ops: {list(TYPE_TRANSITIONS.keys())}"
            )
        self._handlers[name] = handler

    def register_margin_calculator(self, name: str, calculator: Callable) -> None:
        self._margin_calculators[name] = calculator

    def register_plot(self, data_type: DataType, handler: Callable) -> None:
        self._plot_handlers[data_type] = handler

    def register_overlay_plot(self, handler: Callable) -> None:
        self._overlay_plot_handler = handler

    def get_op(self, name: str) -> Callable:
        if name not in self._handlers:
            available = list(self._handlers.keys())
            raise KeyError(
                f"No handler registered for op '{name}'. "
                f"Registered ops: {available}"
            )
        return self._handlers[name]

    def get_margin_calculator(self, name: str) -> Optional[Callable]:
        return self._margin_calculators.get(name)

    def get_plot(self, data_type: DataType) -> Optional[Callable]:
        return self._plot_handlers.get(data_type)

    def get_overlay_plot(self) -> Optional[Callable]:
        return self._overlay_plot_handler

    def validate_type_transition(self, op_name: str, input_type: DataType) -> DataType:
        transitions = TYPE_TRANSITIONS.get(op_name, {})
        if input_type not in transitions:
            valid = [t.__name__ for t in transitions.keys()]
            raise TypeError(
                f"Op '{op_name}' cannot accept input type '{input_type.__name__}'. "
                f"Valid input types: {valid}"
            )
        return transitions[input_type]


# ════════════════════════════════════════════════════════════════════════════════
# AST NODES
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class SourceNode:
    """AST node for a data source."""
    source_type: str            # "mea_trace", "ca_trace", "rtsort"
    source_id: Union[int, str]  # channel/trace index, or "all"

    def cache_key_parts(self) -> Tuple:
        return (self.source_type, self.source_id)


@dataclass
class OpNode:
    """AST node for a chained operation."""
    op_name: str
    kwargs_overrides: Dict[str, Any] = field(default_factory=dict)
    inner_expr: Optional['ExprNode'] = None  # for function-ops like x_corr

    def cache_key_parts(self) -> Tuple:
        inner = self.inner_expr.cache_key_parts() if self.inner_expr else None
        return (self.op_name, tuple(sorted(self.kwargs_overrides.items())), inner)


@dataclass
class ExprNode:
    """AST node for a full expression: source.op1.op2.op3"""
    source: SourceNode
    ops: List[OpNode] = field(default_factory=list)

    def cache_key_parts(self) -> Tuple:
        parts = [self.source.cache_key_parts()]
        for op in self.ops:
            parts.append(op.cache_key_parts())
        return tuple(parts)


@dataclass
class WindowDirective:
    """AST node for window_ms[start, end] or window[full] directive."""
    start_ms: Optional[float] = None
    end_ms: Optional[float] = None
    is_full: bool = False


@dataclass
class OverlayGroup:
    """AST node for [expr1, expr2, ...] overlay groups."""
    expressions: List[ExprNode]


PipelineItem = Union[WindowDirective, ExprNode, OverlayGroup]


# ════════════════════════════════════════════════════════════════════════════════
# DSL PARSER
# ════════════════════════════════════════════════════════════════════════════════

class DSLParser:
    """Parse pipeline_cfg DSL strings into AST nodes."""

    _WINDOW_RE = re.compile(
        r'^window_ms\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]$'
    )
    _WINDOW_FULL_RE = re.compile(
        r'^window_ms\[full\]$'
    )
    _SOURCE_RE = re.compile(
        r'^(mea_trace|ca_trace|rtsort)\(([^)]+)\)$'
    )

    def parse_pipeline(self, pipeline_cfg: List) -> List[PipelineItem]:
        items: List[PipelineItem] = []
        for entry in pipeline_cfg:
            if isinstance(entry, list):
                exprs = [self._parse_expression(e) for e in entry]
                items.append(OverlayGroup(expressions=exprs))
            elif isinstance(entry, str):
                items.append(self._parse_string(entry))
            else:
                raise ValueError(f"Invalid pipeline entry type: {type(entry)}")
        return items

    def _parse_string(self, s: str) -> PipelineItem:
        s = s.strip()
        m = self._WINDOW_RE.match(s)
        if m:
            return WindowDirective(start_ms=float(m.group(1)), end_ms=float(m.group(2)))
        m = self._WINDOW_FULL_RE.match(s)
        if m:
            return WindowDirective(is_full=True)
        return self._parse_expression(s)

    def _parse_expression(self, s: str) -> ExprNode:
        s = s.strip()
        tokens = self._tokenize_dotchain(s)
        if not tokens:
            raise ValueError(f"Empty expression: '{s}'")
        source = self._parse_source_token(tokens[0])
        ops = [self._parse_op_token(tok) for tok in tokens[1:]]
        return ExprNode(source=source, ops=ops)

    def _tokenize_dotchain(self, s: str) -> List[str]:
        """Split on dots, respecting parenthesis nesting."""
        tokens = []
        current: List[str] = []
        depth = 0

        for ch in s:
            if ch == '(':
                depth += 1
                current.append(ch)
            elif ch == ')':
                depth -= 1
                current.append(ch)
            elif ch == '.' and depth == 0:
                token = ''.join(current).strip()
                if token:
                    tokens.append(token)
                current = []
            else:
                current.append(ch)

        token = ''.join(current).strip()
        if token:
            tokens.append(token)
        return tokens

    def _parse_source_token(self, token: str) -> SourceNode:
        m = self._SOURCE_RE.match(token)
        if not m:
            raise ValueError(
                f"Invalid source token: '{token}'. "
                f"Expected mea_trace(N), ca_trace(N), rtsort(N), or mea_trace(all)."
            )
        source_type = m.group(1)
        id_str = m.group(2).strip()
        if id_str == 'all':
            source_id: Union[int, str] = 'all'
        else:
            try:
                source_id = int(id_str)
            except ValueError:
                raise ValueError(f"Source ID must be int or 'all', got: '{id_str}'")
        return SourceNode(source_type=source_type, source_id=source_id)

    def _parse_op_token(self, token: str) -> OpNode:
        paren_idx = token.find('(')
        if paren_idx == -1:
            return OpNode(op_name=token)

        op_name = token[:paren_idx]
        inner = self._extract_paren_content(token, paren_idx)

        if self._is_kwargs(inner):
            kwargs = self._parse_kwargs(inner)
            return OpNode(op_name=op_name, kwargs_overrides=kwargs)
        else:
            inner_expr = self._parse_expression(inner)
            return OpNode(op_name=op_name, inner_expr=inner_expr)

    def _extract_paren_content(self, token: str, open_idx: int) -> str:
        depth = 0
        for i in range(open_idx, len(token)):
            if token[i] == '(':
                depth += 1
            elif token[i] == ')':
                depth -= 1
                if depth == 0:
                    return token[open_idx + 1:i]
        raise ValueError(f"Unmatched parenthesis in: '{token}'")

    def _is_kwargs(self, inner: str) -> bool:
        """If inner contains '=' at parenthesis depth 0, it's kwargs."""
        depth = 0
        for ch in inner:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == '=' and depth == 0:
                return True
        return False

    def _parse_kwargs(self, inner: str) -> Dict[str, Any]:
        parts = self._split_top_level(inner, ',')
        kwargs: Dict[str, Any] = {}
        for part in parts:
            part = part.strip()
            if '=' not in part:
                raise ValueError(f"Expected key=value, got: '{part}'")
            key, val_str = part.split('=', 1)
            kwargs[key.strip()] = self._parse_value(val_str.strip())
        return kwargs

    def _split_top_level(self, s: str, delimiter: str) -> List[str]:
        parts: List[str] = []
        current: List[str] = []
        depth = 0
        for ch in s:
            if ch in '([':
                depth += 1
            elif ch in ')]':
                depth -= 1
            if ch == delimiter and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append(''.join(current))
        return parts

    def _parse_value(self, val_str: str) -> Any:
        val_str = val_str.strip()

        # Parse list literals like [1, 2, 3]
        if val_str.startswith('[') and val_str.endswith(']'):
            inner = val_str[1:-1].strip()
            if not inner:
                return []
            elements = self._split_top_level(inner, ',')
            return [self._parse_value(elem.strip()) for elem in elements]

        try:
            return int(val_str)
        except ValueError:
            pass
        try:
            return float(val_str)
        except ValueError:
            pass
        if val_str.lower() == 'true':
            return True
        if val_str.lower() == 'false':
            return False
        if val_str.lower() == 'none':
            return None
        if (val_str.startswith('"') and val_str.endswith('"')) or \
           (val_str.startswith("'") and val_str.endswith("'")):
            return val_str[1:-1]
        return val_str


# ════════════════════════════════════════════════════════════════════════════════
# CACHE SYSTEM
# ════════════════════════════════════════════════════════════════════════════════

class PipelineCache:
    """Two-tier cache: in-memory prefix reuse + optional disk cache.

    For project-scoped caches, pass ``cache_dir = <project>/.cache``. The
    cache machinery is identical; only the directory changes, so each
    project gets an isolated cache without any special code path.
    """

    def __init__(self, cache_dir: Optional[str] = None, source_paths: Optional[Dict[str, str]] = None,
                 memory_cache: bool = True, disk_cache: bool = True):
        self._memory: Dict[str, Any] = {}
        self._memory_enabled = memory_cache
        self._disk_enabled = disk_cache
        self._cache_dir: Optional[Path] = Path(cache_dir) if cache_dir and disk_cache else None
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._stats = {"hits": 0, "misses": 0, "disk_hits": 0}
        self._file_fingerprints = self._compute_fingerprints(source_paths or {})

    def _compute_fingerprints(self, paths: Dict[str, str]) -> Dict[str, float]:
        skip = {'output_dir', 'cache_dir'}
        fps = {}
        for k, v in paths.items():
            if k not in skip and v and Path(v).is_file():
                fps[k] = Path(v).stat().st_mtime
        return fps

    def make_key(self, window_ms: Tuple[float, float],
                 expr_parts: Tuple, ops_cfg: Dict[str, Dict],
                 margin: int = 0) -> str:
        key_data = {
            "window_ms": list(window_ms),
            "margin": margin,
            "expr": self._serialize_parts(expr_parts, ops_cfg),
            "files": self._file_fingerprints,
        }
        return json.dumps(key_data, sort_keys=True, default=str)

    def _serialize_parts(self, parts: Tuple, ops_cfg: Dict) -> list:
        result = []
        for item in parts:
            if isinstance(item, tuple) and len(item) == 3 and isinstance(item[0], str):
                # Op tuple from OpNode.cache_key_parts(): (op_name, kwargs_tuple, inner)
                op_name, kwargs_tuple, inner = item
                merged = {**ops_cfg.get(op_name, {}), **dict(kwargs_tuple or ())}
                inner_serialized = self._serialize_parts(inner, ops_cfg) if inner else None
                result.append({"op": op_name, "params": merged, "inner": inner_serialized})
            elif isinstance(item, tuple) and len(item) == 2:
                # Source tuple from SourceNode.cache_key_parts(): (source_type, source_id)
                key, val = item
                if isinstance(key, str) and key in ops_cfg:
                    merged = {**ops_cfg.get(key, {})}
                    if isinstance(val, tuple):
                        merged.update(dict(val))
                    result.append({"op": key, "params": merged})
                else:
                    result.append([key, val])
            else:
                result.append(item if not isinstance(item, tuple) else list(item))
        return result

    def make_prefix_key(self, window_ms: Tuple[float, float],
                        source: SourceNode, ops: List[OpNode],
                        ops_cfg: Dict, margin: int = 0) -> str:
        partial = ExprNode(source=source, ops=list(ops))
        return self.make_key(window_ms, partial.cache_key_parts(), ops_cfg, margin)

    def mem_get(self, key: str) -> Optional[Any]:
        if not self._memory_enabled:
            return None
        result = self._memory.get(key)
        if result is not None:
            self._stats["hits"] += 1
        return result

    def mem_put(self, key: str, value: Any) -> None:
        if not self._memory_enabled:
            return
        self._memory[key] = value

    def find_longest_prefix(self, window_ms: Tuple[float, float],
                            expr: ExprNode, ops_cfg: Dict,
                            margin: int = 0) -> Tuple[int, Any]:
        """Find longest cached prefix. Returns (prefix_len, cached_result).
        prefix_len == len(expr.ops) means full result cached.
        prefix_len == -1 means nothing found."""
        if not self._memory_enabled and not self._disk_enabled:
            self._stats["misses"] += 1
            return (-1, None)
        for n in range(len(expr.ops), -1, -1):
            key = self.make_prefix_key(window_ms, expr.source, expr.ops[:n], ops_cfg, margin)
            if self._memory_enabled:
                cached = self._memory.get(key)
                if cached is not None:
                    self._stats["hits"] += 1
                    return (n, cached)
            if self._disk_enabled:
                disk_result = self.disk_get_result(key)
                if disk_result is not None:
                    if self._memory_enabled:
                        self._memory[key] = disk_result
                    return (n, disk_result)
        self._stats["misses"] += 1
        return (-1, None)

    # -- Disk cache --

    def _disk_hash(self, key: str) -> str:
        return hashlib.md5(key.encode()).hexdigest()[:16]

    def disk_put_result(self, key: str, obj: Any) -> None:
        if not self._cache_dir:
            return
        path = self._cache_dir / f"pipeline_{self._disk_hash(key)}.pkl"
        try:
            with open(path, 'wb') as f:
                pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            pass  # best-effort, never crash pipeline

    def disk_get_result(self, key: str) -> Optional[Any]:
        if not self._cache_dir:
            return None
        path = self._cache_dir / f"pipeline_{self._disk_hash(key)}.pkl"
        if not path.exists():
            return None
        self._stats["disk_hits"] += 1
        try:
            with open(path, 'rb') as f:
                return pickle.load(f)
        except Exception:
            return None

    def disk_get(self, key: str) -> Optional[Dict[str, np.ndarray]]:
        if not self._cache_dir:
            return None
        path = self._cache_dir / f"pipeline_{self._disk_hash(key)}.npz"
        if path.exists():
            self._stats["disk_hits"] += 1
            data = np.load(path, allow_pickle=True)
            return {k: data[k] for k in data.files}
        return None

    def disk_put(self, key: str, **arrays: np.ndarray) -> None:
        if not self._cache_dir:
            return
        path = self._cache_dir / f"pipeline_{self._disk_hash(key)}.npz"
        np.savez(path, **arrays)

    def clear_memory(self) -> None:
        self._memory.clear()

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)


# ════════════════════════════════════════════════════════════════════════════════
# PIPELINE EXECUTOR
# ════════════════════════════════════════════════════════════════════════════════

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

    def _load_source(self, source: SourceNode, margin_samples: int = 0) -> Any:
        loader_key = source.source_type
        if loader_key not in self.source_loaders:
            raise KeyError(
                f"No source loader registered for '{loader_key}'. "
                f"Available: {list(self.source_loaders.keys())}"
            )
        return self.source_loaders[loader_key](source.source_id, self.ctx, margin_samples)

    def _apply_op(self, op: OpNode, current: Any) -> Any:
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

    def _apply_op_to_bank(self, op: OpNode, bank: MEABank) -> Any:
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

    def _apply_op_to_rt_bank(self, op: OpNode, bank: RTBank) -> Any:
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

    def _apply_function_op(self, op: OpNode, left: Any) -> Any:
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
                import re as _re
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
                        from casi.sessions import write_provenance_sidecar
                        write_provenance_sidecar(plot_path, self.ctx)
                    except Exception as e:
                        if self.ctx.verbose:
                            print(f"  [provenance sidecar skipped: {e}]")
                    _orig_show(*a, **kw)
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


# ════════════════════════════════════════════════════════════════════════════════
# TOP-LEVEL API
# ════════════════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL DATA CACHES
# ════════════════════════════════════════════════════════════════════════════════

_mea_recording_cache: Dict[str, Any] = {}
_rtsort_cache: Dict[str, Any] = {}
_calcium_cache: Dict[str, Any] = {}
_rtsort_model_cache: Dict[str, Any] = {}


# ════════════════════════════════════════════════════════════════════════════════
# MEA / CA / RTSORT HELPERS
# ════════════════════════════════════════════════════════════════════════════════

def _load_mea_recording(ctx: PipelineContext):
    """Load MaxwellRecordingExtractor, cache the object."""
    path = ctx.paths["mea_h5"]
    if path not in _mea_recording_cache:
        print(f"  Loading MEA recording from: {path}")
        _mea_recording_cache[path] = MaxwellRecordingExtractor(path)
    return _mea_recording_cache[path]


def _get_mea_metadata(recording) -> Dict[str, Any]:
    """Extract channel IDs, electrode positions from recording."""
    return {
        "channel_ids":  recording.get_channel_ids(),
        "locations":    recording.get_channel_locations(),
        "num_channels": recording.get_num_channels(),
        "num_samples":  recording.get_num_samples(),
    }


def get_recording_duration_ms(ctx: PipelineContext) -> float:
    """Get the full duration of the MEA recording in milliseconds."""
    recording = _load_mea_recording(ctx)
    num_samples = recording.get_num_samples()
    return (num_samples / ctx.mea_fs_hz) * 1000


def clear_data_caches() -> None:
    """Clear in-memory recording/calcium/rtsort caches to free memory."""
    _mea_recording_cache.clear()
    _rtsort_cache.clear()
    _calcium_cache.clear()
    _rtsort_model_cache.clear()


def clear_pipeline_cache(cache_dir: str) -> None:
    """Delete all disk-cached pipeline results (*.pkl) in cache_dir."""
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return
    deleted = 0
    for f in cache_path.glob("pipeline_*.pkl"):
        f.unlink()
        deleted += 1
    print(f"[cache] Cleared {deleted} disk cache file(s) from {cache_dir}")


def _load_rtsort_model(model_dir: str) -> Tuple[Any, dict]:
    """Load and cache RTSort ModelSpikeSorter for CPU inference.
    Returns (conv_module, model_info_dict)."""
    if model_dir in _rtsort_model_cache:
        return _rtsort_model_cache[model_dir]

    try:
        from braindance.core.spikedetector.model import ModelSpikeSorter
    except ImportError as e:
        raise ImportError(
            "The rt_detect operation requires braindance, which is not on PyPI.\n"
            "Install it separately with:\n"
            "    pip install --no-deps git+https://github.com/braingeneers/braindance\n"
            "Then re-run your pipeline."
        ) from e

    model_path = Path(model_dir)
    with open(model_path / "init_dict.json") as f:
        init_dict = json.load(f)

    init_dict["device"] = "cpu"
    model = ModelSpikeSorter(**init_dict)
    model.load_state_dict(
        torch.load(model_path / "state_dict.pt", map_location="cpu")
    )
    model.to(dtype=torch.float32)
    model.eval()

    assert hasattr(model.model, 'conv'), (
        "RTSort model must use ModelTuning architecture (has .conv subnet). "
        "RMSThresh baseline is not supported for pipeline inference."
    )
    conv = model.model.conv
    info = {
        "sample_size": model.sample_size,
        "num_output_locs": model.num_output_locs,
        "input_scale": model.input_scale,
        "buffer_front": model.buffer_front_sample,
        "buffer_end": model.buffer_end_sample,
    }
    result = (conv, info)
    _rtsort_model_cache[model_dir] = result
    print(f"  Loaded RTSort model from {model_dir} (sample_size={info['sample_size']}, "
          f"output_locs={info['num_output_locs']})")
    return result


# ════════════════════════════════════════════════════════════════════════════════
# SOURCE LOADERS
# ════════════════════════════════════════════════════════════════════════════════

def load_mea_trace(source_id, ctx: PipelineContext, margin_samples: int = 0):
    """Source loader for mea_trace(CH) and mea_trace(all)."""
    recording = _load_mea_recording(ctx)
    meta = _get_mea_metadata(recording)
    ws = ctx.window_samples_mea
    start, end = ws
    total_samples = meta["num_samples"]

    ext_start = max(0, start - margin_samples)
    ext_end = min(total_samples, end + margin_samples)
    margin_left = start - ext_start
    margin_right = ext_end - end

    if source_id == 'all':
        traces = recording.get_traces(
            start_frame=ext_start, end_frame=ext_end, return_in_uV=True
        ).T  # (n_channels, n_samples)
        print(f"  Loaded {traces.shape[0]} MEA channels x {traces.shape[1]} samples")
        return MEABank(
            traces=traces,
            fs_hz=ctx.mea_fs_hz,
            channel_ids=meta["channel_ids"],
            locations=meta["locations"],
            window_samples=ws,
            margin_left=margin_left,
            margin_right=margin_right,
            label="raw",
        )
    else:
        ch_idx = int(source_id)
        trace = recording.get_traces(
            channel_ids=[str(ch_idx)],
            start_frame=ext_start, end_frame=ext_end,
            return_in_uV=True
        ).flatten()
        return MEATrace(
            data=trace,
            fs_hz=ctx.mea_fs_hz,
            channel_idx=ch_idx,
            window_samples=ws,
            margin_left=margin_left,
            margin_right=margin_right,
            label="raw",
        )


def load_ca_trace(source_id, ctx: PipelineContext, margin_samples: int = 0):
    """Source loader for ca_trace(IDX). Loads, trims edges, interpolates to MEA grid."""
    path = ctx.paths["ca_traces_npz"]
    if path not in _calcium_cache:
        print(f"  Loading calcium traces from: {path}")
        data = np.load(path)
        ca_traces = np.asarray(data["ca_traces"])[:, 5:-25]
        ca_frames = np.asarray(data["frames"])[5:-25]
        _calcium_cache[path] = {"traces": ca_traces, "frames": ca_frames}

    ca_data = _calcium_cache[path]
    tr_idx = int(source_id)
    ca_trace = ca_data["traces"][tr_idx]
    ca_frames = ca_data["frames"]
    ws = ctx.window_samples_mea

    start_sample, end_sample = ws
    target_frames = np.arange(start_sample, end_sample)
    ca_interp = np.interp(target_frames, ca_frames, ca_trace)

    return CATrace(
        data=ca_interp,
        fs_hz=ctx.mea_fs_hz,
        trace_idx=tr_idx,
        window_samples=ws,
        original_data=ca_trace,
        original_frames=ca_frames,
        label="real",
    )


def load_rtsort(source_id, ctx: PipelineContext, margin_samples: int = 0):
    """Source loader for rtsort(CH). CH is a channel ID (same as mea_trace)."""
    path = ctx.paths["rt_model_outputs_npy"]
    if path not in _rtsort_cache:
        print(f"  Loading RTSort outputs from: {path}")
        _rtsort_cache[path] = np.load(path)

    recording = _load_mea_recording(ctx)
    channel_ids = _get_mea_metadata(recording)["channel_ids"]
    ch_id = str(source_id)
    matches = np.where(channel_ids == ch_id)[0]
    if len(matches) == 0:
        raise ValueError(
            f"Channel ID '{ch_id}' not found in recording. "
            f"Available IDs: {channel_ids[:10]}...{channel_ids[-10:]}"
        )
    row_idx = matches[0]

    ws = ctx.window_samples_rtsort
    start, end = ws
    raw = _rtsort_cache[path][row_idx, start:end]

    return RTTrace(
        data=raw,
        fs_hz=ctx.rtsort_fs_hz,
        channel_idx=int(source_id),
        window_samples=(start, start + len(raw)),
        label="raw",
    )


# ════════════════════════════════════════════════════════════════════════════════
# SIGNAL PROCESSING HELPERS
# ════════════════════════════════════════════════════════════════════════════════

def detect_spikes_constant_rms(signal, fs, k, min_distance_ms, prominence=None):
    """Detect spikes using constant RMS threshold (negative polarity)."""
    threshold = -k * np.std(signal)
    distance = int(min_distance_ms * fs / 1000)
    kwargs = {"height": -threshold, "distance": distance}
    if prominence is not None:
        kwargs["prominence"] = prominence
    spike_indices, props = find_peaks(-signal, **kwargs)
    spike_values = signal[spike_indices]
    threshold_curve = np.full(len(signal), threshold)
    return threshold_curve, spike_indices, spike_values


def detect_spikes_sliding_rms(signal, fs, k, half_window_ms, min_spike_distance_ms,
                               min_nonzero_fraction=0.2, zero_eps=1e-4, zero_buffer_ms=0.0,
                               prominence=None):
    """Detect spikes using sliding RMS threshold (negative polarity)."""
    N = len(signal)
    half_w = int(round(half_window_ms * fs / 1000.0))
    wlen = 2 * half_w + 1
    min_count = max(1, int(round(wlen * min_nonzero_fraction)))

    nz = (np.abs(signal) > zero_eps)
    x2 = (signal * signal) * nz

    csum = np.empty(N + 1, dtype=float)
    csum[0] = 0.0
    np.cumsum(x2, out=csum[1:])

    ccount = np.empty(N + 1, dtype=np.int64)
    ccount[0] = 0
    np.cumsum(nz.astype(np.int64), out=ccount[1:])

    idx = np.arange(N)
    lo = np.clip(idx - half_w, 0, N)
    hi = np.clip(idx + half_w + 1, 0, N)

    ss = csum[hi] - csum[lo]
    nn = ccount[hi] - ccount[lo]

    rms = np.sqrt(ss / np.maximum(nn, 1))
    rms[nn < min_count] = np.nan
    threshold = -k * rms

    invalid = ~nz
    if zero_buffer_ms > 0:
        buf = int(round(zero_buffer_ms * fs / 1000.0))
        if buf > 0:
            kern = np.ones(2 * buf + 1, dtype=int)
            invalid = np.convolve(invalid.astype(int), kern, mode="same") > 0

    valid = (~invalid) & np.isfinite(threshold)
    distance = int(round(min_spike_distance_ms * fs / 1000.0))

    s_for_peaks = -signal.copy()
    s_for_peaks[~valid] = -np.inf

    kwargs = {"distance": distance}
    if prominence is not None:
        kwargs["prominence"] = prominence
    peak_idx, _ = find_peaks(s_for_peaks, **kwargs)

    keep = valid[peak_idx] & (signal[peak_idx] < threshold[peak_idx])
    spike_indices = peak_idx[keep]
    spike_values = signal[spike_indices]

    return threshold, spike_indices, spike_values


def cross_correlate_pair(ca_signal, sim_trace, max_lag_samples, normalize=True):
    """Max cross-correlation between calcium and simulated trace."""
    min_len = min(len(ca_signal), len(sim_trace))
    ca = ca_signal[:min_len]
    sim = sim_trace[:min_len]
    if normalize:
        ca = (ca - np.mean(ca)) / (np.std(ca) + 1e-10)
        sim = (sim - np.mean(sim)) / (np.std(sim) + 1e-10)
    corr = correlate(ca, sim, mode='same') / min_len
    center = len(corr) // 2
    return np.max(corr[center - max_lag_samples:center + max_lag_samples + 1])


# ════════════════════════════════════════════════════════════════════════════════
# OP HANDLERS
# ════════════════════════════════════════════════════════════════════════════════

def op_butter_bandpass(inp: MEATrace, ctx: PipelineContext, *,
                       low_hz, high_hz, order, zero_phase=True) -> MEATrace:
    """Butterworth bandpass filter. Filters extended data then trims margins."""
    nyq = inp.fs_hz * 0.5
    b, a = butter(order, [low_hz / nyq, high_hz / nyq], btype='band')
    if zero_phase:
        filtered = filtfilt(b, a, inp.data)
    else:
        from scipy.signal import lfilter
        filtered = lfilter(b, a, inp.data)

    ml, mr = inp.margin_left, inp.margin_right
    if ml > 0 or mr > 0:
        end = len(filtered) - mr if mr > 0 else len(filtered)
        filtered = filtered[ml:end]

    return MEATrace(
        data=filtered,
        fs_hz=inp.fs_hz,
        channel_idx=inp.channel_idx,
        window_samples=inp.window_samples,
        margin_left=0, margin_right=0,
        label="bandpass",
    )


def op_notch_filter(inp: MEATrace, ctx: PipelineContext, *,
                    notch_freq_hz, notch_q, harmonics=None) -> MEATrace:
    """Notch filter with optional harmonics. Filters extended data then trims margins."""
    if harmonics is None:
        harmonics = [1]

    filtered = inp.data.copy()
    for harmonic in harmonics:
        freq = notch_freq_hz * harmonic
        b, a = iirnotch(freq, notch_q, inp.fs_hz)
        sos = tf2sos(b, a)
        filtered = sosfiltfilt(sos, filtered)

    ml, mr = inp.margin_left, inp.margin_right
    if ml > 0 or mr > 0:
        end = len(filtered) - mr if mr > 0 else len(filtered)
        filtered = filtered[ml:end]

    return MEATrace(
        data=filtered,
        fs_hz=inp.fs_hz,
        channel_idx=inp.channel_idx,
        window_samples=inp.window_samples,
        margin_left=0, margin_right=0,
        label="notch",
    )


def op_sliding_rms(inp: MEATrace, ctx: PipelineContext, *,
                   k, half_window_ms, min_spike_distance_ms,
                   min_nonzero_fraction=0.2, zero_eps=1e-4,
                   zero_buffer_ms=0.0) -> SpikeTrain:
    """Sliding RMS spike detection."""
    signal = inp.trimmed_data if hasattr(inp, 'trimmed_data') else inp.data
    fs = inp.fs_hz
    threshold, spike_indices, spike_values = detect_spikes_sliding_rms(
        signal, fs, k, half_window_ms, min_spike_distance_ms,
        min_nonzero_fraction, zero_eps, zero_buffer_ms
    )
    return SpikeTrain(
        spike_indices=spike_indices,
        spike_values=spike_values,
        threshold_curve=threshold,
        source_signal=signal,
        fs_hz=fs,
        source_id=inp.channel_idx if hasattr(inp, 'channel_idx') else 0,
        window_samples=inp.window_samples,
        label="sliding_rms",
    )


def op_constant_rms(inp: MEATrace, ctx: PipelineContext, *,
                    k, min_spike_distance_ms) -> SpikeTrain:
    """Constant RMS spike detection."""
    signal = inp.trimmed_data if hasattr(inp, 'trimmed_data') else inp.data
    fs = inp.fs_hz
    threshold, spike_indices, spike_values = detect_spikes_constant_rms(
        signal, fs, k, min_spike_distance_ms
    )
    return SpikeTrain(
        spike_indices=spike_indices,
        spike_values=spike_values,
        threshold_curve=threshold,
        source_signal=signal,
        fs_hz=fs,
        source_id=inp.channel_idx if hasattr(inp, 'channel_idx') else 0,
        window_samples=inp.window_samples,
        label="constant_rms",
    )


def op_spike_pca(inp: SpikeTrain, ctx: PipelineContext, *,
                 snippet_ms=1.5, n_components=3, outlier_std=2.5,
                 min_spikes=10) -> SpikePCA:
    """Project spike waveforms into PCA space and flag outliers by centroid distance."""
    fs = inp.fs_hz
    snippet_len = int(snippet_ms * fs / 1000)
    if snippet_len % 2 == 0:
        snippet_len += 1
    half = snippet_len // 2

    def _degenerate(indices, values):
        n = len(indices)
        return SpikePCA(
            spike_indices=indices,
            spike_values=values,
            waveforms=np.empty((n, snippet_len)),
            pca_projections=np.empty((n, 0)),
            pca_components=np.empty((0, snippet_len)),
            explained_variance_ratio=np.array([]),
            centroid=np.array([]),
            distances=np.zeros(n),
            outlier_mask=np.zeros(n, dtype=bool),
            source_signal=inp.source_signal,
            threshold_curve=inp.threshold_curve,
            fs_hz=fs,
            source_id=inp.source_id,
            window_samples=inp.window_samples,
            label="spike_pca",
        )

    if inp.num_spikes < min_spikes:
        print(f"  spike_pca: too few spikes ({inp.num_spikes} < {min_spikes}), skipping PCA")
        return _degenerate(inp.spike_indices, inp.spike_values)

    sig = inp.source_signal
    sig_len = len(sig)
    valid_idx = []
    waveform_list = []
    for i, idx in enumerate(inp.spike_indices):
        start = idx - half
        end = idx + half + 1
        if start < 0 or end > sig_len:
            continue
        waveform_list.append(sig[start:end])
        valid_idx.append(i)

    n_valid = len(valid_idx)
    if n_valid < min_spikes:
        print(f"  spike_pca: too few valid waveforms after boundary check "
              f"({n_valid} < {min_spikes}), skipping PCA")
        return _degenerate(inp.spike_indices, inp.spike_values)

    valid_idx = np.array(valid_idx)
    spike_indices = inp.spike_indices[valid_idx]
    spike_values = inp.spike_values[valid_idx]
    waveforms = np.array(waveform_list)

    nc = min(n_components, n_valid - 1, snippet_len)
    if nc < 1:
        print(f"  spike_pca: cannot compute PCA (n_valid={n_valid}), skipping")
        return _degenerate(spike_indices, spike_values)

    centered = waveforms - waveforms.mean(axis=0)
    U, S, Vt = np.linalg.svd(centered, full_matrices=False)

    pca_components = Vt[:nc]
    projections = centered @ pca_components.T
    total_var = (S ** 2).sum()
    explained_variance_ratio = (S[:nc] ** 2) / total_var if total_var > 0 else np.zeros(nc)

    centroid = projections.mean(axis=0)
    distances = np.linalg.norm(projections - centroid, axis=1)
    dist_mean = distances.mean()
    dist_std = distances.std()
    outlier_mask = distances > (dist_mean + outlier_std * dist_std)

    n_out = int(outlier_mask.sum())
    print(f"  spike_pca: {n_valid} waveforms, {nc} components "
          f"({explained_variance_ratio.sum() * 100:.1f}% var), "
          f"{n_out} outliers ({n_out / n_valid * 100:.1f}%)")

    return SpikePCA(
        spike_indices=spike_indices,
        spike_values=spike_values,
        waveforms=waveforms,
        pca_projections=projections,
        pca_components=pca_components,
        explained_variance_ratio=explained_variance_ratio,
        centroid=centroid,
        distances=distances,
        outlier_mask=outlier_mask,
        source_signal=inp.source_signal,
        threshold_curve=inp.threshold_curve,
        fs_hz=fs,
        source_id=inp.source_id,
        window_samples=inp.window_samples,
        label="spike_pca",
    )


def op_spike_curate(left: SpikePCA, right: CATrace, ctx: PipelineContext, *,
                    corr_threshold=0.005, max_lag_ms=500.0) -> SpikeTrain:
    """Iteratively remove PCA outlier spikes guided by cross-correlation improvement.

    For each candidate outlier (farthest from PCA centroid first), temporarily
    remove it from the spike train, regenerate the simulated calcium trace, and
    cross-correlate against the real calcium trace.  If correlation improves by
    at least `corr_threshold`, the spike is permanently excluded.
    """
    if not isinstance(left, SpikePCA):
        raise TypeError(f"spike_curate left operand must be SpikePCA, got {type(left).__name__}")
    if not isinstance(right, CATrace):
        raise TypeError(f"spike_curate right operand must be CATrace, got {type(right).__name__}")

    inp = left
    n_total = len(inp.spike_indices)
    if n_total == 0:
        print("  spike_curate: no spikes to curate")
        return SpikeTrain(
            spike_indices=inp.spike_indices, spike_values=inp.spike_values,
            threshold_curve=inp.threshold_curve, source_signal=inp.source_signal,
            fs_hz=inp.fs_hz, source_id=inp.source_id,
            window_samples=inp.window_samples, label="spike_curate",
        )

    # Build GCaMP kernel from ops_cfg
    gcamp_cfg = ctx.ops_cfg.get("gcamp_sim", {})
    kernel = _build_gcamp_kernel(
        inp.fs_hz,
        gcamp_cfg.get("half_rise_ms", 80.0),
        gcamp_cfg.get("half_decay_ms", 500.0),
        gcamp_cfg.get("duration_ms", 2500.0),
        gcamp_cfg.get("peak_dff", 0.20),
    )
    max_lag_samples = int(max_lag_ms * right.fs_hz / 1000)
    ca_signal = right.data
    num_samples = len(inp.source_signal)

    def _sim_and_correlate(indices):
        """Generate sim calcium from spike indices and correlate with real CA."""
        spike_arr = np.zeros(num_samples)
        if len(indices) > 0:
            spike_arr[indices] = 1
        sim = convolve(spike_arr, kernel, mode='full')[:num_samples]
        return cross_correlate_pair(ca_signal, sim, max_lag_samples)

    # Baseline correlation with all spikes
    keep_mask = np.ones(n_total, dtype=bool)
    baseline_corr = _sim_and_correlate(inp.spike_indices)

    # Rank outlier candidates by distance (farthest first)
    candidate_idx = np.where(inp.outlier_mask)[0]
    candidate_idx = candidate_idx[np.argsort(-inp.distances[candidate_idx])]

    n_removed = 0
    current_corr = baseline_corr
    for ci in candidate_idx:
        # Temporarily remove this spike
        test_mask = keep_mask.copy()
        test_mask[ci] = False
        test_corr = _sim_and_correlate(inp.spike_indices[test_mask])

        if test_corr >= current_corr + corr_threshold:
            keep_mask[ci] = False
            current_corr = test_corr
            n_removed += 1

    print(f"  spike_curate: removed {n_removed}/{n_total} spikes "
          f"(corr {baseline_corr:.4f} → {current_corr:.4f})")

    curated_indices = inp.spike_indices[keep_mask]
    curated_values = inp.spike_values[keep_mask]
    return SpikeTrain(
        spike_indices=curated_indices,
        spike_values=curated_values,
        threshold_curve=inp.threshold_curve,
        source_signal=inp.source_signal,
        fs_hz=inp.fs_hz,
        source_id=inp.source_id,
        window_samples=inp.window_samples,
        label="spike_curate",
    )


def op_baseline_correction(inp: CATrace, ctx: PipelineContext, *,
                            window_frames, percentile) -> CATrace:
    """Percentile baseline correction for calcium traces."""
    if inp.original_data is not None:
        baseline = percentile_filter(
            inp.original_data.astype(float), percentile,
            size=window_frames, mode='nearest')
        corrected_orig = inp.original_data - baseline + np.mean(inp.original_data)

        start_sample, end_sample = inp.window_samples
        target_frames = np.arange(start_sample, end_sample)
        corrected_interp = np.interp(target_frames, inp.original_frames, corrected_orig)
        baseline_interp = np.interp(target_frames, inp.original_frames, baseline)
    else:
        baseline_arr = percentile_filter(
            inp.data.astype(float), percentile,
            size=window_frames, mode='nearest')
        corrected_interp = inp.data - baseline_arr + np.mean(inp.data)
        baseline_interp = baseline_arr

    return CATrace(
        data=corrected_interp,
        fs_hz=inp.fs_hz,
        trace_idx=inp.trace_idx,
        window_samples=inp.window_samples,
        original_data=inp.original_data,
        original_frames=inp.original_frames,
        baseline=baseline_interp,
        label="baseline_corrected",
    )


def op_rt_detect(inp: MEATrace, ctx: PipelineContext, *,
                     inference_scaling_numerator=12.6,
                     pre_median_frames=None) -> RTTrace:
    """Run RTSort detection model on a single MEA trace, producing logits."""
    conv, info = _load_rtsort_model(ctx.paths["rt_model_path"])
    sample_size = info["sample_size"]
    num_output_locs = info["num_output_locs"]
    input_scale = info["input_scale"]
    buf_front = info["buffer_front"]
    buf_end = info["buffer_end"]

    data = inp.trimmed_data.astype(np.float32)
    n_samples = len(data)

    # IQR-based inference scaling (same as braindance run_detection_model)
    pre_n = min(pre_median_frames, n_samples) if pre_median_frames is not None else n_samples
    iqr_val = np.percentile(data[:pre_n], 75) - np.percentile(data[:pre_n], 25)
    inference_scaling = inference_scaling_numerator / max(iqr_val, 1e-6)

    # Allocate output
    out_len = n_samples - buf_front - buf_end
    if out_len <= 0:
        raise ValueError(
            f"Trace too short ({n_samples} samples) for model buffers "
            f"({buf_front}+{buf_end}={buf_front + buf_end})"
        )
    output = np.zeros(out_len, dtype=np.float32)

    # Sliding window inference
    all_starts = list(range(0, n_samples - sample_size + 1, num_output_locs))
    with torch.no_grad():
        for start in all_starts:
            chunk = data[start:start + sample_size].copy()
            chunk -= np.median(chunk)
            t = torch.tensor(chunk, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
            logits = conv(t * input_scale * inference_scaling).numpy()[0, 0, :]
            output[start:start + num_output_locs] = logits

        # Handle remaining frames at end of trace
        if all_starts:
            last_end = all_starts[-1] + sample_size
        else:
            last_end = 0
        remaining = n_samples - last_end
        if remaining > 0 and n_samples >= sample_size:
            chunk = data[-sample_size:].copy()
            chunk -= np.median(chunk)
            t = torch.tensor(chunk, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
            logits = conv(t * input_scale * inference_scaling).numpy()[0, 0, :]
            output[-remaining:] = logits[-remaining:]

    # Adjust window_samples for buffer trimming
    ws = inp.window_samples
    new_ws = (ws[0] + buf_front, ws[1] - buf_end)

    return RTTrace(
        data=output,
        fs_hz=inp.fs_hz,
        channel_idx=inp.channel_idx,
        window_samples=new_ws,
        label="rt_detect",
    )


def op_sigmoid(inp: RTTrace, ctx: PipelineContext) -> RTTrace:
    """Apply sigmoid to raw RTSort logits."""
    sigmoid_data = 1.0 / (1.0 + np.exp(-inp.data))
    return RTTrace(
        data=sigmoid_data,
        fs_hz=inp.fs_hz,
        channel_idx=inp.channel_idx,
        window_samples=inp.window_samples,
        label="sigmoid",
    )


def op_rt_thresh(inp: RTTrace, ctx: PipelineContext, *, threshold) -> SpikeTrain:
    """Threshold RTSort sigmoid output to detect events."""
    distance = max(1, int(1.0 * inp.fs_hz / 1000))
    event_indices, _ = find_peaks(inp.data, height=threshold, distance=distance)
    event_values = inp.data[event_indices]
    threshold_curve = np.full(len(inp.data), threshold)

    return SpikeTrain(
        spike_indices=event_indices,
        spike_values=event_values,
        threshold_curve=threshold_curve,
        source_signal=inp.data,
        fs_hz=inp.fs_hz,
        source_id=inp.channel_idx,
        window_samples=inp.window_samples,
        label="rt_thresh",
    )


def _build_gcamp_kernel(fs, half_rise_ms, half_decay_ms, duration_ms, peak_dff):
    """Build GCaMP kernel (config in ms, converts internally to seconds)."""
    tau_rise = (half_rise_ms / 1000.0) / np.log(2)
    tau_decay = (half_decay_ms / 1000.0) / np.log(2)
    t = np.arange(0, duration_ms / 1000.0, 1 / fs)
    k = (1 - np.exp(-t / tau_rise)) * np.exp(-t / tau_decay)
    peak = k.max()
    if peak > 0:
        k *= peak_dff / peak
    else:
        raise ValueError("Kernel peak must be > 0")
    return k


def op_gcamp_sim(inp, ctx: PipelineContext, *,
                 half_rise_ms, half_decay_ms, duration_ms, peak_dff):
    """Simulate calcium trace from spike train via GCaMP kernel convolution."""
    fs = inp.fs_hz
    kernel = _build_gcamp_kernel(fs, half_rise_ms, half_decay_ms, duration_ms, peak_dff)

    if isinstance(inp, SpikeTrain):
        num_samples = len(inp.source_signal)
        spike_train_arr = np.zeros(num_samples)
        if len(inp.spike_indices) > 0:
            spike_train_arr[inp.spike_indices] = 1
        sim_data = convolve(spike_train_arr, kernel, mode='full')[:num_samples]

        return SimCalcium(
            data=sim_data,
            fs_hz=fs,
            source_id=inp.source_id,
            window_samples=inp.window_samples,
            spike_indices=inp.spike_indices,
            label="gcamp_sim",
        )

    elif isinstance(inp, _SpikeBankIntermediate):
        all_sim = []
        electrode_info = []
        for i, st in enumerate(tqdm(inp.spike_trains, desc="  gcamp_sim (all ch)", leave=False)):
            num_samples = len(st.source_signal)
            spike_train_arr = np.zeros(num_samples)
            if len(st.spike_indices) > 0:
                spike_train_arr[st.spike_indices] = 1
            sim_data = convolve(spike_train_arr, kernel, mode='full')[:num_samples]
            all_sim.append(sim_data)

            ch_id = inp.channel_ids[i]
            electrode_info.append({
                "channel":    int(ch_id) if str(ch_id).isdigit() else i,
                "electrode":  i,
                "x":          float(inp.locations[i][0]),
                "y":          float(inp.locations[i][1]),
                "num_spikes": len(st.spike_indices),
            })

        return SimCalciumBank(
            traces=np.array(all_sim),
            fs_hz=fs,
            channel_ids=inp.channel_ids,
            locations=inp.locations,
            electrode_info=electrode_info,
            window_samples=inp.window_samples,
            label="gcamp_sim_bank",
        )
    else:
        raise TypeError(f"gcamp_sim: unexpected input {type(inp).__name__}")


def op_x_corr(left: CATrace, right: SimCalciumBank, ctx: PipelineContext, *,
              max_lag_ms=500.0, normalize=True, adapt_circle_size=False) -> CorrelationResult:
    """Cross-correlate a calcium trace against a bank of simulated calcium traces."""
    if not isinstance(left, CATrace):
        raise TypeError(f"x_corr left operand must be CATrace, got {type(left).__name__}")
    if not isinstance(right, SimCalciumBank):
        raise TypeError(f"x_corr right operand must be SimCalciumBank, got {type(right).__name__}")

    max_lag_samples = int(max_lag_ms * left.fs_hz / 1000)
    ca_signal = left.data

    correlations = np.array([
        cross_correlate_pair(ca_signal, right.traces[i], max_lag_samples, normalize)
        for i in tqdm(range(right.traces.shape[0]), desc="  x_corr", leave=False)
    ])

    best_idx = int(np.argmax(correlations))
    x_coords = np.array([info["x"] for info in right.electrode_info])
    y_coords = np.array([info["y"] for info in right.electrode_info])

    pct_masked = None
    if adapt_circle_size:
        for cached_val in ctx.cache._memory.values():
            if isinstance(cached_val, SaturationReport):
                total = cached_val.total_samples
                sat_map = {
                    int(ch): (cached_val.samples_masked[i] / total * 100 if total > 0 else 0.0)
                    for i, ch in enumerate(cached_val.channel_ids)
                }
                pct_masked = np.array([sat_map.get(info["channel"], 0.0)
                                       for info in right.electrode_info])
                break

    return CorrelationResult(
        correlations=correlations,
        best_idx=best_idx,
        best_corr=correlations[best_idx],
        electrode_info=right.electrode_info,
        ca_trace_idx=left.trace_idx,
        x_coords=x_coords,
        y_coords=y_coords,
        ca_signal=ca_signal,
        best_sim_trace=right.traces[best_idx],
        window_samples=left.window_samples,
        fs_hz=left.fs_hz,
        label="x_corr",
        pct_masked=pct_masked,
    )


def op_spectrogram(inp: MEATrace, ctx: PipelineContext, *,
                   nperseg=256, noverlap=None, window='hann',
                   scaling='density', fmin=0, fmax=None, db_scale=True) -> Spectrogram:
    """Compute time-frequency spectrogram from MEATrace."""
    signal = inp.trimmed_data if hasattr(inp, 'trimmed_data') else inp.data
    fs = inp.fs_hz

    freqs, times, Sxx = _scipy_spectrogram(
        signal, fs=fs, window=window, nperseg=nperseg,
        noverlap=noverlap, scaling=scaling, mode='psd'
    )
    window_start_ms = inp.window_samples[0] / fs * 1000
    times_ms = times * 1000 + window_start_ms

    if fmax is None:
        fmax = fs / 2
    freq_mask = (freqs >= fmin) & (freqs <= fmax)
    freqs_filtered = freqs[freq_mask]
    Sxx_filtered = Sxx[freq_mask, :]

    if db_scale:
        Sxx_filtered = 10 * np.log10(Sxx_filtered + 1e-10)

    return Spectrogram(
        frequencies=freqs_filtered,
        times=times_ms,
        power=Sxx_filtered,
        fs_hz=fs,
        source_id=inp.channel_idx if hasattr(inp, 'channel_idx') else 0,
        window_samples=inp.window_samples,
        label="spectrogram",
    )


def op_freq_traces(inp: MEATrace, ctx: PipelineContext, *,
                   freqs_hz, broadband_range_hz,
                   nperseg=4096, noverlap=None, window='hann') -> FreqPowerTraces:
    """Compute power vs time at specific frequencies from MEATrace using STFT."""
    signal = inp.trimmed_data if hasattr(inp, 'trimmed_data') else inp.data
    fs = inp.fs_hz

    freqs, times_s, Sxx = _scipy_spectrogram(
        signal, fs=fs, window=window, nperseg=nperseg,
        noverlap=noverlap, scaling='density', mode='psd',
    )
    window_start_ms = inp.window_samples[0] / fs * 1000
    times_ms = times_s * 1000 + window_start_ms

    freq_traces_dict: Dict[float, np.ndarray] = {}
    for hz in freqs_hz:
        idx = int(np.argmin(np.abs(freqs - hz)))
        freq_traces_dict[float(hz)] = Sxx[idx, :]

    bb_low, bb_high = broadband_range_hz
    bb_mask = (freqs >= bb_low) & (freqs <= bb_high)
    broadband_power = Sxx[bb_mask, :].mean(axis=0)

    return FreqPowerTraces(
        times=times_ms,
        freq_traces=freq_traces_dict,
        broadband_power=broadband_power,
        broadband_range_hz=tuple(broadband_range_hz),
        fs_hz=fs,
        source_id=inp.channel_idx,
        window_samples=inp.window_samples,
    )


def op_saturation_mask(inp, ctx: PipelineContext, *,
                       min_run=20, eps_range=1.0,
                       lookahead=400, recovery_eps=5.0,
                       pre_samples=0, mode="fill_nan", scope="all",
                       sync_cut=False, drop_saturated_pct=None):
    # --- MEABank branch: bank-level operations (sync_cut / drop_saturated_pct) ---
    if isinstance(inp, MEABank):
        n_channels = inp.traces.shape[0]
        ml, mr = inp.margin_left, inp.margin_right
        total_samples = inp.traces.shape[1] - ml - (mr if mr > 0 else 0)
        min_run_i = int(min_run)
        lookahead_i = int(lookahead)

        lead_end = np.zeros(n_channels, dtype=np.int64)
        for ch_i in tqdm(range(n_channels), desc="  saturation_mask", leave=False):
            raw = inp.traces[ch_i]
            end = len(raw) - mr if mr > 0 else len(raw)
            signal = raw[ml:end]
            n = len(signal)
            i = 0
            while i <= n - min_run_i:
                ref_val = signal[i]
                run_len = 1
                for j in range(i + 1, min(i + min_run_i, n)):
                    if abs(signal[j] - ref_val) <= eps_range:
                        run_len += 1
                    else:
                        break
                if run_len < min_run_i:
                    i += 1
                    continue
                sat_start = i
                sat_end = i + min_run_i
                while sat_end < n and abs(signal[sat_end] - ref_val) <= eps_range:
                    sat_end += 1
                end_val = signal[sat_end - 1]
                while sat_end < n:
                    window_end = min(sat_end + lookahead_i, n)
                    chunk = signal[sat_end:window_end]
                    hits = np.where(np.abs(chunk - end_val) <= recovery_eps)[0]
                    if len(hits) == 0:
                        break
                    sat_end = sat_end + hits[-1] + 1
                    end_val = signal[sat_end - 1]
                if sat_start == 0:
                    lead_end[ch_i] = sat_end
                break

        lead_pct = lead_end / total_samples if total_samples > 0 else np.zeros(n_channels)
        traces = inp.traces
        channel_ids = inp.channel_ids
        locations = inp.locations

        if drop_saturated_pct is not None:
            threshold = float(drop_saturated_pct)
            keep_mask = lead_pct < threshold
            n_dropped = int(np.sum(~keep_mask))
            print(f"  saturation_mask: dropping {n_dropped} channel(s) "
                  f"with leading saturation >= {threshold*100:.1f}% of window")
            traces = traces[keep_mask]
            channel_ids = channel_ids[keep_mask]
            locations = locations[keep_mask]
            lead_end = lead_end[keep_mask]

        end_idx = traces.shape[1] - mr if mr > 0 else traces.shape[1]
        if sync_cut and len(traces) > 0:
            global_trim = int(np.max(lead_end))
            data = traces[:, ml:end_idx]
            if global_trim > 0:
                data = data[:, global_trim:]
                new_ws = (inp.window_samples[0] + global_trim, inp.window_samples[1])
                print(f"  saturation_mask: sync_cut trimmed {global_trim} samples "
                      f"({global_trim / inp.fs_hz * 1000:.1f} ms) from start")
            else:
                new_ws = inp.window_samples
        else:
            data = traces[:, ml:end_idx]
            new_ws = inp.window_samples

        return MEABank(
            traces=data, fs_hz=inp.fs_hz,
            channel_ids=channel_ids, locations=locations,
            window_samples=new_ws, margin_left=0, margin_right=0,
            label="saturation_mask",
        )

    # --- MEATrace branch: single-channel masking ---
    valid_modes = ("fill_nan", "fill_zeroes", "cut_window")
    if mode not in valid_modes:
        raise ValueError(f"saturation_mask mode must be one of {valid_modes}, got '{mode}'")
    if scope not in ("all", "leading"):
        raise ValueError(f"saturation_mask scope must be 'all' or 'leading', got '{scope}'")

    ml, mr = inp.margin_left, inp.margin_right
    if ml > 0 or mr > 0:
        end = len(inp.data) - mr if mr > 0 else len(inp.data)
        signal = inp.data[ml:end].copy()
    else:
        signal = inp.data.copy()

    n = len(signal)
    min_run = int(min_run)
    lookahead = int(lookahead)
    episodes = []
    i = 0

    while i <= n - min_run:
        ref_val = signal[i]
        run_len = 1
        for j in range(i + 1, min(i + min_run, n)):
            if abs(signal[j] - ref_val) <= eps_range:
                run_len += 1
            else:
                break
        if run_len < min_run:
            i += 1
            continue

        sat_start = i
        sat_end = i + min_run
        while sat_end < n and abs(signal[sat_end] - ref_val) <= eps_range:
            sat_end += 1

        end_val = signal[sat_end - 1]
        while sat_end < n:
            window_end = min(sat_end + lookahead, n)
            chunk = signal[sat_end:window_end]
            hits = np.where(np.abs(chunk - end_val) <= recovery_eps)[0]
            if len(hits) == 0:
                break
            sat_end = sat_end + hits[-1] + 1
            end_val = signal[sat_end - 1]

        raw_start = sat_start
        sat_start = max(sat_start - int(pre_samples), 0)
        episodes.append((sat_start, sat_end))
        if scope == "leading":
            if raw_start != 0:
                episodes.pop()
            break
        i = sat_end

    # --- Mode-specific masking ---
    ws = inp.window_samples

    if mode == "fill_nan":
        for s, e in episodes:
            signal[s:e] = np.nan
        masked_pct = np.sum(np.isnan(signal)) / n * 100
        print(f"  saturation_mask: {len(episodes)} episode(s), "
              f"{masked_pct:.1f}% of samples masked")
        return MEATrace(
            data=signal, fs_hz=inp.fs_hz, channel_idx=inp.channel_idx,
            window_samples=ws, margin_left=0, margin_right=0,
            label="saturation_mask",
        )

    elif mode == "fill_zeroes":
        for s, e in episodes:
            signal[s:e] = 0.0
        zeroed_pct = sum(e - s for s, e in episodes) / n * 100
        print(f"  saturation_mask: {len(episodes)} episode(s), "
              f"{zeroed_pct:.1f}% of samples zeroed")
        return MEATrace(
            data=signal, fs_hz=inp.fs_hz, channel_idx=inp.channel_idx,
            window_samples=ws, margin_left=0, margin_right=0,
            label="saturation_mask",
        )

    else:  # cut_window
        leading = [ep for ep in episodes if ep[0] == 0]
        trailing = [ep for ep in episodes if ep[1] >= n]
        middle = [ep for ep in episodes if ep[0] != 0 and ep[1] < n]

        if middle:
            print(f"  saturation_mask (cut_window): WARNING — {len(middle)} middle "
                  f"episode(s) detected, left unmasked")

        trim_left = max((ep[1] for ep in leading), default=0)
        trim_right = min((ep[0] for ep in trailing), default=n)

        if trim_left >= trim_right:
            print(f"  saturation_mask (cut_window): entire signal is saturated")
            return MEATrace(
                data=np.array([], dtype=signal.dtype),
                fs_hz=inp.fs_hz, channel_idx=inp.channel_idx,
                window_samples=(ws[0], ws[0]),
                margin_left=0, margin_right=0, label="saturation_mask",
            )

        signal = signal[trim_left:trim_right]
        new_ws = (ws[0] + trim_left, ws[0] + trim_right)

        print(f"  saturation_mask (cut_window): {len(episodes)} episode(s), "
              f"trimmed {trim_left} from start, {n - trim_right} from end, "
              f"{len(signal)} samples remain")
        return MEATrace(
            data=signal, fs_hz=inp.fs_hz, channel_idx=inp.channel_idx,
            window_samples=new_ws, margin_left=0, margin_right=0,
            label="saturation_mask",
        )


def op_amp_gain_correction(inp: MEATrace, ctx: PipelineContext, *,
                           broadband_range_hz, nperseg=4096,
                           noverlap=None, window='hann') -> MEATrace:
    """Normalize signal amplitude by dividing by sqrt of broadband power envelope."""
    ml, mr = inp.margin_left, inp.margin_right
    if ml > 0 or mr > 0:
        end = len(inp.data) - mr if mr > 0 else len(inp.data)
        signal = inp.data[ml:end].copy()
    else:
        signal = inp.data.copy()

    fs = inp.fs_hz
    n = len(signal)

    freqs, times_s, Sxx = _scipy_spectrogram(
        signal, fs=fs, window=window, nperseg=nperseg,
        noverlap=noverlap, scaling='density', mode='psd',
    )

    bb_low, bb_high = broadband_range_hz
    bb_mask = (freqs >= bb_low) & (freqs <= bb_high)
    bb_power = Sxx[bb_mask, :].mean(axis=0)
    bb_sqrt = np.sqrt(np.maximum(bb_power, 1e-10))

    stft_sample_indices = times_s * fs
    signal_indices = np.arange(n, dtype=np.float64)
    bb_sqrt_interp = np.interp(signal_indices, stft_sample_indices, bb_sqrt)

    corrected = signal / bb_sqrt_interp

    return MEATrace(
        data=corrected,
        fs_hz=fs,
        channel_idx=inp.channel_idx,
        window_samples=inp.window_samples,
        margin_left=0, margin_right=0,
        label="amp_gain_correction",
    )


def op_saturation_survey(inp: MEABank, ctx: PipelineContext, *,
                         min_run=20, eps_range=1.0,
                         lookahead=400, recovery_eps=5.0,
                         pre_samples=0, scope="all", plot_type="histogram") -> SaturationReport:
    if scope not in ("all", "leading"):
        raise ValueError(f"saturation_survey scope must be 'all' or 'leading', got '{scope}'")
    """Count saturated samples per MEA channel and return a per-channel report."""
    n_channels = inp.traces.shape[0]
    ml, mr = inp.margin_left, inp.margin_right
    total_samples = inp.traces.shape[1] - ml - (mr if mr > 0 else 0)
    samples_masked = np.zeros(n_channels, dtype=np.int64)
    min_run_i = int(min_run)
    lookahead_i = int(lookahead)

    for ch_i in tqdm(range(n_channels), desc="  saturation_survey", leave=False):
        raw = inp.traces[ch_i]
        end = len(raw) - mr if mr > 0 else len(raw)
        signal = raw[ml:end]
        n = len(signal)
        count = 0
        i = 0
        while i <= n - min_run_i:
            ref_val = signal[i]
            run_len = 1
            for j in range(i + 1, min(i + min_run_i, n)):
                if abs(signal[j] - ref_val) <= eps_range:
                    run_len += 1
                else:
                    break
            if run_len < min_run_i:
                i += 1
                continue
            sat_start = i
            sat_end = i + min_run_i
            while sat_end < n and abs(signal[sat_end] - ref_val) <= eps_range:
                sat_end += 1
            end_val = signal[sat_end - 1]
            while sat_end < n:
                window_end = min(sat_end + lookahead_i, n)
                chunk = signal[sat_end:window_end]
                hits = np.where(np.abs(chunk - end_val) <= recovery_eps)[0]
                if len(hits) == 0:
                    break
                sat_end = sat_end + hits[-1] + 1
                end_val = signal[sat_end - 1]
            raw_start = sat_start
            sat_start = max(raw_start - int(pre_samples), 0)
            if scope != "leading" or raw_start == 0:
                count += sat_end - sat_start
            i = sat_end
            if scope == "leading":
                break
        samples_masked[ch_i] = count

    if plot_type not in ("histogram", "scatter", "survival"):
        raise ValueError(f"plot_type must be 'histogram', 'scatter', or 'survival', got '{plot_type}'")

    return SaturationReport(
        channel_ids=inp.channel_ids,
        locations=inp.locations,
        samples_masked=samples_masked,
        total_samples=total_samples,
        window_samples=inp.window_samples,
        fs_hz=inp.fs_hz,
        plot_type=plot_type,
    )


# ════════════════════════════════════════════════════════════════════════════════
# MARGIN CALCULATORS
# ════════════════════════════════════════════════════════════════════════════════

def margin_butter_bandpass(params: Dict, ctx: PipelineContext) -> int:
    order = params.get('order', 10)
    low_hz = params.get('low_hz', 300)
    return int(3 * order * ctx.mea_fs_hz / low_hz)


def margin_notch_filter(params: Dict, ctx: PipelineContext) -> int:
    q = params.get('notch_q', 30.0)
    freq = params.get('notch_freq_hz', 60.0)
    return 3 * int(q * ctx.mea_fs_hz / freq)


# ════════════════════════════════════════════════════════════════════════════════
# REGISTRY FACTORY
# ════════════════════════════════════════════════════════════════════════════════
#
# ADDING A NEW OP: this function is where new ops get registered via
# registry.register_op(). It is one of six touch points documented in the
# "Adding a new operation" checklist in docs/operations.md. See also the
# comment above TYPE_TRANSITIONS for the full list.

def create_registry(
    plot_backend: str = "matplotlib",
) -> Tuple[OpRegistry, Dict[str, Callable]]:
    """Build and return a pre-configured (registry, source_loaders) pair.

    Plot handlers are dispatched based on ``plot_backend``:
        - "matplotlib"        : static PNG via matplotlib
        - "matplotlib_widget" : interactive ipympl widget
        - "pyqtgraph"         : standalone Qt desktop GUI
        - "pyqplot"           : publication PDF/PNG/SVG via the qplot binary
    """
    registry = OpRegistry()

    # Op handlers
    registry.register_op("butter_bandpass",     op_butter_bandpass)
    registry.register_op("notch_filter",         op_notch_filter)
    registry.register_op("saturation_mask",     op_saturation_mask)
    registry.register_op("sliding_rms",          op_sliding_rms)
    registry.register_op("constant_rms",         op_constant_rms)
    registry.register_op("spike_pca",            op_spike_pca)
    registry.register_op("spike_curate",         op_spike_curate)
    registry.register_op("baseline_correction",  op_baseline_correction)
    registry.register_op("rt_detect",             op_rt_detect)
    registry.register_op("sigmoid",              op_sigmoid)
    registry.register_op("rt_thresh",            op_rt_thresh)
    registry.register_op("gcamp_sim",            op_gcamp_sim)
    registry.register_op("x_corr",              op_x_corr)
    registry.register_op("spectrogram",          op_spectrogram)
    registry.register_op("freq_traces",          op_freq_traces)
    registry.register_op("amp_gain_correction",  op_amp_gain_correction)
    registry.register_op("saturation_survey",    op_saturation_survey)

    # Margin calculators
    registry.register_margin_calculator("butter_bandpass", margin_butter_bandpass)
    registry.register_margin_calculator("notch_filter",    margin_notch_filter)

    # Plot handlers (live in casi.plot_backends/, dispatched by chosen backend)
    from casi.plot_backends import register_for_backend
    register_for_backend(registry, plot_backend)

    source_loaders: Dict[str, Callable] = {
        "mea_trace": load_mea_trace,
        "ca_trace":  load_ca_trace,
        "rtsort":    load_rtsort,
    }

    return registry, source_loaders
