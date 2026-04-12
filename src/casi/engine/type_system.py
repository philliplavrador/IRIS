"""
Type system: operation type transitions and validation.

TYPE_TRANSITIONS is the canonical source of truth for which operations
accept which input types and produce which output types. This is one
of the six touch points when adding a new operation.
"""
from typing import Dict

from casi.engine.types import (
    MEATrace, MEABank, CATrace, RTTrace, RTBank,
    SpikeTrain, SimCalcium, SimCalciumBank,
    CorrelationResult, SpikePCA, Spectrogram,
    FreqPowerTraces, SaturationReport,
    _SpikeBankIntermediate,
)

DataType = type

TYPE_TRANSITIONS: Dict[str, Dict[DataType, DataType]] = {
    "butter_bandpass":     {MEATrace: MEATrace,   MEABank: MEABank},
    "notch_filter":        {MEATrace: MEATrace,   MEABank: MEABank},
    "saturation_mask":     {MEATrace: MEATrace,   MEABank: MEABank},
    "constant_rms":        {MEATrace: SpikeTrain, MEABank: _SpikeBankIntermediate},
    "sliding_rms":         {MEATrace: SpikeTrain, MEABank: _SpikeBankIntermediate},
    "spike_pca":           {SpikeTrain: SpikePCA},
    "spike_curate":        {},  # validated separately (function-op: SpikePCA + CATrace → SpikeTrain)
    "baseline_correction": {CATrace: CATrace},
    "rt_detect":           {MEATrace: RTTrace},
    "sigmoid":             {RTTrace: RTTrace,   RTBank: RTBank},
    "rt_thresh":           {RTTrace: SpikeTrain, RTBank: _SpikeBankIntermediate},
    "gcamp_sim":           {SpikeTrain: SimCalcium, _SpikeBankIntermediate: SimCalciumBank},
    "spectrogram":         {MEATrace: Spectrogram},
    "freq_traces":         {MEATrace: FreqPowerTraces},
    "amp_gain_correction": {MEATrace: MEATrace, MEABank: MEABank},
    "saturation_survey":   {MEABank: SaturationReport},
    "x_corr":              {},  # validated separately
}

# Ops that handle MEABank directly (no per-channel vectorization) despite supporting MEATrace.
DIRECT_BANK_OPS: set = {"saturation_mask"}
