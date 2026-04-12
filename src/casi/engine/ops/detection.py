"""Detection op handlers: sliding_rms, constant_rms, rt_detect, rt_thresh, sigmoid."""
from __future__ import annotations

import json

import numpy as np
import torch
from scipy.signal import find_peaks

from casi.engine.helpers import detect_spikes_constant_rms, detect_spikes_sliding_rms
from casi.engine.types import MEATrace, PipelineContext, RTTrace, SpikeTrain

# Module-level model cache (shared with loaders via engine package)
_rtsort_model_cache = {}


def _load_rtsort_model(model_dir):
    """Load and cache RTSort ModelSpikeSorter for CPU inference.
    Returns (conv_module, model_info_dict)."""
    from pathlib import Path

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
