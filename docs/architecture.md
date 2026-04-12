# MEA Electrophysiology Pipeline — Project Overview

## 1. Introduction

### What This Is

This project is a config-driven pipeline for processing extracellular electrophysiology recordings from Maxwell microelectrode arrays (MEAs), alongside GCaMP calcium imaging data. Instead of writing ad-hoc analysis scripts, the user defines processing chains as short strings — a domain-specific language (DSL) — and the engine handles execution, caching, type checking, and plotting automatically.

A typical pipeline string looks like this:

```
mea_trace(861).saturation_mask.notch_filter.butter_bandpass.rt_detect.sigmoid
```

This loads channel 861 from the MEA recording, masks saturated regions, removes power-line noise, bandpass-filters to the spike band, runs a CNN spike detector, and converts logits to probabilities — all from a single line of config.

### Why It Exists

MEA recordings generate large, multi-channel voltage traces (20 kHz sampling across hundreds of electrodes). Processing these recordings involves many sequential steps — filtering, artifact removal, spike detection, calcium trace alignment — each with tunable parameters. The goals of this pipeline are:

- **Reproducibility**: every parameter is stored in a config dict; re-running the same config produces the same result.
- **Composability**: operations are independent building blocks that chain together via the DSL. Swapping the order or adding a step is a one-line edit.
- **Speed**: a two-tier cache (in-memory + disk) means re-runs skip already-computed steps. Changing a parameter only recomputes from that point forward.
- **Visualization**: every operation auto-generates a plot of its output, with operation parameters embedded in the figure margin for traceability.

### Project Structure

| File | Purpose |
|------|---------|
| `engine.py` | All domain logic: data types, DSL parser, pipeline executor, cache, operation handlers, source loaders, plot handlers, registry factory. ~2400 lines. |
| `pipeline.ipynb` | Config and run only. Defines file paths, operation parameters, and DSL pipeline strings. No domain logic. Local use (Windows). |
| `colab_pipeline.ipynb` | Google Colab version of `pipeline.ipynb`. Same config, different paths and matplotlib backend. |
| `ops.md` | Mathematical reference for every operation, with LaTeX formulas and source links into `engine.py`. |
| `requirements.txt` | Python dependencies. |

All domain logic lives in `engine.py`. The notebooks contain zero signal processing code — they are purely configuration.

---

## 2. Architecture

### High-Level Flow

```
User writes config dicts     User writes DSL strings        One cell runs everything
   (ops_cfg, paths_cfg)    →   (pipeline_cfg list)       →   run_pipeline() → plots
```

The pipeline takes three inputs:
1. **`paths_cfg`** — where the data files are
2. **`ops_cfg`** — parameters for each operation (filter cutoffs, thresholds, etc.)
3. **`pipeline_cfg`** — list of DSL strings describing what to compute

And produces: auto-generated plots for every result, plus in-memory result objects for further analysis.

### Under the Hood

```
DSL strings
    ↓
DSLParser  →  Abstract Syntax Tree (source nodes + operation nodes)
    ↓
PipelineExecutor  →  For each expression:
    ├── Check cache (longest prefix match)
    ├── Load source data (with margin padding for filters)
    ├── Apply operations in sequence (type-checked)
    ├── Cache intermediate results
    └── Auto-plot the final result
```

**Key components:**

- **DSLParser** — converts strings like `"mea_trace(861).notch_filter"` into an AST of source nodes and operation nodes. Handles parenthesized arguments, nested expressions (for cross-correlation), overlay groups, and window directives.

- **OpRegistry** — central registry mapping operation names to their handler functions, margin calculators, and plot handlers. The `TYPE_TRANSITIONS` table defines which input types each operation accepts and what it produces.

- **PipelineExecutor** — walks the AST, dispatching each operation through the registry. Handles bank vectorization (applying single-channel ops across all channels of an MEABank automatically), function-ops with inner expressions (like `x_corr`), and margin management.

- **PipelineCache** — two-tier caching system:
  - *Memory cache*: reuses previously computed prefixes within a single run. If the pipeline includes both `mea_trace(861).notch_filter` and `mea_trace(861).notch_filter.butter_bandpass`, the notch-filtered result is computed once.
  - *Disk cache*: persists results as pickle files across runs. Cache keys include the analysis window, all operation parameters, file paths, and file modification times — so the cache automatically invalidates when source data or parameters change.

- **Margin system** — IIR filters (bandpass, notch) produce transient artifacts at signal edges. The margin system solves this by loading extra samples on each side of the requested window, running the filter on the extended data, then trimming the margins. Each filter declares how many margin samples it needs (based on filter order and cutoff frequency).

### Type System

Every operation declares its input → output type mapping. The executor validates these at each step:

| Type | Represents |
|------|------------|
| `MEATrace` | Single-channel voltage trace (data, sample rate, channel ID, window, margins) |
| `MEABank` | Multi-channel voltage traces (all channels at once) |
| `CATrace` | Calcium imaging trace (single ROI, interpolated to MEA sample rate) |
| `RTTrace` | RTSort CNN output (single-channel logits or probabilities) |
| `RTBank` | Multi-channel RTSort outputs |
| `SpikeTrain` | Detected spike times + threshold curve + source signal |
| `SimCalcium` | Simulated GCaMP fluorescence from a spike train |
| `SimCalciumBank` | Simulated fluorescence for all channels |
| `CorrelationResult` | Cross-correlation scores + best-matching electrode |
| `Spectrogram` | Time-frequency power spectral density |
| `FreqPowerTraces` | Power vs time at specific frequencies |

### Type Transitions

Each operation declares which input types it accepts and what it produces:

| Operation | Input → Output |
|-----------|---------------|
| `butter_bandpass` | MEATrace → MEATrace, MEABank → MEABank |
| `notch_filter` | MEATrace → MEATrace, MEABank → MEABank |
| `saturation_mask` | MEATrace → MEATrace, MEABank → MEABank |
| `amp_gain_correction` | MEATrace → MEATrace, MEABank → MEABank |
| `constant_rms` | MEATrace → SpikeTrain |
| `sliding_rms` | MEATrace → SpikeTrain |
| `baseline_correction` | CATrace → CATrace |
| `rt_detect` | MEATrace → RTTrace |
| `sigmoid` | RTTrace → RTTrace, RTBank → RTBank |
| `rt_thresh` | RTTrace → SpikeTrain |
| `gcamp_sim` | SpikeTrain → SimCalcium |
| `x_corr` | CATrace × SimCalciumBank → CorrelationResult |
| `spectrogram` | MEATrace → Spectrogram |
| `freq_traces` | MEATrace → FreqPowerTraces |

If you chain an operation onto an incompatible type (e.g., `ca_trace(11).rt_detect`), the executor raises a clear type error before any computation.

### Bank Vectorization

When an operation is registered for both `MEATrace → MEATrace` and `MEABank → MEABank`, the executor automatically handles the bank case by applying the single-channel handler to each channel with a progress bar. Operation code only needs to be written once for the single-channel case.

---

## 3. The DSL

### Basics

A pipeline string is a dot-separated chain starting with a data source:

```
mea_trace(861).notch_filter.butter_bandpass
```

- **Source**: `mea_trace(861)` loads channel 861 from the MEA recording
- **Operations**: each dot-separated name applies an operation to the previous result
- **Left to right**: data flows through the chain sequentially

### Sources

| Source | Description |
|--------|-------------|
| `mea_trace(N)` | Load MEA channel N (e.g., 861). Returns `MEATrace`. |
| `mea_trace(all)` | Load all MEA channels. Returns `MEABank`. |
| `ca_trace(N)` | Load calcium trace N. Returns `CATrace`. |
| `rtsort(N)` | Load precomputed RTSort output for channel N. Returns `RTTrace`. |

### Windows

The first item in a pipeline section sets the time window:

```python
pipe = [
    "window_ms[14487.05, 44352.95]",   # analyze this time range
    "mea_trace(861).notch_filter",       # this runs within that window
]
```

Use `"window_ms[full]"` for the entire recording.

### Overlays

Wrap multiple expressions in a list to overlay them on one plot:

```python
["mea_trace(861)", "mea_trace(861).butter_bandpass"]
```

This plots raw and filtered signals together, normalized to [0, 1] for visual comparison.

### Parameter Overrides

Operation parameters come from `ops_cfg` by default, but can be overridden inline:

```
mea_trace(861).butter_bandpass(low_hz=500, high_hz=3000)
```

### Function-Ops

Some operations take a second input via a nested expression:

```
ca_trace(11).baseline_correction.x_corr(mea_trace(all).butter_bandpass.sliding_rms.gcamp_sim)
```

This cross-correlates the calcium trace against simulated GCaMP signals from all MEA channels.

---

## 4. Operations Reference

### 4.1 `saturation_mask`

**What it does:** Detects ADC clipping and flatline artifacts in raw MEA recordings and removes them.

Maxwell MEA recordings can contain episodes where the signal "rails" — the voltage hits the ADC ceiling or floor and stays flat. These artifacts corrupt downstream analysis (filters ring, RMS estimates are biased, spike detectors fire falsely). `saturation_mask` identifies these episodes and handles them.

**Types:** `MEATrace → MEATrace`, `MEABank → MEABank`

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_run` | 20 | Minimum consecutive flat samples to trigger detection |
| `eps_range` | 1.0 µV | Tolerance for "flat" — samples within this range of a reference value |
| `lookahead` | 400 | Samples to scan ahead when checking if the signal has truly recovered |
| `recovery_eps` | 5.0 µV | Tolerance for the lookahead recovery check |
| `pre_samples` | 0 | Extra samples to mask before each detected episode |
| `mode` | `"fill_nan"` | How to handle detected episodes |

**Modes:**
- `"fill_nan"` — replace saturated samples with NaN (preserves time axis)
- `"fill_zeroes"` — replace with zeros (avoids NaN propagation through downstream filters)
- `"cut_window"` — trim leading/trailing saturation by adjusting the data window; middle episodes are left unmasked with a warning

**Algorithm:** Walks the signal sample-by-sample. When it finds `min_run` consecutive samples within `eps_range` µV of a reference value, it marks the start of a saturation episode. It extends the episode forward until the signal deviates, then uses a lookahead window to confirm the signal has truly recovered (catching brief recovery transients). Detected episodes are then handled according to `mode`.

### 4.2 `notch_filter`

**What it does:** Removes power-line interference (60 Hz) and its harmonics from MEA recordings.

Electrical recordings inevitably pick up 60 Hz noise from the power grid, plus harmonics at 120, 180, 240, and 300 Hz. The notch filter places narrow rejection bands at each of these frequencies, suppressing the interference while preserving the neural signal.

**Types:** `MEATrace → MEATrace`, `MEABank → MEABank`

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `notch_freq_hz` | 60.0 | Fundamental frequency to reject |
| `notch_q` | 30.0 | Quality factor (higher = narrower rejection band) |
| `harmonics` | [1, 2, 3, 4, 5] | Which harmonics to filter (1 = fundamental) |

**Method:** For each harmonic, designs a 2nd-order IIR notch filter using `scipy.signal.iirnotch`, converts to second-order sections (SOS) for numerical stability, and applies zero-phase filtering via `sosfiltfilt`. Filters are applied sequentially — one per harmonic.

### 4.3 `butter_bandpass`

**What it does:** Passes frequencies within a specified band and attenuates everything outside it.

For spike detection, the relevant neural signal lies roughly in the 350–6000 Hz range. The bandpass filter removes slow drifts (low frequencies) and high-frequency noise, isolating the spike waveforms.

**Types:** `MEATrace → MEATrace`, `MEABank → MEABank`

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `low_hz` | — | Lower cutoff frequency |
| `high_hz` | — | Upper cutoff frequency |
| `order` | — | Filter order (higher = steeper rolloff) |
| `zero_phase` | True | Forward-backward filtering (no phase distortion) |

**Method:** Designs a Butterworth IIR filter with `scipy.signal.butter`. When `zero_phase=True`, applies forward-backward via `filtfilt` (effectively doubling the filter order with zero phase shift). Margins are trimmed after filtering to remove edge transients.

### 4.4 `amp_gain_correction`

**What it does:** Normalizes signal amplitude over time to compensate for slow gain changes.

MEA recordings can exhibit gradual amplitude drift due to electrode impedance changes, tissue settling, or other factors. This makes spike detection unreliable — the same neuron produces larger or smaller spikes at different times. `amp_gain_correction` divides the signal by its broadband power envelope, equalizing amplitude across the recording.

**Types:** `MEATrace → MEATrace`, `MEABank → MEABank`

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `broadband_range_hz` | — (required) | Frequency range [low, high] for broadband power |
| `nperseg` | 4096 | STFT window size in samples |
| `noverlap` | None | STFT overlap (None = nperseg/2) |
| `window` | `"hann"` | STFT window function |

**Method:** Computes the STFT, takes the mean power spectral density across the broadband frequency range at each time bin, computes the square root, interpolates back to the original sample rate, and divides the signal by this envelope. A floor of 10⁻¹⁰ prevents division by zero.

### 4.5 `sliding_rms` / `constant_rms`

**What they do:** Detect spikes (action potentials) in filtered MEA voltage traces.

Neural spikes appear as brief, sharp negative deflections in extracellular recordings. Both detectors find these deflections by comparing the signal against a threshold derived from its RMS (root mean square) amplitude.

- **`sliding_rms`** uses a time-varying threshold that adapts to local noise levels — better for non-stationary recordings
- **`constant_rms`** uses a single global threshold — simpler, appropriate for stationary signals

**Types:** `MEATrace → SpikeTrain`, `MEABank → _SpikeBankIntermediate`

**`sliding_rms` parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `k` | 5.0 | Threshold multiplier (k × local RMS) |
| `half_window_ms` | 250.0 | Half-width of sliding RMS window |
| `min_spike_distance_ms` | 1.0 | Minimum gap between detected spikes |
| `min_nonzero_fraction` | 0.2 | Fraction of non-zero samples required in window |
| `zero_eps` | 1e-4 | Values below this are treated as silent |
| `zero_buffer_ms` | 0.0 | Buffer around silent regions to exclude |

**`constant_rms` parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `k` | 5.0 | Threshold multiplier (k × global RMS) |
| `min_spike_distance_ms` | 1.0 | Minimum gap between detected spikes |

**Method:** Both compute threshold = −k × σ (where σ is RMS or local RMS), then find peaks in the inverted signal exceeding that threshold, with a minimum inter-spike distance enforced. `sliding_rms` uses prefix-sum arrays for efficient windowed computation and handles regions of silence (zero-valued samples from upstream masking).

### 4.6 `baseline_correction`

**What it does:** Removes slow fluorescence drift from calcium imaging traces.

Calcium traces exhibit slow baseline wander from photobleaching, focus drift, and other artifacts. This operation estimates the baseline using a rolling percentile filter and subtracts it, preserving the fast calcium transients that indicate neural activity.

**Types:** `CATrace → CATrace`

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `window_frames` | 41 | Sliding window size for percentile filter |
| `percentile` | 20 | Percentile used to estimate baseline (20th = below most transients) |

**Method:** Applies `scipy.ndimage.percentile_filter` to the original camera-rate data to estimate the baseline, then subtracts it and adds back the mean (preserving overall fluorescence level). The corrected trace is linearly interpolated from camera frame times onto the MEA sample grid for downstream alignment.

### 4.7 `rt_detect`

**What it does:** Runs a convolutional neural network (CNN) on raw MEA voltage to detect spikes.

Traditional spike detection (RMS thresholding) can miss overlapping spikes or fire on noise. The RTSort model (from the braindance library) is a CNN trained on labeled spike data that produces per-sample spike probability logits.

**Types:** `MEATrace → RTTrace`, `MEABank → RTBank`

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `inference_scaling_numerator` | 12.6 | Numerator for IQR-based amplitude normalization |
| `pre_median_frames` | None | Samples to use for IQR estimation (None = full trace) |

**Method:** Loads the pre-trained ModelSpikeSorter CNN (conv subnet, CPU, float32). Computes IQR-based input scaling from the signal to normalize amplitude. Runs sliding window inference (200-sample windows at 120-sample stride), with per-window median subtraction. Output is raw logits — apply `sigmoid` to get probabilities.

**Known issue:** Currently produces very large logits (~10⁸) causing sigmoid saturation. Investigation paused.

### 4.8 `sigmoid` / `rt_thresh`

**`sigmoid`** converts raw RTSort logits to probabilities: p = 1 / (1 + e⁻ᶻ). No parameters.

**Types:** `RTTrace → RTTrace`, `RTBank → RTBank`

**`rt_thresh`** detects spikes from the probability signal by finding local maxima above a threshold, with 1 ms minimum separation.

**Types:** `RTTrace → SpikeTrain`, `RTBank → _SpikeBankIntermediate`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `threshold` | 0.275 | Probability cutoff for spike detection |

### 4.9 `gcamp_sim`

**What it does:** Simulates what a calcium indicator (GCaMP) fluorescence trace would look like given a set of detected spikes.

This bridges the gap between electrical recordings (MEA) and optical recordings (calcium imaging). By convolving a spike train with a GCaMP kernel, we generate a predicted fluorescence signal that can be compared against the actual recorded calcium trace.

**Types:** `SpikeTrain → SimCalcium`, `_SpikeBankIntermediate → SimCalciumBank`

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `half_rise_ms` | 80.0 | GCaMP rise half-life (ms) |
| `half_decay_ms` | 500.0 | GCaMP decay half-life (ms) |
| `duration_ms` | 2500.0 | Kernel duration (ms) |
| `peak_dff` | 0.20 | Peak ΔF/F amplitude of kernel |

**Method:** Constructs a GCaMP kernel: k(t) = (1 − e^(−t/τ_rise)) · e^(−t/τ_decay), where τ = half_life / ln(2). The kernel is scaled so its peak equals `peak_dff`. The spike train (binary array with 1 at each spike time) is convolved with the kernel to produce the simulated trace.

### 4.10 `x_corr`

**What it does:** Finds which MEA electrode best matches a recorded calcium trace by cross-correlating the calcium signal against simulated GCaMP responses from all electrodes.

This is the key alignment operation — it answers the question: "which electrode is recording from the same neuron that this calcium ROI is imaging?"

**Types:** `CATrace × SimCalciumBank → CorrelationResult`

**DSL syntax:**
```
ca_trace(11).baseline_correction.x_corr(mea_trace(all).butter_bandpass.sliding_rms.gcamp_sim)
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_lag_ms` | 500.0 | Maximum cross-correlation lag |
| `normalize` | True | Z-score both signals before correlating |

**Method:** For each electrode, z-scores both the recorded calcium trace and the simulated GCaMP trace, computes their cross-correlation, and takes the maximum correlation within ±`max_lag_ms`. The electrode with the highest peak correlation is the best match. Results include the full spatial correlation map (for plotting as a heatmap over electrode positions) and the temporal alignment.

### 4.11 `spectrogram`

**What it does:** Computes the time-frequency power spectral density of an MEA signal.

Visualizes how the frequency content of the signal changes over time — useful for identifying noise sources, verifying filter performance, and understanding signal characteristics.

**Types:** `MEATrace → Spectrogram`

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `nperseg` | 4096 | STFT window size in samples |
| `noverlap` | None | Overlap (None = nperseg/2) |
| `window` | `"hann"` | Window function |
| `scaling` | `"density"` | PSD scaling mode |
| `fmin` | 0 | Lower frequency bound for display |
| `fmax` | — | Upper frequency bound for display |
| `db_scale` | True | Convert power to dB (10·log₁₀) |

### 4.12 `freq_traces`

**What it does:** Extracts power-versus-time traces at specific frequencies of interest from the STFT.

Useful for tracking power-line interference (60 Hz and harmonics) over time or monitoring broadband signal power.

**Types:** `MEATrace → FreqPowerTraces`

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `freqs_hz` | — | List of frequencies to extract (e.g., [60, 120, 300]) |
| `broadband_range_hz` | — | Frequency range for broadband average |
| `nperseg` | 4096 | STFT window size |
| `noverlap` | None | Overlap |
| `window` | `"hann"` | Window function |

---

## 5. Caching

### Why Caching Matters

A typical pipeline might be:
```
mea_trace(861).saturation_mask.notch_filter.butter_bandpass.sliding_rms.gcamp_sim
```

If you change only the `gcamp_sim` parameters and re-run, you don't want to re-compute the saturation mask, notch filter, bandpass, and spike detection. The caching system handles this automatically.

### How It Works

**Memory cache** (within a single run): When the pipeline includes multiple expressions sharing a common prefix — like `mea_trace(861).notch_filter` and `mea_trace(861).notch_filter.butter_bandpass` — the shared prefix is computed once and reused.

**Disk cache** (across runs): After computing each intermediate result, it's saved as a pickle file in `cache_dir`. On subsequent runs, the executor checks for the longest cached prefix of each expression. If the first 4 of 6 operations are already cached, only the last 2 are computed.

**Cache keys** include: the analysis window, margin sizes, all operation parameters, source file paths, and source file modification times. This means:
- Changing any parameter invalidates downstream cache entries
- Modifying a data file invalidates all cache entries that depend on it
- Different windows produce different cache entries

Both tiers can be independently enabled/disabled via `globals_cfg["memory_cache"]` and `globals_cfg["disk_cache"]`.

---

## 6. Configuration Reference

### `ops_cfg`

All operation parameters in one dict. Each key is an operation name, each value is a dict of parameter names to values. These serve as defaults — individual pipeline strings can override them inline.

### `globals_cfg`

| Key | Type | Description |
|-----|------|-------------|
| `show_ops_params` | bool | Embed a parameter panel in the bottom margin of each plot |
| `interactive_plots` | bool | Use ipympl widget backend (hover coords, zoom/pan) vs static PNG |
| `memory_cache` | bool | Enable in-memory prefix reuse within a pipeline run |
| `disk_cache` | bool | Enable disk-persistent pickle cache across runs |

### `paths_cfg`

| Key | Description |
|-----|-------------|
| `mea_h5` | Path to Maxwell MEA recording (.raw.h5) |
| `ca_traces_npz` | Path to calcium imaging traces (.npz) |
| `rt_model_outputs_npy` | Path to precomputed RTSort outputs (.npy) |
| `rt_model_path` | Path to RTSort model directory (init_dict.json + state_dict.pt) |
| `output_dir` | Directory for generated outputs |
| `cache_dir` | Directory for disk cache pickle files |

### `pipeline_cfg` Conventions

- Each sub-pipeline is a plain Python list
- The first item is always a window directive: `"window_ms[start, end]"` or `"window_ms[full]"`
- Subsequent items are DSL strings or overlay groups (lists of DSL strings)
- Multiple sub-pipelines can be concatenated: `pipeline_cfg = section_a + section_b`

---

## 7. Plotting

Every operation result is automatically plotted based on its output type:

| Output Type | Plot Style |
|-------------|------------|
| `MEATrace` | Time-domain voltage trace |
| `SpikeTrain` | Source signal + threshold curve + spike markers |
| `CATrace` | Fluorescence trace (with baseline if corrected) |
| `RTTrace` | Logit or probability trace |
| `RTBank` | Multi-channel subplots (first 5 channels) |
| `SimCalcium` | Simulated fluorescence + spike positions |
| `CorrelationResult` | Spatial heatmap of correlations + temporal alignment |
| `Spectrogram` | Time-frequency heatmap |
| `FreqPowerTraces` | Power vs time at each frequency |
| Overlay groups | Normalized signals overlaid on one axis |

When `show_ops_params` is enabled, each plot includes a panel at the bottom listing the full operation chain and all parameter values used — making every figure self-documenting and reproducible.

---

## 8. Usage Examples

### Basic spike detection
```python
pipeline_cfg = [
    "window_ms[15000, 16000]",
    "mea_trace(861).notch_filter.butter_bandpass.sliding_rms",
]
```
Load 1 second of channel 861 → remove 60 Hz noise → bandpass 350–6000 Hz → detect spikes with adaptive threshold.

### Comparing raw vs filtered
```python
pipeline_cfg = [
    "window_ms[15000, 16000]",
    ["mea_trace(861)", "mea_trace(861).butter_bandpass"],
]
```
Overlay the raw and bandpass-filtered signals on one plot.

### Full MEA-to-calcium alignment
```python
pipeline_cfg = [
    "window_ms[full]",
    "ca_trace(11).baseline_correction.x_corr(mea_trace(all).butter_bandpass.sliding_rms.gcamp_sim)",
]
```
For every MEA channel: bandpass → detect spikes → simulate GCaMP → cross-correlate with calcium trace 11. Find the best-matching electrode.

### Multiple windows
```python
overview = [
    "window_ms[full]",
    "mea_trace(861).saturation_mask",
]

detail = [
    "window_ms[15000, 16000]",
    "mea_trace(861).notch_filter.butter_bandpass.sliding_rms",
]

pipeline_cfg = overview + detail
```
Run a full-recording saturation scan, then a detailed 1-second spike analysis — in one pipeline call.

### CNN spike detection
```python
pipeline_cfg = [
    "window_ms[14487.05, 44352.95]",
    "mea_trace(861).saturation_mask.notch_filter.amp_gain_correction.rt_detect.sigmoid.rt_thresh",
]
```
Mask saturation → notch filter → normalize amplitude → run CNN → sigmoid → threshold to spike times.
