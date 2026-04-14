"""
Type system: operation type transitions and validation.

TYPE_TRANSITIONS is the canonical source of truth for which operations
accept which input types and produce which output types. This is one
of the six touch points when adding a new operation.

Binary (function-op) operations — ``spike_curate`` and ``x_corr`` — use
the left-operand type as the ``input_type`` key and the final output
type as the value. The right-operand type is documented separately in
:data:`BINARY_OP_SIGNATURES`. The executor dispatches these through
``_apply_function_op`` and never calls ``validate_type_transition`` on
them, so the single-input key is descriptive metadata, not a runtime
gate.
"""

from iris.engine.types import (
    CATrace,
    CorrelationResult,
    FreqPowerTraces,
    MEABank,
    MEATrace,
    RTBank,
    RTTrace,
    SaturationReport,
    SimCalcium,
    SimCalciumBank,
    Spectrogram,
    SpikePCA,
    SpikeTrain,
    _SpikeBankIntermediate,
)

DataType = type

TYPE_TRANSITIONS: dict[str, dict[DataType, DataType]] = {
    "butter_bandpass": {MEATrace: MEATrace, MEABank: MEABank},
    "notch_filter": {MEATrace: MEATrace, MEABank: MEABank},
    "saturation_mask": {MEATrace: MEATrace, MEABank: MEABank},
    "constant_rms": {MEATrace: SpikeTrain, MEABank: _SpikeBankIntermediate},
    "sliding_rms": {MEATrace: SpikeTrain, MEABank: _SpikeBankIntermediate},
    "spike_pca": {SpikeTrain: SpikePCA},
    "spike_curate": {SpikePCA: SpikeTrain},  # binary; right operand: CATrace
    "baseline_correction": {CATrace: CATrace},
    "rt_detect": {MEATrace: RTTrace},
    "sigmoid": {RTTrace: RTTrace, RTBank: RTBank},
    "rt_thresh": {RTTrace: SpikeTrain, RTBank: _SpikeBankIntermediate},
    "gcamp_sim": {SpikeTrain: SimCalcium, _SpikeBankIntermediate: SimCalciumBank},
    "spectrogram": {MEATrace: Spectrogram},
    "freq_traces": {MEATrace: FreqPowerTraces},
    "amp_gain_correction": {MEATrace: MEATrace, MEABank: MEABank},
    "saturation_survey": {MEABank: SaturationReport},
    "x_corr": {CATrace: CorrelationResult},  # binary; right operand: SimCalciumBank
}

# Binary ops (function-ops) take a right operand via inner_expr. These are
# dispatched through PipelineExecutor._apply_function_op, not the single-input
# validate_type_transition path. Listed here so the daemon ops route can
# expose the right-operand type alongside the left.
BINARY_OP_SIGNATURES: dict[str, DataType] = {
    "spike_curate": CATrace,
    "x_corr": SimCalciumBank,
}

# Ops that handle MEABank directly (no per-channel vectorization) despite supporting MEATrace.
DIRECT_BANK_OPS: set = {"saturation_mask"}
