"""Resuelve rutas de ortomosaicos al usar los mismos archivos desde Docker."""

from __future__ import annotations

from pathlib import Path


def resolve_upload_path(saved_path: str, uploads_dir: Path) -> Path:
    """Acepta rutas absolutas antiguas de Windows y rutas del contenedor."""
    original = Path(saved_path)
    if original.is_file():
        return original.resolve()

    parts = saved_path.replace("\\", "/").split("/")
    upload_positions = [i for i, part in enumerate(parts) if part.lower() == "uploads"]
    if not upload_positions:
        return original.resolve()

    relative_parts = parts[upload_positions[-1] + 1 :]
    if not relative_parts or any(part in {"", ".", ".."} for part in relative_parts):
        raise ValueError("La ruta del ortomosaico no es valida.")

    root = uploads_dir.resolve()
    candidate = root.joinpath(*relative_parts).resolve()
    candidate.relative_to(root)
    if not candidate.is_file() and "Ã" in saved_path:
        try:
            repaired_parts = [part.encode("latin-1").decode("utf-8") for part in relative_parts]
        except UnicodeError:
            pass
        else:
            repaired = root.joinpath(*repaired_parts).resolve()
            repaired.relative_to(root)
            if repaired.is_file():
                return repaired
    return candidate
