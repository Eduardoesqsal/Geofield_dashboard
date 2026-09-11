"""Storage local compatible con los artefactos actuales."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


class LocalArtifactStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        normalized = PurePosixPath(key)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("La ruta del artefacto no es valida.")
        path = (self.root / Path(*normalized.parts)).resolve()
        path.relative_to(self.root)
        return path

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def read_bytes(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def write_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> str:
        del content_type
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return self.public_url(key)

    def public_url(self, key: str) -> str:
        normalized = PurePosixPath(key)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("La ruta del artefacto no es valida.")
        return f"/static/{normalized.as_posix()}"

