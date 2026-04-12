"""AST node dataclasses for the CASI pipeline DSL."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class SourceNode:
    """AST node for a data source."""
    source_type: str            # "mea_trace", "ca_trace", "rtsort"
    source_id: Union[int, str]  # channel/trace index, or "all"

    def cache_key_parts(self) -> Tuple:
        return (self.source_type, self.source_id)


@dataclass
class OpNode:
    """AST node for a chained operation."""
    op_name: str
    kwargs_overrides: Dict[str, Any] = field(default_factory=dict)
    inner_expr: Optional['ExprNode'] = None  # for function-ops like x_corr

    def cache_key_parts(self) -> Tuple:
        inner = self.inner_expr.cache_key_parts() if self.inner_expr else None
        return (self.op_name, tuple(sorted(self.kwargs_overrides.items())), inner)


@dataclass
class ExprNode:
    """AST node for a full expression: source.op1.op2.op3"""
    source: SourceNode
    ops: List[OpNode] = field(default_factory=list)

    def cache_key_parts(self) -> Tuple:
        parts = [self.source.cache_key_parts()]
        for op in self.ops:
            parts.append(op.cache_key_parts())
        return tuple(parts)


@dataclass
class WindowDirective:
    """AST node for window_ms[start, end] or window[full] directive."""
    start_ms: Optional[float] = None
    end_ms: Optional[float] = None
    is_full: bool = False


@dataclass
class OverlayGroup:
    """AST node for [expr1, expr2, ...] overlay groups."""
    expressions: List[ExprNode]


PipelineItem = Union[WindowDirective, ExprNode, OverlayGroup]
