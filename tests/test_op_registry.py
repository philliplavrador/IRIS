"""Op registry + type-transition tests."""

from __future__ import annotations

import pytest

from iris.engine import (
    TYPE_TRANSITIONS,
    CATrace,
    MEABank,
    MEATrace,
    OpRegistry,
    SimCalcium,
    SimCalciumBank,
    Spectrogram,
    SpikeTrain,
    _SpikeBankIntermediate,
    create_registry,
)

EXPECTED_OP_COUNT = 17

EXPECTED_OP_NAMES = {
    "butter_bandpass",
    "notch_filter",
    "saturation_mask",
    "constant_rms",
    "sliding_rms",
    "spike_pca",
    "spike_curate",
    "baseline_correction",
    "rt_detect",
    "sigmoid",
    "rt_thresh",
    "gcamp_sim",
    "spectrogram",
    "freq_traces",
    "amp_gain_correction",
    "saturation_survey",
    "x_corr",
}


def test_create_registry_default_backend():
    registry, source_loaders = create_registry()
    assert isinstance(registry, OpRegistry)
    assert set(source_loaders) == {"mea_trace", "ca_trace", "rtsort"}
    # All 17 ops + 1 overlay handler + 11 plot handlers + 2 margin calculators
    assert len(registry._handlers) == EXPECTED_OP_COUNT
    assert len(registry._plot_handlers) == 11
    assert registry._overlay_plot_handler is not None


def test_type_transitions_covers_every_registered_op():
    """Lock-in: TYPE_TRANSITIONS must surface all 17 hardcoded ops (incl. binary)."""
    registry, _ = create_registry()
    assert set(TYPE_TRANSITIONS.keys()) == EXPECTED_OP_NAMES
    assert set(registry._handlers.keys()) == EXPECTED_OP_NAMES
    # Every op publishes at least one transition row (binary ops included).
    for name in EXPECTED_OP_NAMES:
        assert TYPE_TRANSITIONS[name], f"{name} has no transitions"


def test_binary_ops_have_signatures():
    """spike_curate and x_corr are binary; BINARY_OP_SIGNATURES documents their right operand."""
    from iris.engine.type_system import BINARY_OP_SIGNATURES

    assert set(BINARY_OP_SIGNATURES.keys()) == {"spike_curate", "x_corr"}


def test_create_registry_invalid_backend_raises():
    with pytest.raises(ValueError, match="Unknown plot_backend"):
        create_registry(plot_backend="invalid")


@pytest.mark.parametrize("op_name", sorted(TYPE_TRANSITIONS.keys()))
def test_op_in_type_transitions(op_name):
    """Every op listed in TYPE_TRANSITIONS must be registered by create_registry."""
    registry, _ = create_registry()
    if TYPE_TRANSITIONS[op_name]:  # function-ops have empty transitions
        assert op_name in registry._handlers, f"{op_name} not registered"


def test_butter_bandpass_transitions():
    registry, _ = create_registry()
    assert registry.validate_type_transition("butter_bandpass", MEATrace) is MEATrace
    assert registry.validate_type_transition("butter_bandpass", MEABank) is MEABank


def test_sliding_rms_transitions():
    registry, _ = create_registry()
    assert registry.validate_type_transition("sliding_rms", MEATrace) is SpikeTrain
    assert registry.validate_type_transition("sliding_rms", MEABank) is _SpikeBankIntermediate


def test_gcamp_sim_transitions():
    registry, _ = create_registry()
    assert registry.validate_type_transition("gcamp_sim", SpikeTrain) is SimCalcium
    assert registry.validate_type_transition("gcamp_sim", _SpikeBankIntermediate) is SimCalciumBank


def test_spectrogram_transitions():
    registry, _ = create_registry()
    assert registry.validate_type_transition("spectrogram", MEATrace) is Spectrogram


def test_baseline_correction_transitions():
    registry, _ = create_registry()
    assert registry.validate_type_transition("baseline_correction", CATrace) is CATrace


def test_invalid_input_type_raises():
    registry, _ = create_registry()
    with pytest.raises(TypeError, match="cannot accept input type"):
        registry.validate_type_transition("butter_bandpass", CATrace)


def test_unknown_op_raises():
    registry, _ = create_registry()
    with pytest.raises(KeyError):
        registry.get_op("nonexistent_op")
