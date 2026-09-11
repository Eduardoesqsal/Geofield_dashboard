"""Contrato para futuras publicaciones hacia dashboard externo."""

from __future__ import annotations

from typing import Any, Protocol


class PublicationRepository(Protocol):
    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

