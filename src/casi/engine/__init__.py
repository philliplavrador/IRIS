"""
CASI engine package.

Public API re-exported from submodules. All callers (CLI, daemon, tests,
plot backends) should import from ``casi.engine`` — never from the
individual submodules directly (those are implementation details).
"""
# Types
from casi.engine.types import (  # noqa: F401
    PipelineContext,
    MEATrace, MEABank, CATrace, RTTrace, RTBank,
    SpikeTrain, SimCalcium, SimCalciumBank,
    CorrelationResult, SpikePCA, Spectrogram,
    FreqPowerTraces, SaturationReport,
    _SpikeBankIntermediate,
)

# Type system
from casi.engine.type_system import (  # noqa: F401
    DataType, TYPE_TRANSITIONS, DIRECT_BANK_OPS,
)

# Registry
from casi.engine.registry import OpRegistry  # noqa: F401

# AST
from casi.engine.ast import (  # noqa: F401
    SourceNode, OpNode, ExprNode, WindowDirective, OverlayGroup,
    PipelineItem,
)

# Parser
from casi.engine.parser import DSLParser  # noqa: F401

# Cache
from casi.engine.cache import PipelineCache  # noqa: F401

# Executor
from casi.engine.executor import PipelineExecutor, run_pipeline  # noqa: F401

# Loaders
from casi.engine.loaders import (  # noqa: F401
    load_mea_trace, load_ca_trace, load_rtsort,
    get_recording_duration_ms,
    clear_data_caches, clear_pipeline_cache,
)

# Factory
from casi.engine.factory import create_registry  # noqa: F401
