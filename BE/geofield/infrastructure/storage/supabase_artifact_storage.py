"""Adaptador preparado para Supabase Storage.

No se usa por defecto. Existe para que activar Supabase Storage mas adelante
sea una decision de configuracion y no una reescritura de casos de uso.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from supabase import Client


class SupabaseArtifactStorage:
    def __init__(self, client: Client, bucket: str, prefix: str = "artifacts") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        normalized = PurePosixPath(key)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("La ruta del artefacto no es valida.")
        path = normalized.as_posix()
        return f"{self.prefix}/{path}" if self.prefix else path

    def exists(self, key: str) -> bool:
        try:
            self.client.storage.from_(self.bucket).download(self._key(key))
            return True
        except Exception:
            return False

    def read_bytes(self, key: str) -> bytes:
        return self.client.storage.from_(self.bucket).download(self._key(key))

    def write_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> str:
        options: dict[str, str] = {"upsert": "true"}
        if content_type:
            options["content-type"] = content_type
        storage_key = self._key(key)
        self.client.storage.from_(self.bucket).upload(
            storage_key,
            content,
            options,
        )
        return self.public_url(key)

    def public_url(self, key: str) -> str:
        return self.client.storage.from_(self.bucket).get_public_url(self._key(key))
