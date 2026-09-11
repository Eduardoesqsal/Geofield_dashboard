"""Contrato para ejecutar trabajos de aplicacion."""

from __future__ import annotations

from typing import Callable, Protocol, TypeVar


T = TypeVar("T")


class JobQueue(Protocol):
    def run(self, name: str, handler: Callable[[], T]) -> T:
        ...
