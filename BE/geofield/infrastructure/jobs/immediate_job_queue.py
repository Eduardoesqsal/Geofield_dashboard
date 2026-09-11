"""Cola sincrona para mantener el comportamiento actual."""

from __future__ import annotations

from typing import Callable, TypeVar


T = TypeVar("T")


class ImmediateJobQueue:
    def run(self, name: str, handler: Callable[[], T]) -> T:
        del name
        return handler()
