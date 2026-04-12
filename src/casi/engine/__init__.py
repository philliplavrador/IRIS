"""
CASI engine package.

This package wraps the original engine module (now engine_monolith.py)
and provides the same public API. New code should import types from
engine.types and engine.type_system; the monolith re-exports are for
backward compatibility.

The full split (moving ops, parser, cache, executor out of the monolith)
is tracked in the refactor plan and will proceed incrementally.
"""
# Re-export everything from the monolith
from casi.engine_monolith import *  # noqa: F401, F403
from casi.engine_monolith import (  # noqa: F401 — explicit re-exports for type checkers
    PipelineContext,
    MEATrace, MEABank, CATrace, RTTrace, RTBank,
    SpikeTrain, SimCalcium, SimCalciumBank,
    CorrelationResult, SpikePCA, Spectrogram,
    FreqPowerTraces, SaturationReport,
    _SpikeBankIntermediate,
    DataType, TYPE_TRANSITIONS, DIRECT_BANK_OPS,
    OpRegistry,
    SourceNode, OpNode, ExprNode, WindowDirective, OverlayGroup,
    DSLParser,
    PipelineCache,
    PipelineExecutor,
    run_pipeline,
    load_mea_trace, load_ca_trace, load_rtsort,
    get_recording_duration_ms,
    clear_data_caches, clear_pipeline_cache,
    create_registry,
)
