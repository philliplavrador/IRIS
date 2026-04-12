# Sessions and provenance

Every IRIS pipeline run lives in its own **session directory** under `outputs/`. The session directory bundles the analysis configuration, the generated plots, and a per-plot **sidecar JSON** with the full provenance metadata so any plot can be reproduced even if the parent session is lost.

## Session directory layout

```
outputs/
└── 2026-04-10_session_001_test-b/
    ├── manifest.json                        ← config snapshot, file fingerprints
    ├── transcript.md                        ← optional, written by the Claude agent
    ├── plot_001_mea_trace_861_spectrogram_0.png
    ├── plot_001_mea_trace_861_spectrogram_0.png.json
    ├── plot_002_overlay_ca_vs_sim_0.png
    └── plot_002_overlay_ca_vs_sim_0.png.json
```

The directory name has the form `YYYY-MM-DD_session_NNN[_label]`:
- `YYYY-MM-DD` is the calendar date the session was created
- `NNN` is a zero-padded counter that auto-increments to avoid clobbering same-day sessions
- `_label` is an optional human-readable suffix you set with `--label` (sanitized to safe characters, max 40 chars)

Create a new session via the CLI:

```bash
iris session new --label test-b
# outputs/2026-04-10_session_001_test-b
```

Or via the Claude Code agent — it creates one automatically after you confirm the config.

## `manifest.json` schema

Written once when the session is created (and updated by the CLI's `iris run` command). Snapshots the active configuration so you know exactly what produced the session even if `configs/` was edited afterward.

```json
{
  "iris_version": "0.1.0",
  "created_at": "2026-04-10T13:42:11",
  "session_dir": "outputs/2026-04-10_session_001_test-b",
  "paths": {
    "mea_h5": "/abs/path/MEA_B.raw.h5",
    "ca_traces_npz": "/abs/path/CA_traces_B.npz",
    "rt_model_path": "/abs/path/rtsort_model",
    "output_dir": "outputs/2026-04-10_session_001_test-b",
    "cache_dir": "/abs/path/cache"
  },
  "globals": {
    "plot_backend": "matplotlib",
    "show_ops_params": true,
    "save_plots": true,
    "memory_cache": true,
    "disk_cache": true
  },
  "ops": { /* full ops.yaml dict */ },
  "sources": {
    "mea_h5":        { "path": "...", "mtime": 1735000000.0, "size": 1749986307 },
    "ca_traces_npz": { "path": "...", "mtime": 1734999990.0, "size": 12345 },
    "rt_model_path": { "path": "...", "kind": "directory" }
  },
  "window_ms": null
}
```

View a session's manifest via the CLI:

```bash
iris session show 2026-04-10_session_001_test-b
```

## Sidecar `<plot>.json` schema

Written next to **every** saved plot. Contains the full DSL expression and all parameter values needed to reproduce the plot.

```json
{
  "iris_version": "0.1.0",
  "timestamp": "2026-04-10T13:42:23",
  "plot_file": "plot_001_mea_trace_861_butter_bandpass_spectrogram_0.png",
  "dsl": "mea_trace(861).butter_bandpass.spectrogram",
  "window_ms": [0.0, 297621.6],
  "ops": [
    {
      "name": "butter_bandpass",
      "params": {
        "low_hz": 350,
        "high_hz": 6000,
        "order": 10,
        "zero_phase": true
      }
    },
    {
      "name": "spectrogram",
      "params": {
        "nperseg": 16384,
        "noverlap": null,
        "window": "hann",
        "scaling": "density",
        "fmin": 0,
        "fmax": 360,
        "db_scale": true
      }
    }
  ],
  "sources": {
    "mea_h5": {
      "path": "/abs/path/MEA_B.raw.h5",
      "mtime": 1735000000.0,
      "size": 1749986307
    }
  },
  "plot_backend": "matplotlib"
}
```

The `ops` array contains every op in the chain with **fully-merged parameters** (defaults from `ops.yaml` + any inline DSL overrides). The `sources` block fingerprints the input files so you can detect if the data has changed since the plot was generated.

For function-ops like `x_corr` and `spike_curate`, the inner expression is captured under an `inner` key:

```json
{
  "name": "x_corr",
  "params": { "max_lag_ms": 500.0, "normalize": true, "adapt_circle_size": true },
  "inner": {
    "source": { "type": "mea_trace", "id": "all" },
    "ops": [
      { "name": "butter_bandpass", "params": { ... } },
      { "name": "sliding_rms", "params": { ... } },
      { "name": "gcamp_sim", "params": { ... } }
    ]
  }
}
```

## Reproducing a plot from its sidecar

```python
import json
from iris.engine import create_registry, run_pipeline

with open("outputs/.../plot_001_*.png.json") as f:
    sidecar = json.load(f)

registry, source_loaders = create_registry(plot_backend=sidecar["plot_backend"])
run_pipeline(
    paths_cfg={k: v["path"] for k, v in sidecar["sources"].items()} | {
        "output_dir": "outputs/reproduced",
        "cache_dir": "cache",
    },
    ops_cfg={op["name"]: op["params"] for op in sidecar["ops"]},
    pipeline_cfg=[
        f"window_ms[{sidecar['window_ms'][0]}, {sidecar['window_ms'][1]}]",
        sidecar["dsl"],
    ],
    registry=registry,
    source_loaders=source_loaders,
    globals_cfg={"save_plots": True},
)
```

## Listing past sessions

```bash
iris session list
# 2026-04-10_session_001_test-b                                  3 plot(s)
# 2026-04-09_session_002_qc                                      7 plot(s)
# 2026-04-09_session_001                                         1 plot(s)
```
