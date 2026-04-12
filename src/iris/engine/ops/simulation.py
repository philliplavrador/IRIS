"""Simulation op handlers: gcamp_sim + _build_gcamp_kernel."""
from __future__ import annotations

import numpy as np
from scipy.signal import convolve
from tqdm.auto import tqdm

from iris.engine.types import (
    PipelineContext, SimCalcium, SimCalciumBank, SpikeTrain, _SpikeBankIntermediate,
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
