"""Pruebas de storage de artefactos."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geofield.config import Settings
from geofield.application.use_cases import PublishJsonArtifactUseCase
from geofield.infrastructure.storage import LocalArtifactStorage, create_artifact_storage


class LocalArtifactStorageTests(unittest.TestCase):
    def test_write_read_exists_and_public_url_use_local_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            storage = LocalArtifactStorage(root)

            url = storage.write_bytes(
                "prescriptions/artifact.json",
                b'{"status":"ok"}',
                "application/json",
            )

            self.assertEqual(url, "/static/prescriptions/artifact.json")
            self.assertTrue(storage.exists("prescriptions/artifact.json"))
            self.assertEqual(
                storage.read_bytes("prescriptions/artifact.json"),
                b'{"status":"ok"}',
            )

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = LocalArtifactStorage(Path(temporary_directory))

            with self.assertRaisesRegex(ValueError, "artefacto no es valida"):
                storage.read_bytes("../secret.txt")


class ArtifactStorageFactoryTests(unittest.TestCase):
    def test_local_mode_creates_local_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings = Settings(
                base_dir=Path(temporary_directory),
                output_dir=Path(temporary_directory) / "static",
                cache_dir=Path(temporary_directory) / "cache",
                uploads_dir=Path(temporary_directory) / "uploads",
                artifact_storage_mode="local",
            )

            storage = create_artifact_storage(settings)

            self.assertIsInstance(storage, LocalArtifactStorage)

    def test_supabase_mode_requires_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings = Settings(
                base_dir=Path(temporary_directory),
                output_dir=Path(temporary_directory) / "static",
                cache_dir=Path(temporary_directory) / "cache",
                uploads_dir=Path(temporary_directory) / "uploads",
                artifact_storage_mode="supabase",
            )

            with self.assertRaisesRegex(ValueError, "requiere un cliente"):
                create_artifact_storage(settings)


class PublishJsonArtifactUseCaseTests(unittest.TestCase):
    def test_publish_json_serializes_to_storage_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = LocalArtifactStorage(Path(temporary_directory))

            url = PublishJsonArtifactUseCase(storage).execute(
                "exports/result.json",
                {"status": "ok", "items": [1, 2]},
            )

            self.assertEqual(url, "/static/exports/result.json")
            self.assertEqual(
                storage.read_bytes("exports/result.json"),
                b'{"status":"ok","items":[1,2]}',
            )


if __name__ == "__main__":
    unittest.main()
