"""Registry factory: create_registry() assembles op registry + source loaders."""
from __future__ import annotations

from typing import Callable, Dict, Tuple

from casi.engine.loaders import load_ca_trace, load_mea_trace, load_rtsort
from casi.engine.margins import margin_butter_bandpass, margin_notch_filter
from casi.engine.ops.analysis import op_baseline_correction, op_spike_curate, op_spike_pca
from casi.engine.ops.correlation import op_x_corr
from casi.engine.ops.detection import (
    op_constant_rms, op_rt_detect, op_rt_thresh, op_sigmoid, op_sliding_rms,
)
from casi.engine.ops.filtering import op_amp_gain_correction, op_butter_bandpass, op_notch_filter
from casi.engine.ops.saturation import op_saturation_mask, op_saturation_survey
from casi.engine.ops.simulation import op_gcamp_sim
from casi.engine.ops.spectral import op_freq_traces, op_spectrogram
from casi.engine.registry import OpRegistry


def create_registry(
    plot_backend: str = "matplotlib",
) -> Tuple[OpRegistry, Dict[str, Callable]]:
    """Build and return a pre-configured (registry, source_loaders) pair."""
    registry = OpRegistry()

    # Op handlers
    registry.register_op("butter_bandpass",     op_butter_bandpass)
    registry.register_op("notch_filter",         op_notch_filter)
    registry.register_op("saturation_mask",     op_saturation_mask)
    registry.register_op("sliding_rms",          op_sliding_rms)
    registry.register_op("constant_rms",         op_constant_rms)
    registry.register_op("spike_pca",            op_spike_pca)
    registry.register_op("spike_curate",         op_spike_curate)
    registry.register_op("baseline_correction",  op_baseline_correction)
    registry.register_op("rt_detect",             op_rt_detect)
    registry.register_op("sigmoid",              op_sigmoid)
    registry.register_op("rt_thresh",            op_rt_thresh)
    registry.register_op("gcamp_sim",            op_gcamp_sim)
    registry.register_op("x_corr",              op_x_corr)
    registry.register_op("spectrogram",          op_spectrogram)
    registry.register_op("freq_traces",          op_freq_traces)
    registry.register_op("amp_gain_correction",  op_amp_gain_correction)
    registry.register_op("saturation_survey",    op_saturation_survey)

    # Margin calculators
    registry.register_margin_calculator("butter_bandpass", margin_butter_bandpass)
    registry.register_margin_calculator("notch_filter",    margin_notch_filter)

    # Plot handlers (live in casi.plot_backends/, dispatched by chosen backend)
    from casi.plot_backends import register_for_backend
    register_for_backend(registry, plot_backend)

    source_loaders: Dict[str, Callable] = {
        "mea_trace": load_mea_trace,
        "ca_trace":  load_ca_trace,
        "rtsort":    load_rtsort,
    }

    return registry, source_loaders
