# Data formats expected by CASI

CASI's source loaders read three kinds of input data. This page documents what the loader expects in each file so you can prepare your own recordings without trial-and-error.

## MEA recordings — `mea_h5`

**Loader:** `casi.engine.load_mea_recording` → `spikeinterface.extractors.MaxwellRecordingExtractor`

**Format:** Maxwell Biosystems `.raw.h5` files produced by the MaxOne / MaxTwo recording systems.

**Sample rate:** 20 kHz (default; override via `mea_fs_hz` in `run_pipeline`).

**Channel addressing:** the DSL uses **Maxwell channel IDs**, not row indices. These are non-sequential integer strings (`'0', '2', '4', ...`) — channel 861 is row 478 in the recording, etc. CASI maps channel IDs to row indices automatically; you only need to specify channel IDs in DSL strings.

**Metadata extracted:**
- `recording.get_channel_ids()` — channel ID strings
- `recording.get_channel_locations()` — `(n_channels, 2)` electrode XY coordinates (µm)
- `recording.get_num_channels()`
- `recording.get_num_samples()`

**Path key:** `paths.mea_h5` in `configs/paths.yaml`.

## Calcium imaging traces — `ca_traces_npz`

**Loader:** `casi.engine.load_ca_trace`

**Format:** numpy `.npz` archive with the following keys:

| Key | Shape | Description |
|---|---|---|
| `traces` | `(n_rois, n_frames)` | ΔF/F₀ (or raw fluorescence) per ROI per frame |
| `frame_times` | `(n_frames,)` | Frame timestamps in **MEA samples** (not ms or seconds) |

The frame times must be in MEA-sample units so the loader can interpolate calcium frames onto the MEA grid. If your acquisition produces calcium frame times in seconds or ms, multiply by `mea_fs_hz` before saving the `.npz`.

**Sample rate:** typically 50 Hz (widefield calcium imaging).

**Path key:** `paths.ca_traces_npz` in `configs/paths.yaml`.

## RTSort precomputed outputs — `rt_model_outputs_npy`

**Loader:** `casi.engine.load_rtsort`

**Format:** numpy `.npy` array of shape `(n_channels, n_samples_trimmed)`. Each row is the precomputed sigmoid output of the RT-Sort CNN for one channel. The array is already trimmed by the model's front and end buffers.

**Sample rate:** 20 kHz (must match `mea_fs_hz`).

**Channel addressing:** rows are indexed by **channel ID** via the same mapping as `mea_trace`. The loader uses `_load_mea_recording` + `_get_mea_metadata` to translate the requested channel ID into the correct row.

**Use:** the `rtsort(N)` source loads precomputed outputs only. To run RT-Sort inference live on raw voltage, use `mea_trace(N).rt_detect.sigmoid` instead — this requires `braindance` and the model weights.

**Path key:** `paths.rt_model_outputs_npy` in `configs/paths.yaml`.

## RTSort model weights — `rt_model_path`

**Loader:** `casi.engine._load_rtsort_model`

**Format:** a directory containing the two files:
- `init_dict.json` — model architecture / hyperparameters
- `state_dict.pt` — PyTorch model weights

**Use:** required only by the `rt_detect` op. The model is loaded once and cached at module level. Inference is forced to CPU + float32 to match braindance's compile/inference path.

**Path key:** `paths.rt_model_path` in `configs/paths.yaml`.

## Where the example data lives

The legacy snapshot at `legacy/data/alignment-data/Test-B/` contains:

```
legacy/data/alignment-data/Test-B/
├── MEA_B.raw.h5                            (1.6 GB Maxwell recording)
├── CA_traces_B.npz                         (calcium ROI traces)
└── sequences/
    └── model_outputs.npy                   (precomputed RT-Sort outputs)
```

And the model weights:

```
legacy/models/rtsort_model/
├── init_dict.json
└── state_dict.pt
```

These are referenced by the default `configs/paths.yaml` so you can verify the install with `casi config validate` immediately after cloning.

## Adding your own recordings

1. Drop your Maxwell `.raw.h5` somewhere accessible
2. Generate a `.npz` with `traces` + `frame_times` from your calcium imaging pipeline (frame times in MEA-sample units)
3. Run `casi config edit paths mea_h5 /your/recording.h5`
4. Run `casi config edit paths ca_traces_npz /your/calcium.npz`
5. Run `casi config validate` to confirm the loader sees them
6. Run any DSL expression you want — the cache key includes file mtimes so you'll never accidentally hit a stale result from a different recording
