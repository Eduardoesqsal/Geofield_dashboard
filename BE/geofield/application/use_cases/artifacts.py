"""Casos de uso pequenos para publicar artefactos generados."""

from __future__ import annotations

import json
from typing import Any

from geofield.application.ports import ArtifactStorage


class PublishJsonArtifactUseCase:
    """Publica JSON con serializacion consistente y storage intercambiable."""

    def __init__(self, storage: ArtifactStorage) -> None:
        self.storage = storage

    def execute(self, key: str, payload: dict[str, Any]) -> str:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.storage.write_bytes(key, content, "application/json")
