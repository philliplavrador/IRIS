"""Two-tier pipeline cache: in-memory prefix reuse + optional disk cache."""
from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from iris.engine.ast import ExprNode, OpNode, SourceNode


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
