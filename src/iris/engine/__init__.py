"""
IRIS engine package.

Public API re-exported from submodules. All callers (CLI, daemon, tests,
plot backends) should import from ``iris.engine`` — never from the
individual submodules directly (those are implementation details).
"""
# Types
from iris.engine.types import (  # noqa: F401
    PipelineContext,
    MEATrace, MEABank, CATrace, RTTrace, RTBank,
    SpikeTrain, SimCalcium, SimCalciumBank,
    CorrelationResult, SpikePCA, Spectrogram,
    FreqPowerTraces, SaturationReport,
    _SpikeBankIntermediate,
)

# Type system
from iris.engine.type_system import (  # noqa: F401
    DataType, TYPE_TRANSITIONS, DIRECT_BANK_OPS,
)

# Registry
from iris.engine.registry import OpRegistry  # noqa: F401

# AST
from iris.engine.ast import (  # noqa: F401
    SourceNode, OpNode, ExprNode, WindowDirective, OverlayGroup,
    PipelineItem,
)

# Parser
from iris.engine.parser import DSLParser  # noqa: F401

# Cache
from iris.engine.cache import PipelineCache  # noqa: F401

# Executor
from iris.engine.executor import PipelineExecutor, run_pipeline  # noqa: F401

# Loaders
from iris.engine.loaders import (  # noqa: F401
    load_mea_trace, load_ca_trace, load_rtsort,
    get_recording_duration_ms,
    clear_data_caches, clear_pipeline_cache,
)

# Factory
from iris.engine.factory import create_registry  # noqa: F401
