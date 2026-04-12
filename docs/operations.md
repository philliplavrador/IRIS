# Pipeline Operations Reference

All operations are defined in [`engine.py`](engine.py). Each takes a typed input and returns a typed output as described below.

## Table of Contents

**Signal Filtering & Preprocessing**
- [`butter_bandpass`](#butter_bandpass) — Bandpass IIR filter
- [`notch_filter`](#notch_filter) — Power-line noise suppression
- [`saturation_mask`](#saturation_mask) — ADC clipping detection & masking
- [`amp_gain_correction`](#amp_gain_correction) — Amplitude normalization by broadband power

**Spike Detection**
- [`constant_rms`](#constant_rms) — Fixed-threshold spike detection
- [`sliding_rms`](#sliding_rms) — Adaptive threshold spike detection
- [`rt_detect`](#rt_detect) — CNN-based spike detection (RTSort model)
- [`sigmoid`](#sigmoid) — Logit-to-probability conversion
- [`rt_thresh`](#rt_thresh) — Thresholding RTSort model outputs

**Calcium Imaging**
- [`baseline_correction`](#baseline_correction) — Fluorescence drift removal

**Signal Simulation & Analysis**
- [`gcamp_sim`](#gcamp_sim) — GCaMP fluorescence kernel convolution
- [`x_corr`](#x_corr) — Cross-correlation alignment
- [`spectrogram`](#spectrogram) — Short-time Fourier transform
- [`freq_traces`](#freq_traces) — Power-vs-time at specific frequencies

**Diagnostics**
- [`saturation_survey`](#saturation_survey) — Per-channel saturation quantification

## `butter_bandpass` — [source](engine.py#L1396)
<a id="butter_bandpass"></a>

`MEATrace → MEATrace` | `MEABank → MEABank`

Applies a zero-phase Butterworth bandpass IIR filter to remove frequencies outside `[low_hz, high_hz]`.

**Parameters:** `low_hz`, `high_hz`, `order`, `zero_phase` (bool)

### Filter design

$$f_{\text{low\_norm}} = \frac{f_{\text{low}}}{f_s / 2}, \quad f_{\text{high\_norm}} = \frac{f_{\text{high}}}{f_s / 2}$$

Filter coefficients `(b, a)` are computed via `scipy.signal.butter(order, [f_low_norm, f_high_norm], btype='band')`.

### Filtering

- `zero_phase=True` (default): forward-backward filtering via `filtfilt` — applies the filter twice (forward then reverse), giving **zero phase distortion** and effectively **doubling the filter order**.
- `zero_phase=False`: single-pass causal filtering via `lfilter`, which introduces phase lag.

If the signal was loaded with margin padding (to avoid edge artifacts), margins are trimmed after filtering:

$$x_{\text{out}} = x_{\text{filtered}}[m_L \; : \; N - m_R]$$

where $m_L$, $m_R$ are the left and right margin sample counts.

## `notch_filter` — [source](engine.py#L1422)
<a id="notch_filter"></a>

`MEATrace → MEATrace` | `MEABank → MEABank`

Applies a series of IIR notch filters to suppress power-line noise at a fundamental frequency and its harmonics.

**Parameters:** `notch_freq_hz`, `notch_q`, `harmonics` (list of integers, e.g. `[1, 2, 3, 4, 5]`)

### Filter design

For each harmonic $h$ in the list, the target frequency is $f_h = f_{\text{notch}} \times h$. A 2nd-order IIR notch is designed at $f_h$ with quality factor $Q$:

$$H(z) = \frac{1 - 2\cos(2\pi f_h / f_s)\, z^{-1} + z^{-2}}{1 - 2\frac{Q}{Q+1}\cos(2\pi f_h / f_s)\, z^{-1} + \frac{Q-1}{Q+1} z^{-2}}$$

Coefficients are converted to SOS format via `tf2sos` and applied zero-phase via `sosfiltfilt`. Filters are applied sequentially — one per harmonic — so the signal passes through all notches in series. Margins are trimmed after filtering.

## `saturation_mask` — [source](engine.py#L1793)
<a id="saturation_mask"></a>

`MEATrace → MEATrace` | `MEABank → MEABank`

Detects ADC clipping / flatline episodes where the signal stays essentially constant (plateau) and NaN-masks them. The plateau need not be at the global min or max — any sustained flat region is detected. Output preserves the original time axis (same length array; masked samples become NaN).

**Parameters:** `win`, `eps_range`, `min_run`, `lookahead`, `gap_merge`, `ceil_eps`

### Step 1–2: Sliding window range → per-sample flat mask

For each sample $t$, the local range within a centered window of `win` samples is computed via O(n) running max/min filters:

$$R[t] = \max_{|i-t| \leq w/2} x[i] \;-\; \min_{|i-t| \leq w/2} x[i]$$

A sample is marked flat if its local range is at or below the tolerance:

$$\text{flat}[t] = \bigl(R[t] \leq \varepsilon_{\text{range}}\bigr)$$

Windows containing NaN propagate NaN through the max/min filters, causing `flat[t] = \text{False}` (NaN comparisons are False).

### Step 3: Run-length encoding and filtering

Contiguous runs of $\text{flat} = \text{True}$ are detected via `np.diff`. Runs shorter than `min_run` samples are discarded. If `gap_merge > 0`, adjacent runs separated by fewer than `gap_merge` samples are merged into a single run (handles brief departures from the plateau).

### Step 4: Lookahead confirmation

For each candidate episode, the algorithm checks whether the signal truly recovers. If another flat run starts within `lookahead` samples of the current episode's end, the two are merged into a single episode. This repeats until a gap ≥ `lookahead` confirms recovery.

### Step 4b: Global ceiling-hit sweep

The flat mask (steps 1–2) only catches sustained flat regions. Isolated ceiling touches — brief ADC clips where the signal spikes to the ceiling for a few samples — are missed. After determining the ceiling value from detected episodes (median of flat-detected samples), the entire signal is swept for samples within `ceil_eps` µV of that ceiling:

$$\text{ceil\_hit}[t] = \bigl(|x[t] - \hat{c}| \leq \varepsilon_{\text{ceil}}\bigr)$$

where $\hat{c}$ is the consensus ceiling value. `ceil_eps` is typically wider than `eps_range` (e.g., 10.0 µV vs 1.0 µV) because individual near-ceiling spikes don't exactly match the plateau value. These ceiling-hit runs are grouped using `lookahead` and merged with the flat-mask episodes.

### Step 5: NaN masking

All samples within each final episode interval $[s, e)$ are set to NaN:

$$x_{\text{out}}[t] = \begin{cases} \text{NaN} & \text{if } t \in \text{any episode} \\ x[t] & \text{otherwise} \end{cases}$$

Margins are trimmed (same pattern as filter ops).

## `amp_gain_correction` — [source](engine.py#L1996)
<a id="amp_gain_correction"></a>

`MEATrace → MEATrace` | `MEABank → MEABank`

Normalizes signal amplitude over time by dividing by the square root of the broadband power envelope. Compensates for slow gain changes (electrode drift, tissue settling) so that spike amplitude is consistent across the recording.

**Parameters:** `broadband_range_hz`, `nperseg`, `noverlap`, `window`

### Broadband power envelope

The STFT is computed via `scipy.signal.spectrogram` with the given window parameters. The broadband power at each STFT time bin is the mean PSD across the configured frequency range:

$$P_{\text{bb}}[t] = \frac{1}{|F_{\text{bb}}|} \sum_{f \in F_{\text{bb}}} S[f, t], \quad F_{\text{bb}} = \{f_i : f_{\text{low}} \leq f_i \leq f_{\text{high}}\}$$

### Envelope interpolation

The STFT time grid (one value per hop) is interpolated back to the original sample rate via linear interpolation:

$$\hat{E}[n] = \text{interp}\bigl(n,\; t_{\text{STFT}} \cdot f_s,\; \sqrt{\max(P_{\text{bb}},\; 10^{-10})}\bigr)$$

The $10^{-10}$ floor prevents division by zero.

### Correction

$$x_{\text{out}}[n] = \frac{x[n]}{\hat{E}[n]}$$

Margins are trimmed before processing; the output has `margin_left = margin_right = 0`.

## `constant_rms` — [source](engine.py#L1473)
<a id="constant_rms"></a>

`MEATrace → SpikeTrain` | `MEABank → _SpikeBankIntermediate`

Detects negative-polarity spikes using a fixed threshold derived from the global RMS of the signal.

**Parameters:** `k`, `min_spike_distance_ms`

### Threshold

$$\theta = -k \cdot \sigma(x), \quad \sigma(x) = \sqrt{\frac{1}{N}\sum_{n=0}^{N-1} x[n]^2 - \bar{x}^2}$$

where $\sigma$ is the standard deviation of the full signal window.

### Spike detection

Peaks are found in $-x[n]$ (inverted signal) satisfying:
- $-x[n] > -\theta = k\sigma$ (i.e. $x[n] < \theta$)
- Minimum separation of $\lfloor f_s \cdot t_{\min} / 1000 \rfloor$ samples between consecutive spikes

## `sliding_rms` — [source](engine.py#L1450)
<a id="sliding_rms"></a>

`MEATrace → SpikeTrain` | `MEABank → _SpikeBankIntermediate`

Detects negative-polarity spikes using a time-varying threshold derived from a local sliding-window RMS. Adapts to non-stationary noise levels across the recording.

**Parameters:** `k`, `half_window_ms`, `min_spike_distance_ms`, `min_nonzero_fraction`, `zero_eps`, `zero_buffer_ms`

### Sliding RMS

Samples with $|x[n]| \leq \varepsilon_0$ (`zero_eps`) are excluded from RMS calculation (treated as silent/dead).

Let $W = 2w + 1$ be the window length where $w = \lfloor f_s \cdot t_{\text{half}} / 1000 \rfloor$, and let $\text{nz}[n] = \mathbf{1}[|x[n]| > \varepsilon_0]$. Using prefix sums:

$$\text{SS}[n] = \sum_{i \in W_n} x[i]^2 \cdot \text{nz}[i], \quad \text{NN}[n] = \sum_{i \in W_n} \text{nz}[i]$$

$$\text{RMS}[n] = \sqrt{\frac{\text{SS}[n]}{\max(\text{NN}[n], 1)}}$$

If $\text{NN}[n] < \lfloor W \cdot f_{\min} \rfloor$ (fewer than `min_nonzero_fraction` of samples are non-zero), $\text{RMS}[n] = \text{NaN}$.

### Adaptive threshold

$$\theta[n] = -k \cdot \text{RMS}[n]$$

If `zero_buffer_ms > 0`, a dilation is applied — any sample within $\lfloor f_s \cdot t_{\text{buf}} / 1000 \rfloor$ samples of a zero region is also masked as invalid.

### Spike detection

A sample $n$ is a spike candidate if:
- $\theta[n]$ is finite (i.e. the window had enough non-zero samples)
- $x[n]$ is not in a zero/masked region
- $x[n] < \theta[n]$
- It is a local minimum of $x$ with minimum separation $\lfloor f_s \cdot t_{\min} / 1000 \rfloor$ samples

## `baseline_correction` — [source](engine.py#L1493)
<a id="baseline_correction"></a>

`CATrace → CATrace`

Removes slow fluorescence drift from calcium traces using a rolling percentile baseline estimate.

**Parameters:** `window_frames`, `percentile`

### Baseline estimation

Applied to the original camera-rate data before interpolation:

$$B[t] = \text{percentile}_p\bigl(F[t - w/2 : t + w/2]\bigr)$$

computed via `scipy.ndimage.percentile_filter` with nearest-edge padding at boundaries.

### Correction

$$F_{\text{corrected}}[t] = F[t] - B[t] + \bar{F}$$

where $\bar{F} = \frac{1}{T}\sum_t F[t]$ is the mean of the original trace. The mean is added back to preserve the overall fluorescence level.

The corrected trace is then **linearly interpolated** from camera frame times onto the MEA sample grid for downstream alignment.

## `rt_detect` — [source](engine.py#L1525)
<a id="rt_detect"></a>

`MEATrace → RTTrace` | `MEABank → RTBank`

Runs braindance's RTSort detection CNN on raw MEA voltage traces, producing per-sample logits (unnormalized spike probabilities). This replaces the need to pre-run RTSort externally.

**Parameters:** `inference_scaling_numerator`, `pre_median_frames`

### Model

Uses `ModelSpikeSorter` from braindance, loaded from `paths_cfg["rt_model_path"]` (`init_dict.json` + `state_dict.pt`). Only the convolutional inference subnet (`model.model.conv`) is used, matching braindance's own `compile()` path. The model is forced to CPU and float32.

### IQR-based input scaling

The first `pre_median_frames` samples (default 1000) are used to estimate signal amplitude:

$$\text{IQR} = P_{75}(x[0{:}N_{\text{pre}}]) - P_{25}(x[0{:}N_{\text{pre}}])$$

$$s_{\text{inference}} = \frac{s_{\text{num}}}{\max(\text{IQR},\; 10^{-6})}$$

where $s_{\text{num}}$ is `inference_scaling_numerator` (default 12.6).

### Sliding window inference

The model accepts fixed-size windows of `sample_size` frames (200 at 20 kHz = 10 ms) and outputs `num_output_locs` frames (120 = 6 ms) per window. The front and end buffers (40 frames each) are discarded. Windows are placed at stride `num_output_locs`:

$$\text{starts} = \{0,\; L_{\text{out}},\; 2 L_{\text{out}},\; \ldots\}$$

For each window starting at sample $k$:

1. Extract chunk $x[k : k + S]$ and subtract its median: $\hat{x} = x - \tilde{x}$
2. Form input tensor: $\mathbf{t} = \hat{x} \cdot s_{\text{input}} \cdot s_{\text{inference}}$ with shape $(1, 1, S)$
3. Forward pass: $\mathbf{y} = \text{conv}(\mathbf{t})$ → shape $(1, 1, L_{\text{out}})$
4. Write $\mathbf{y}$ into the output array at position $k$

Any remaining samples at the end are handled by running inference on the last `sample_size` frames and copying only the uncovered tail.

### Output

Output length is $N - b_f - b_e$ where $b_f$, $b_e$ are the front/end buffer sizes. The `window_samples` tuple is adjusted inward accordingly. Output values are raw logits — apply `.sigmoid` to get probabilities.

## `sigmoid` — [source](engine.py#L1589)
<a id="sigmoid"></a>

`RTTrace → RTTrace`

Converts raw RTSort model logit outputs to probabilities via the logistic sigmoid function. No parameters.

$$p[n] = \sigma(z[n]) = \frac{1}{1 + e^{-z[n]}}$$

where $z[n]$ is the raw logit at sample $n$. Output is in $[0, 1]$.

## `rt_thresh` — [source](engine.py#L1601)
<a id="rt_thresh"></a>

`RTTrace → SpikeTrain`

Thresholds RTSort probability output to detect spike events. RTSort-specific equivalent of `constant_rms` / `sliding_rms`, operating on model probability rather than raw voltage.

**Parameters:** `threshold`

### Event detection

Finds local maxima of $p[n]$ satisfying:
- $p[n] > \theta$ (`threshold`)
- Minimum separation of 1 ms ($\lfloor f_s / 1000 \rfloor$ samples) between consecutive events

## `gcamp_sim` — [source](engine.py#L1634)
<a id="gcamp_sim"></a>

`SpikeTrain → SimCalcium` | `_SpikeBankIntermediate → SimCalciumBank`

Simulates a fluorescence trace by convolving a binary spike train with a GCaMP indicator kernel.

**Parameters:** `half_rise_ms`, `half_decay_ms`, `duration_ms`, `peak_dff`

### Kernel construction

Time constants from the half-life parameters:

$$\tau_{\text{rise}} = \frac{t_{1/2}^{\text{rise}}}{1000 \cdot \ln 2}, \quad \tau_{\text{decay}} = \frac{t_{1/2}^{\text{decay}}}{1000 \cdot \ln 2}$$

Kernel shape (evaluated at sample times $t = 0, 1/f_s, 2/f_s, \ldots$):

$$k(t) = \left(1 - e^{-t / \tau_{\text{rise}}}\right) \cdot e^{-t / \tau_{\text{decay}}}$$

Scaled so its peak equals `peak_dff`:

$$k_{\text{scaled}}(t) = k(t) \cdot \frac{\Delta F / F_0}{\max_t\, k(t)}$$

### Convolution

A binary spike train $s[n]$ is formed by placing a $1$ at each detected spike index:

$$\hat{F}[n] = (s * k_{\text{scaled}})[n] = \sum_{m=0}^{M-1} s[n - m]\, k_{\text{scaled}}[m]$$

where $M$ is the kernel length in samples (`duration_ms`). Output is truncated to the original signal length $N$.

## `x_corr` — [source](engine.py#L1689)
<a id="x_corr"></a>

`CATrace × SimCalciumBank → CorrelationResult`

Cross-correlates a recorded calcium trace against every simulated calcium trace in the bank to find the best-matching electrode.

**DSL syntax:** `ca_trace(N).baseline_correction.x_corr(mea_trace(all).butter_bandpass.sliding_rms.gcamp_sim)`

**Parameters:** `max_lag_ms`, `normalize` (bool), `adapt_circle_size` (bool)

When `adapt_circle_size=True`, circle sizes in the spatial heatmap are scaled by `(1 − pct_masked/100)` per electrode (requires a `saturation_survey` result in the same pipeline run).

### Normalization

If `normalize=True`, both signals are z-scored before correlation:

$$\tilde{c}[n] = \frac{c[n] - \bar{c}}{\sigma_c + \varepsilon}, \quad \tilde{s}_i[n] = \frac{s_i[n] - \bar{s}_i}{\sigma_{s_i} + \varepsilon}$$

where $\varepsilon = 10^{-10}$ for numerical stability.

### Cross-correlation

For each electrode $i$, the cross-correlation normalized by signal length:

$$R_i[\tau] = \frac{1}{N} \sum_{n=0}^{N-1} \tilde{c}[n]\, \tilde{s}_i[n - \tau]$$

The score for electrode $i$ is the maximum correlation within the lag window:

$$\rho_i = \max_{|\tau| \leq \tau_{\max}} R_i[\tau], \quad \tau_{\max} = \lfloor f_s \cdot t_{\max\text{lag}} / 1000 \rfloor$$

The best-matching electrode is $i^* = \arg\max_i\, \rho_i$.

## `spectrogram` — [source](engine.py#L1725)
<a id="spectrogram"></a>

`MEATrace → Spectrogram`

Computes the short-time Fourier transform (STFT) power spectral density.

**Parameters:** `nperseg`, `noverlap`, `window`, `scaling`, `fmin`, `fmax`, `db_scale`

### STFT

The signal is divided into overlapping frames of length `nperseg` (hop size $H = N_{\text{seg}} - N_{\text{overlap}}$), each multiplied by a window function $w[m]$ (default: Hann). PSD at each time frame and frequency bin:

$$S[f, t] = \frac{2}{f_s \cdot \|w\|^2} \left| \sum_{m=0}^{N_{\text{seg}}-1} x[t \cdot H + m]\, w[m]\, e^{-j 2\pi f m / N_{\text{seg}}} \right|^2$$

Bins outside $[f_{\min}, f_{\max}]$ are discarded.

### dB conversion

If `db_scale=True`:

$$S_{\text{dB}}[f, t] = 10 \cdot \log_{10}(S[f, t] + 10^{-10})$$

The $10^{-10}$ floor prevents $\log(0)$.

## `freq_traces` — [source](engine.py#L1759)
<a id="freq_traces"></a>

`MEATrace → FreqPowerTraces`

Extracts power-vs-time traces at specific frequencies of interest, plus a broadband average, from the STFT. Uses the same STFT as `spectrogram` but operates on linear (non-dB) power.

**Parameters:** `freqs_hz` (list), `broadband_range_hz` (list of 2), `nperseg`, `noverlap`, `window`

### Narrowband extraction

For each requested frequency $f_0$, the nearest bin is selected:

$$i^* = \arg\min_i |f_i - f_0|, \quad P_{f_0}[t] = S[i^*, t]$$

### Broadband average

Mean PSD over the frequency range $[f_{bb,\text{low}}, f_{bb,\text{high}}]$:

$$P_{\text{bb}}[t] = \frac{1}{|F_{\text{bb}}|} \sum_{f \in F_{\text{bb}}} S[f, t]$$

where $F_{\text{bb}} = \{f_i : f_{bb,\text{low}} \leq f_i \leq f_{bb,\text{high}}\}$.

## `saturation_survey` — [source](engine.py#L2036)
<a id="saturation_survey"></a>

`MEABank → SaturationReport`

Detects ADC saturation episodes across all MEA channels using the same algorithm as `saturation_mask` (walking the trace sample-by-sample), and summarizes the results per-channel. Returns a report with channel IDs, electrode locations, and the count of saturated samples per channel. Useful for understanding which electrodes are affected by saturation and how much of the recording window is compromised.

**Parameters:** `min_run`, `eps_range`, `lookahead`, `recovery_eps`, `pre_samples`, `scope`, `plot_type`

### Saturation detection

Same algorithm as `saturation_mask`. For each channel, the number of masked samples is counted.

- `min_run` (default: 20) — minimum consecutive samples within `eps_range` to initiate a saturation episode
- `eps_range` (default: 1.0 µV) — tolerance for considering samples part of a plateau
- `lookahead` (default: 400 samples) — window to check for recovery from saturation
- `recovery_eps` (default: 5.0 µV) — tolerance for extending saturation end-time during recovery check
- `pre_samples` (default: 0) — extra samples before saturation start to include
- `scope` (default: "all") — either "all" (count all episodes) or "leading" (count only leading saturation at recording start)

### Output visualization

The returned `SaturationReport` contains electrode locations and per-channel saturation percentages. Three plotting modes are available via `plot_type`:

- **`"histogram"` (default)**: Bar chart showing masked sample count per channel in recording file order, with a secondary y-axis displaying % of window masked. Top-10 worst channels are listed.
- **`"scatter"`**: 2D scatterplot with electrode XY coordinates (from Maxwell array layout), with point color indicating "% of window masked" on a yellow-orange-red colormap. Useful for identifying spatial clustering of saturation.
- **`"survival"`**: Complementary CDF (survival function): for each saturation threshold T (0–100%), plots the number of electrodes with saturation ≥ T%. Shows an S-curve with two flat regions — the first indicating shared leading saturation, the second indicating chronically saturated electrodes. Helps identify thresholds for trimming the recording start and dropping irreparable channels.

---

# Adding a new operation

This section is the authoritative contract for adding a new op to IRIS. Both human contributors and the analysis agent follow it. The op does not ship until all six touch points are present and `scripts/check_op_registered.py <name>` returns `PASS`.

## When to add a new op

Add a new op only when a repeated ad-hoc DSL pattern or a specific user analysis need cannot be expressed by composing existing ops. Three warning signs that an op is premature:

1. It would be used exactly once. (Just write the DSL for that single case.)
2. It can be built by chaining two or three existing ops. (Chain them in the DSL.)
3. No reference supports its math. (Fix that first — this is rule 2 of the partner contract.)

## The autonomous op-creation flow (agent-driven)

When the user asks for an op that isn't in [`iris ops list`](../src/iris/cli.py) and the answer isn't an existing-op composition, the analysis agent runs this flow:

1. **Search** — check that the op really doesn't exist. Look at the TOC above and at `iris ops list`. If there's something close with a different name, propose that instead.

2. **Research** — delegate to `iris-researcher` via the `Task` tool with a specific brief. The researcher saves primary sources under `projects/<active>/claude_references/`. The analysis agent reads every new stub before citing.

3. **Draft a proposal** — fill out [`op-proposal-template.md`](op-proposal-template.md) and save it to `docs/op-proposals/<op_name>.md`. Every section is required. The **cross-check against user goal** section (§6) is the gate — if the agent cannot convincingly explain how the op serves the active project's `## Goals`, it STOPS and surfaces the mismatch:

   > "I might be building the wrong thing. Your goal is X; this op solves Y. Which is it?"

4. **User approval** — the agent shows the user the proposal file path and summarizes §1 (Identity), §2 (Signature), §3 (Parameters), §6 (Cross-check). The user either approves, asks for changes, or rejects. No implementation happens without explicit approval.

5. **Implement across all six touch points.** See the checklist below. `docs/operations.md` (step 5) is **mandatory** — the op does not ship without it.

6. **Verify** — run `python scripts/check_op_registered.py <name>`. Every check must be `[x]`. If any is `[ ]`, go back and fix.

7. **Run the op against the user's data** to confirm it produces something sensible before marking the task done.

8. **Log it** — append to `claude_history.md`:
   - `## Decisions` — `added op_<name> [reason: <one-line>]`
   - `## Operations Run` — the first DSL string that used it, with the session path

## The six touch points

Every op must be present in all six places. `scripts/check_op_registered.py` validates all six by regex + YAML parsing without importing the engine, so it works in any environment.

### Touch point 1 — `TYPE_TRANSITIONS` in [`src/iris/engine.py`](../src/iris/engine.py)

Add a row mapping the op name to its `{input_type: output_type}` dict. One entry per valid input type:

```python
TYPE_TRANSITIONS: Dict[str, Dict[DataType, DataType]] = {
    # ...
    "my_new_op": {MEATrace: MEATrace, MEABank: MEABank},
}
```

For function-ops (sigmoid-style, no type change), use an empty dict: `"sigmoid": {}`.

### Touch point 2 — handler function in [`src/iris/engine.py`](../src/iris/engine.py)

Name the handler `op_<name>` and place it in the OP HANDLERS section near similar ops. Signature pattern:

```python
def op_my_new_op(inp: MEATrace, ctx: PipelineContext, *,
                 param1, param2) -> MEATrace:
    """<one-line purpose>.

    <optional: math citation with reference path>
    """
    # 1. Validate params
    # 2. Run the algorithm
    # 3. Return <OutputType>(...)
```

Keyword arguments (after `*`) must match the parameter names in `configs/ops.yaml`. Margin handling (if the op is a filter) goes through the existing margin-calculator registration pattern — see `op_butter_bandpass` for the canonical example.

### Touch point 3 — `register_op` call in `create_registry()`

Add a line inside `create_registry()` in [`src/iris/engine.py`](../src/iris/engine.py):

```python
registry.register_op("my_new_op", op_my_new_op)
```

Group it with ops of the same category (filters, spike detection, etc.) for readability.

### Touch point 4 — defaults entry in [`configs/ops.yaml`](../configs/ops.yaml)

Add a top-level key matching the op name. Every parameter from the handler signature must have a default here, with an inline comment explaining units and any constraints:

```yaml
my_new_op:
  param1: 350         # Hz, must be > 0
  param2: hann        # window type: hann | hamming | blackman
```

Function-ops with no parameters get an empty dict: `my_new_op: {}`. Never use `null` — the validator rejects it.

### Touch point 5 — documentation section in [`docs/operations.md`](operations.md)

Add a full section following the existing pattern. This is the authoritative source for the op's math and user-facing reference. Required subsections:

```markdown
## `my_new_op` — [source](engine.py#LNNN)
<a id="my_new_op"></a>

`InputType → OutputType` | `InputType2 → OutputType2`

<One-paragraph description of what the op does and when to use it.>

**Parameters:** `param1`, `param2`, ...

### <Algorithm / math subsection>

$$<LaTeX formula>$$

<prose explaining the formula>

### <Edge cases subsection>

<NaN handling, margin trimming, etc.>

### Citations

- `claude_references/<ref>.md` — <one sentence supporting the math>
```

Also add a bullet to the Table of Contents at the top of the file under the correct category. The `## ` heading must use literal backticks around the op name (`` ## `my_new_op` —``), not curly quotes — the verifier regex is strict.

### Touch point 6 — test in [`tests/test_op_registry.py`](../tests/test_op_registry.py)

Add a dedicated `test_<name>_transitions` function near the other transition tests:

```python
def test_my_new_op_transitions():
    registry, _ = create_registry()
    assert registry.validate_type_transition("my_new_op", MEATrace) is MEATrace
    assert registry.validate_type_transition("my_new_op", MEABank) is MEABank
```

One assertion per `{input_type: output_type}` pair from touch point 1. If the op would raise on a bad input type, add a negative test mirroring `test_invalid_input_type_raises`.

Behavioral tests (with synthetic data) are strongly preferred but not enforced by the verifier. When you add them, use helpers from [`tests/synthetic_data.py`](../tests/synthetic_data.py).

## Verifying

```bash
python scripts/check_op_registered.py my_new_op
# PASS: my_new_op
#   [x] TYPE_TRANSITIONS entry in src/iris/engine.py
#   [x] handler function `op_my_new_op(...)` in src/iris/engine.py
#   [x] register_op("my_new_op", ...) in create_registry()
#   [x] `my_new_op:` entry in configs/ops.yaml
#   [x] `## my_new_op` section in docs/operations.md
#   [x] `test_my_new_op_transitions` in tests/test_op_registry.py
```

Or run `--all` to audit every op in the repo at once.

## Proactive suggestions

When the agent notices a repeated DSL pattern across sessions (e.g. the user runs `mea_trace(X).butter_bandpass.sliding_rms.freq_traces` three times in a week with minor variations), it may suggest formalizing it as an op. That suggestion goes through the **same** flow above — research, proposal, cross-check, approval — not a shortcut.

Proactive suggestions are optional, one per conversation at most, and only when the pattern is clearly repeating. The user can always decline.
