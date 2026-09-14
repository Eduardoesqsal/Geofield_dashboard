"""Contrato para futuras publicaciones hacia dashboard externo."""

from __future__ import annotations

from typing import Any, Protocol


class PublicationRepository(Protocol):
    def list(self, source_project_id: str | None = None) -> list[dict[str, Any]]:
        ...

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def delete(self, source_publication_key: str) -> dict[str, Any]:
        ...

    def healthcheck(self) -> dict[str, Any]:
        ...

