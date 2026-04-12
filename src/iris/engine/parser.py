"""DSL parser for the IRIS pipeline configuration language."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Union

from iris.engine.ast import (
    ExprNode, OpNode, OverlayGroup, PipelineItem, SourceNode, WindowDirective,
)


class DSLParser:
    """Parse pipeline_cfg DSL strings into AST nodes."""

    _WINDOW_RE = re.compile(
        r'^window_ms\[\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\]$'
    )
    _WINDOW_FULL_RE = re.compile(
        r'^window_ms\[full\]$'
    )
    _SOURCE_RE = re.compile(
        r'^(mea_trace|ca_trace|rtsort)\(([^)]+)\)$'
    )

    def parse_pipeline(self, pipeline_cfg: List) -> List[PipelineItem]:
        items: List[PipelineItem] = []
        for entry in pipeline_cfg:
            if isinstance(entry, list):
                exprs = [self._parse_expression(e) for e in entry]
                items.append(OverlayGroup(expressions=exprs))
            elif isinstance(entry, str):
                items.append(self._parse_string(entry))
            else:
                raise ValueError(f"Invalid pipeline entry type: {type(entry)}")
        return items

    def _parse_string(self, s: str) -> PipelineItem:
        s = s.strip()
        m = self._WINDOW_RE.match(s)
        if m:
            return WindowDirective(start_ms=float(m.group(1)), end_ms=float(m.group(2)))
        m = self._WINDOW_FULL_RE.match(s)
        if m:
            return WindowDirective(is_full=True)
        return self._parse_expression(s)

    def _parse_expression(self, s: str) -> ExprNode:
        s = s.strip()
        tokens = self._tokenize_dotchain(s)
        if not tokens:
            raise ValueError(f"Empty expression: '{s}'")
        source = self._parse_source_token(tokens[0])
        ops = [self._parse_op_token(tok) for tok in tokens[1:]]
        return ExprNode(source=source, ops=ops)

    def _tokenize_dotchain(self, s: str) -> List[str]:
        """Split on dots, respecting parenthesis nesting."""
        tokens = []
        current: List[str] = []
        depth = 0

        for ch in s:
            if ch == '(':
                depth += 1
                current.append(ch)
            elif ch == ')':
                depth -= 1
                current.append(ch)
            elif ch == '.' and depth == 0:
                token = ''.join(current).strip()
                if token:
                    tokens.append(token)
                current = []
            else:
                current.append(ch)

        token = ''.join(current).strip()
        if token:
            tokens.append(token)
        return tokens

    def _parse_source_token(self, token: str) -> SourceNode:
        m = self._SOURCE_RE.match(token)
        if not m:
            raise ValueError(
                f"Invalid source token: '{token}'. "
                f"Expected mea_trace(N), ca_trace(N), rtsort(N), or mea_trace(all)."
            )
        source_type = m.group(1)
        id_str = m.group(2).strip()
        if id_str == 'all':
            source_id: Union[int, str] = 'all'
        else:
            try:
                source_id = int(id_str)
            except ValueError:
                raise ValueError(f"Source ID must be int or 'all', got: '{id_str}'")
        return SourceNode(source_type=source_type, source_id=source_id)

    def _parse_op_token(self, token: str) -> OpNode:
        paren_idx = token.find('(')
        if paren_idx == -1:
            return OpNode(op_name=token)

        op_name = token[:paren_idx]
        inner = self._extract_paren_content(token, paren_idx)

        if self._is_kwargs(inner):
            kwargs = self._parse_kwargs(inner)
            return OpNode(op_name=op_name, kwargs_overrides=kwargs)
        else:
            inner_expr = self._parse_expression(inner)
            return OpNode(op_name=op_name, inner_expr=inner_expr)

    def _extract_paren_content(self, token: str, open_idx: int) -> str:
        depth = 0
        for i in range(open_idx, len(token)):
            if token[i] == '(':
                depth += 1
            elif token[i] == ')':
                depth -= 1
                if depth == 0:
                    return token[open_idx + 1:i]
        raise ValueError(f"Unmatched parenthesis in: '{token}'")

    def _is_kwargs(self, inner: str) -> bool:
        """If inner contains '=' at parenthesis depth 0, it's kwargs."""
        depth = 0
        for ch in inner:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == '=' and depth == 0:
                return True
        return False

    def _parse_kwargs(self, inner: str) -> Dict[str, Any]:
        parts = self._split_top_level(inner, ',')
        kwargs: Dict[str, Any] = {}
        for part in parts:
            part = part.strip()
            if '=' not in part:
                raise ValueError(f"Expected key=value, got: '{part}'")
            key, val_str = part.split('=', 1)
            kwargs[key.strip()] = self._parse_value(val_str.strip())
        return kwargs

    def _split_top_level(self, s: str, delimiter: str) -> List[str]:
        parts: List[str] = []
        current: List[str] = []
        depth = 0
        for ch in s:
            if ch in '([':
                depth += 1
            elif ch in ')]':
                depth -= 1
            if ch == delimiter and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(ch)
        if current:
            parts.append(''.join(current))
        return parts

    def _parse_value(self, val_str: str) -> Any:
        val_str = val_str.strip()

        # Parse list literals like [1, 2, 3]
        if val_str.startswith('[') and val_str.endswith(']'):
            inner = val_str[1:-1].strip()
            if not inner:
                return []
            elements = self._split_top_level(inner, ',')
            return [self._parse_value(elem.strip()) for elem in elements]

        try:
            return int(val_str)
        except ValueError:
            pass
        try:
            return float(val_str)
        except ValueError:
            pass
        if val_str.lower() == 'true':
            return True
        if val_str.lower() == 'false':
            return False
        if val_str.lower() == 'none':
            return None
        if (val_str.startswith('"') and val_str.endswith('"')) or \
           (val_str.startswith("'") and val_str.endswith("'")):
            return val_str[1:-1]
        return val_str
