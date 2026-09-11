"""Contrato para almacenamiento de artefactos generados.

El proyecto sigue usando filesystem local. Este puerto existe para que los
casos de uso futuros no dependan directamente de rutas locales.
"""

from __future__ import annotations

from typing import Protocol


class ArtifactStorage(Protocol):
    def exists(self, key: str) -> bool:
        ...

    def read_bytes(self, key: str) -> bytes:
        ...

    def write_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> str:
        ...

    def public_url(self, key: str) -> str:
        ...
