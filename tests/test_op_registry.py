"""Op registry + type-transition tests."""
from __future__ import annotations

import pytest

from casi.engine import (
    CATrace,
    FreqPowerTraces,
    MEABank,
    MEATrace,
    OpRegistry,
    RTBank,
    RTTrace,
    SaturationReport,
    SimCalcium,
    SimCalciumBank,
    SpikePCA,
    SpikeTrain,
    Spectrogram,
    TYPE_TRANSITIONS,
    _SpikeBankIntermediate,
    create_registry,
)


def test_create_registry_default_backend():
    registry, source_loaders = create_registry()
    assert isinstance(registry, OpRegistry)
    assert set(source_loaders) == {"mea_trace", "ca_trace", "rtsort"}
    # All 17 ops + 1 overlay handler + 11 plot handlers + 2 margin calculators
    assert len(registry._handlers) == 17
    assert len(registry._plot_handlers) == 11
    assert registry._overlay_plot_handler is not None


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
