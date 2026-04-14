"""Domain-agnostic data profiler.

Extracts *structural* facts from an uploaded file — shape, dtypes, null
counts, value ranges, summary stats, unique-value counts for categoricals,
inferred datetime columns, file-level metadata. Does NOT guess what the
data means. Semantic annotations come from the user.

Dispatch is by file extension (and magic bytes where available). Unknown
types yield a minimal record (size, mtime) rather than raising.

Results are returned as a dict AND staged into
``knowledge.sqlite::data_profile_fields`` with ``confirmed_by_user=False``.
The webapp displays the profile for user confirmation; approved rows are
flipped to ``confirmed_by_user=True`` via the propose/commit flow.

See docs/iris-behavior.md §1 and §12 (new op: ``profile_data``).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import knowledge as _knowledge


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- per-format profilers ---------------------------------------------------


def _profile_csv(path: Path, max_rows: int = 50000) -> dict:
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        return _profile_text_fallback(path, reason="pandas not installed")

    try:
        df = pd.read_csv(path, nrows=max_rows)
    except Exception as e:
        return {"kind": "csv", "error": str(e)}
    return _profile_dataframe(df, kind="csv", sampled=True, max_rows=max_rows)


def _profile_parquet(path: Path) -> dict:
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        return {"kind": "parquet", "error": "pandas not installed"}
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        return {"kind": "parquet", "error": str(e)}
    return _profile_dataframe(df, kind="parquet", sampled=False)


def _profile_json(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as e:
        return {"kind": "json", "error": str(e)}
    kind = type(data).__name__
    info: dict = {"kind": "json", "top_type": kind}
    if isinstance(data, list):
        info["length"] = len(data)
        if data and isinstance(data[0], dict):
            info["keys"] = sorted({k for d in data[:100] if isinstance(d, dict) for k in d})
    elif isinstance(data, dict):
        info["keys"] = sorted(data.keys())
    return info


def _profile_h5(path: Path) -> dict:
    try:
        import h5py  # type: ignore
    except ImportError:
        return {"kind": "h5", "error": "h5py not installed"}
    try:
        with h5py.File(path, "r") as f:
            datasets = []

            def visit(name, obj):
                if isinstance(obj, h5py.Dataset):
                    datasets.append(
                        {
                            "name": name,
                            "shape": list(obj.shape),
                            "dtype": str(obj.dtype),
                        }
                    )

            f.visititems(visit)
            return {"kind": "h5", "datasets": datasets}
    except Exception as e:
        return {"kind": "h5", "error": str(e)}


def _profile_netcdf(path: Path) -> dict:
    try:
        import netCDF4  # type: ignore
    except ImportError:
        return {"kind": "netcdf", "error": "netCDF4 not installed"}
    try:
        with netCDF4.Dataset(path, "r") as ds:  # type: ignore
            return {
                "kind": "netcdf",
                "dimensions": {k: len(v) for k, v in ds.dimensions.items()},
                "variables": {
                    k: {"shape": list(v.shape), "dtype": str(v.dtype)}
                    for k, v in ds.variables.items()
                },
            }
    except Exception as e:
        return {"kind": "netcdf", "error": str(e)}


def _profile_numpy(path: Path) -> dict:
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return {"kind": "numpy", "error": "numpy not installed"}
    try:
        if path.suffix == ".npz":
            z = np.load(path, allow_pickle=False)
            return {
                "kind": "npz",
                "arrays": {k: {"shape": list(z[k].shape), "dtype": str(z[k].dtype)} for k in z.files},
            }
        a = np.load(path, allow_pickle=False)
        return {"kind": "npy", "shape": list(a.shape), "dtype": str(a.dtype)}
    except Exception as e:
        return {"kind": "numpy", "error": str(e)}


def _profile_sqlite(path: Path) -> dict:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ]
            info: dict = {"kind": "sqlite", "tables": {}}
            for t in tables:
                cols = [
                    {"name": r[1], "type": r[2]}
                    for r in conn.execute(f"PRAGMA table_info({t})")
                ]
                try:
                    n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except sqlite3.Error:
                    n = None
                info["tables"][t] = {"columns": cols, "rows": n}
            return info
    except sqlite3.Error as e:
        return {"kind": "sqlite", "error": str(e)}


def _profile_text_fallback(path: Path, reason: str = "") -> dict:
    try:
        sample = path.read_text(encoding="utf-8", errors="replace")[:2048]
    except OSError as e:
        return {"kind": "text", "error": str(e)}
    return {
        "kind": "text",
        "note": reason or "fallback profile",
        "sample_head": sample,
    }


def _profile_dataframe(df, *, kind: str, sampled: bool, max_rows: int = 0) -> dict:
    cols: list[dict] = []
    for name in df.columns:
        col = df[name]
        dtype = str(col.dtype)
        nulls = int(col.isna().sum())
        info: dict[str, Any] = {"name": str(name), "dtype": dtype, "nulls": nulls}
        try:
            if str(col.dtype) in ("object", "category", "string"):
                nunique = int(col.nunique(dropna=True))
                info["unique"] = nunique
                if nunique <= 20:
                    info["values"] = sorted(map(str, col.dropna().unique().tolist()))
            elif col.dtype.kind in "iuf":
                info["min"] = _safe_num(col.min())
                info["max"] = _safe_num(col.max())
                info["mean"] = _safe_num(col.mean())
                info["std"] = _safe_num(col.std())
            elif "datetime" in dtype:
                info["min"] = str(col.min())
                info["max"] = str(col.max())
        except Exception:
            pass
        cols.append(info)
    return {
        "kind": kind,
        "shape": list(df.shape),
        "sampled": sampled,
        "max_rows": max_rows if sampled else None,
        "columns": cols,
    }


def _safe_num(v) -> Optional[float]:
    try:
        import math

        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# -- dispatch ---------------------------------------------------------------


_DISPATCH = {
    ".csv": _profile_csv,
    ".tsv": _profile_csv,
    ".parquet": _profile_parquet,
    ".pq": _profile_parquet,
    ".json": _profile_json,
    ".jsonl": _profile_json,
    ".h5": _profile_h5,
    ".hdf5": _profile_h5,
    ".nc": _profile_netcdf,
    ".netcdf": _profile_netcdf,
    ".npy": _profile_numpy,
    ".npz": _profile_numpy,
    ".sqlite": _profile_sqlite,
    ".db": _profile_sqlite,
}


def profile_data(file_path: str | Path, project_path: Optional[Path] = None) -> dict:
    """Profile ``file_path`` and optionally stage rows in ``knowledge.sqlite``.

    Returns a dict like::

        {"path": ..., "bytes": ..., "mtime": ..., "kind": ..., "columns": [...]}

    When ``project_path`` is given, each column (or dataset) becomes a row
    in ``data_profile_fields`` with ``confirmed_by_user=False`` and a
    ``field_path`` of ``"<filename>::<column_or_dataset>"``. The webapp's
    upload flow calls this with ``project_path`` set.

    Domain-agnostic: NEVER interprets column semantics. The profiler only
    extracts what the format itself exposes.
    """
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(str(p))

    stat = p.stat()
    result: dict = {
        "path": str(p),
        "name": p.name,
        "bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "suffix": p.suffix.lower(),
    }

    profiler = _DISPATCH.get(p.suffix.lower())
    if profiler is None:
        result.update(_profile_text_fallback(p, reason="unknown format"))
    else:
        result.update(profiler(p))

    if project_path is not None:
        _stage_rows(project_path, p.name, result)

    return result


def _stage_rows(project_path: Path, filename: str, profile: dict) -> None:
    """Insert (unconfirmed) profile rows into ``data_profile_fields``."""
    now = _now()
    rows: list[tuple[str, str]] = []
    kind = profile.get("kind")

    def add(field: str, annotation: str) -> None:
        rows.append((f"{filename}::{field}", annotation))

    # File-level row summarizing the whole profile (useful for search).
    add(
        "_file",
        f"kind={kind} bytes={profile.get('bytes')} shape={profile.get('shape')}",
    )

    if kind in ("csv", "parquet"):
        for c in profile.get("columns", []):
            parts = [f"dtype={c.get('dtype')}"]
            for k in ("min", "max", "mean", "unique", "nulls"):
                if c.get(k) is not None:
                    parts.append(f"{k}={c[k]}")
            add(str(c.get("name", "?")), " ".join(parts))
    elif kind == "h5":
        for ds in profile.get("datasets", []):
            add(ds["name"], f"shape={ds['shape']} dtype={ds['dtype']}")
    elif kind == "npz":
        for n, a in (profile.get("arrays") or {}).items():
            add(n, f"shape={a['shape']} dtype={a['dtype']}")
    elif kind == "npy":
        add(
            "_array",
            f"shape={profile.get('shape')} dtype={profile.get('dtype')}",
        )
    elif kind == "netcdf":
        for n, v in (profile.get("variables") or {}).items():
            add(n, f"shape={v['shape']} dtype={v['dtype']}")
    elif kind == "sqlite":
        for tname, t in (profile.get("tables") or {}).items():
            add(tname, f"rows={t.get('rows')} columns={len(t.get('columns') or [])}")
    elif kind == "json":
        for key in profile.get("keys", []) or []:
            add(str(key), f"top_type={profile.get('top_type')}")

    with _knowledge.open_knowledge(project_path) as conn:
        for field_path, annotation in rows:
            conn.execute(
                """INSERT INTO data_profile_fields(field_path, annotation,
                     confirmed_by_user, session, created_at)
                   VALUES (?, ?, 0, NULL, ?)
                   ON CONFLICT(field_path) DO UPDATE SET
                     annotation = excluded.annotation
                   WHERE confirmed_by_user = 0""",
                (field_path, annotation, now),
            )
