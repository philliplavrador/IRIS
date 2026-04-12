"""Op registry: maps op names to handler functions and their type signatures."""
from __future__ import annotations

from typing import Callable, Dict, Optional

from iris.engine.type_system import TYPE_TRANSITIONS, DataType


class OpRegistry:
    """Registry mapping op names to handler functions and their type signatures."""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._margin_calculators: Dict[str, Callable] = {}
        self._plot_handlers: Dict[DataType, Callable] = {}
        self._overlay_plot_handler: Optional[Callable] = None

    def register_op(self, name: str, handler: Callable) -> None:
        if name not in TYPE_TRANSITIONS:
            raise ValueError(
                f"Unknown op name '{name}'. Valid ops: {list(TYPE_TRANSITIONS.keys())}"
            )
        self._handlers[name] = handler

    def register_margin_calculator(self, name: str, calculator: Callable) -> None:
        self._margin_calculators[name] = calculator

    def register_plot(self, data_type: DataType, handler: Callable) -> None:
        self._plot_handlers[data_type] = handler

    def register_overlay_plot(self, handler: Callable) -> None:
        self._overlay_plot_handler = handler

    def get_op(self, name: str) -> Callable:
        if name not in self._handlers:
            available = list(self._handlers.keys())
            raise KeyError(
                f"No handler registered for op '{name}'. "
                f"Registered ops: {available}"
            )
        return self._handlers[name]

    def get_margin_calculator(self, name: str) -> Optional[Callable]:
        return self._margin_calculators.get(name)

    def get_plot(self, data_type: DataType) -> Optional[Callable]:
        return self._plot_handlers.get(data_type)

    def get_overlay_plot(self) -> Optional[Callable]:
        return self._overlay_plot_handler

    def validate_type_transition(self, op_name: str, input_type: DataType) -> DataType:
        transitions = TYPE_TRANSITIONS.get(op_name, {})
        if input_type not in transitions:
            valid = [t.__name__ for t in transitions.keys()]
            raise TypeError(
                f"Op '{op_name}' cannot accept input type '{input_type.__name__}'. "
                f"Valid input types: {valid}"
            )
        return transitions[input_type]
