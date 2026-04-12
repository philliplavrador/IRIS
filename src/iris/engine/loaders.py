"""Source loaders + module-level data caches for MEA, calcium, and RTSort data."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
from spikeinterface.extractors import MaxwellRecordingExtractor

from iris.engine.types import CATrace, MEABank, MEATrace, PipelineContext, RTTrace

# Module-level data caches
_mea_recording_cache: Dict[str, Any] = {}
_rtsort_cache: Dict[str, Any] = {}
_calcium_cache: Dict[str, Any] = {}


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
