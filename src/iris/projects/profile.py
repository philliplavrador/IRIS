"""Dataset profiling (spec §7 Phase 6.3).

Reads a raw dataset version off disk, infers a column-level schema, writes
the resulting JSON onto ``dataset_versions.schema_json``, emits a
``dataset_profiled`` event, and proposes one draft ``memory_entries`` row
per column so the user can confirm/reject column semantics via the
curation ritual.

Format dispatch is extension-based with defensive fallbacks; optional
dependencies (``pandas``, ``pyarrow``, ``h5py``) are imported lazily so
this module stays importable on a minimal install.

Public API
----------
- :func:`profile_dataset`
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from iris.projects import datasets as datasets_mod
from iris.projects import events as events_mod
from iris.projects import memory_entries as memory_mod

__all__ = ["profile_dataset"]

_MAX_SAMPLES: int = 5
_CSV_SNIFF_ROWS: int = 50_000


# -- schema_json column guard ----------------------------------------------


def _ensure_schema_json_column(conn: sqlite3.Connection) -> None:
    """Idempotently ensure ``dataset_versions.schema_json`` exists.

    Modern ``schema.sql`` already declares the column. This guard keeps the
    module working against older DBs migrated forward task-by-task.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(dataset_versions)")}
    if "schema_json" not in cols:
        conn.execute("ALTER TABLE dataset_versions ADD COLUMN schema_json TEXT")


# -- per-format schema extractors ------------------------------------------


def _require(mod_name: str) -> Any:
    """Import ``mod_name`` or raise a clear ``RuntimeError`` on failure."""
    try:
        return __import__(mod_name)
    except ImportError as exc:  # pragma: no cover - trivial
        raise RuntimeError(f"install {mod_name}") from exc


def _profile_csv(path: Path) -> tuple[list[dict[str, Any]], int]:
    pd = _require("pandas")
    df = pd.read_csv(path, nrows=_CSV_SNIFF_ROWS)
    cols = _columns_from_dataframe(df)
    # Row count: stream the file to avoid loading everything into memory.
    with path.open("r", encoding="utf-8", errors="replace") as f:
        n_rows = max(sum(1 for _ in f) - 1, 0)  # subtract header
    return cols, n_rows


def _profile_parquet(path: Path) -> tuple[list[dict[str, Any]], int]:
    # Prefer pyarrow for row_count without materializing; fall back to pandas.
    try:
        pa = __import__("pyarrow.parquet", fromlist=["parquet"])
    except ImportError:
        pa = None
    if pa is not None:
        pf = pa.ParquetFile(str(path))
        n_rows = int(pf.metadata.num_rows) if pf.metadata is not None else 0
        pd = _require("pandas")
        df = pd.read_parquet(path)
        return _columns_from_dataframe(df), n_rows
    pd = _require("pandas")
    df = pd.read_parquet(path)
    return _columns_from_dataframe(df), int(len(df))


def _profile_hdf5(path: Path) -> tuple[list[dict[str, Any]], int]:
    h5py = _require("h5py")
    cols: list[dict[str, Any]] = []
    n_rows = 0
    with h5py.File(path, "r") as f:

        def visit(name: str, obj: Any) -> None:
            nonlocal n_rows
            if isinstance(obj, h5py.Dataset):
                shape = list(obj.shape)
                entry: dict[str, Any] = {
                    "name": name,
                    "dtype": str(obj.dtype),
                    "non_null_count": int(shape[0]) if shape else 1,
                    "n_unique": None,
                    "samples": [],
                }
                if shape:
                    n_rows = max(n_rows, int(shape[0]))
                    try:
                        head = obj[: min(_MAX_SAMPLES, shape[0])]
                        entry["samples"] = [_jsonable(v) for v in list(head)]
                    except Exception:  # noqa: BLE001 - HDF5 edge cases are varied
                        pass
                cols.append(entry)

        f.visititems(visit)
    return cols, n_rows


def _profile_unknown(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Heuristic fallback: treat file as opaque bytes with a size column."""
    size = path.stat().st_size
    return (
        [
            {
                "name": "_bytes",
                "dtype": "binary",
                "non_null_count": size,
                "n_unique": None,
                "samples": [],
            }
        ],
        0,
    )


# -- DataFrame → column dicts ----------------------------------------------


def _jsonable(v: Any) -> Any:
    """Coerce a value into something ``json.dumps`` tolerates."""
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)


def _columns_from_dataframe(df: Any) -> list[dict[str, Any]]:
    """Build per-column records from a pandas DataFrame."""
    out: list[dict[str, Any]] = []
    for name in df.columns:
        col = df[name]
        dtype = str(col.dtype)
        non_null = int(col.notna().sum())
        try:
            n_unique = int(col.nunique(dropna=True))
        except (TypeError, ValueError):
            n_unique = None
        samples: list[Any] = []
        try:
            samples = [_jsonable(v) for v in col.dropna().head(_MAX_SAMPLES).tolist()]
        except Exception:  # noqa: BLE001 - pandas raises wide types here
            samples = []
        entry: dict[str, Any] = {
            "name": str(name),
            "dtype": dtype,
            "non_null_count": non_null,
            "n_unique": n_unique,
            "samples": samples,
        }
        # Numeric min/max are cheap and very useful downstream.
        if getattr(col.dtype, "kind", "") in "iuf":
            try:
                mn = col.min()
                mx = col.max()
                entry["min"] = _jsonable(None if _is_nan(mn) else float(mn))
                entry["max"] = _jsonable(None if _is_nan(mx) else float(mx))
            except (TypeError, ValueError):
                pass
        out.append(entry)
    return out


def _is_nan(v: Any) -> bool:
    try:
        return v != v  # noqa: PLR0124 - NaN self-check is idiomatic
    except Exception:  # noqa: BLE001 - exotic comparators
        return False


# -- dispatch --------------------------------------------------------------


def _dispatch(path: Path) -> tuple[list[dict[str, Any]], int]:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return _profile_csv(path)
    if suffix in {".parquet", ".pq"}:
        return _profile_parquet(path)
    if suffix in {".h5", ".hdf5"}:
        return _profile_hdf5(path)
    return _profile_unknown(path)


# -- public API ------------------------------------------------------------


def profile_dataset(
    conn: sqlite3.Connection,
    project_path: Path,
    *,
    dataset_id: str,
    version_id: str,
) -> dict[str, Any]:
    """Profile the raw file backing ``version_id`` and record the schema.

    Resolves the file via :func:`datasets.get_version`, infers a per-column
    schema, persists it on ``dataset_versions.schema_json``, emits a
    ``dataset_profiled`` event, and proposes one draft
    ``memory_type='preference'`` per inferred column (so the user can
    confirm/reject column semantics via the curation ritual).

    Returns
    -------
    dict
        ``{"columns": [...], "n_rows": int, "schema_json": str}``.

    Raises
    ------
    LookupError
        If ``version_id`` does not resolve to a dataset version.
    FileNotFoundError
        If the raw file for the version is missing on disk.
    RuntimeError
        If a required optional dep (``pandas``, ``pyarrow``, ``h5py``) is
        missing for the detected format.
    """
    _ensure_schema_json_column(conn)

    version = datasets_mod.get_version(conn, version_id)
    if version is None or version["dataset_id"] != dataset_id:
        raise LookupError(f"dataset version {version_id!r} not found for dataset {dataset_id!r}")

    raw_path = Path(project_path) / version["storage_path"]
    if not raw_path.is_file():
        raise FileNotFoundError(f"raw dataset file missing: {raw_path}")

    columns, n_rows = _dispatch(raw_path)
    schema_payload: dict[str, Any] = {
        "columns": columns,
        "n_rows": n_rows,
        "suffix": raw_path.suffix.lower(),
    }
    schema_json = json.dumps(schema_payload, sort_keys=True)

    project_id = _resolve_project_id(conn)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE dataset_versions SET schema_json = ?, row_count = ? "
            "WHERE dataset_version_id = ?",
            (schema_json, n_rows, version_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    events_mod.append_event(
        conn,
        project_id=project_id,
        type=events_mod.EVT_DATASET_PROFILED,
        payload={
            "dataset_id": dataset_id,
            "dataset_version_id": version_id,
            "n_rows": n_rows,
            "n_columns": len(columns),
        },
    )

    # One draft memory_entry per column, for the user to confirm/reject.
    for col in columns:
        memory_mod.propose(
            conn,
            project_id=project_id,
            scope="dataset",
            memory_type="preference",
            text=f"column {col.get('name')}: {col.get('dtype')}",
            dataset_id=dataset_id,
            importance=3,
        )

    return {"columns": columns, "n_rows": n_rows, "schema_json": schema_json}


def _resolve_project_id(conn: sqlite3.Connection) -> str:
    """Return the single project_id stored in this per-project DB."""
    row = conn.execute("SELECT project_id FROM projects ORDER BY created_at ASC LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("no project row found; init_schema must run first")
    return row[0]
