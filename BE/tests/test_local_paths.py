"""Compatibilidad de rutas de TIFF al ejecutar el backend en Docker."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from geofield.services.local_paths import resolve_upload_path


class LocalUploadPathTests(unittest.TestCase):
    def test_resolves_existing_windows_upload_in_container(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            uploads = Path(directory) / "uploads"
            raster = uploads / "2026-08-14" / "flight.tif"
            raster.parent.mkdir(parents=True)
            raster.write_bytes(b"test")

            saved_path = r"C:\Users\Geo\project\BE\uploads\2026-08-14\flight.tif"
            self.assertEqual(resolve_upload_path(saved_path, uploads), raster.resolve())

    def test_rejects_parent_directory_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            uploads = Path(directory) / "uploads"
            uploads.mkdir()

            with self.assertRaises(ValueError):
                resolve_upload_path(r"C:\project\uploads\..\outside.tif", uploads)

    def test_recovers_misencoded_existing_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            uploads = Path(directory) / "uploads"
            raster = uploads / "2026-09-25" / "Límite.tif"
            raster.parent.mkdir(parents=True)
            raster.write_bytes(b"test")

            saved_path = r"C:\project\uploads\2026-09-25\LÃ­mite.tif"
            self.assertEqual(resolve_upload_path(saved_path, uploads), raster.resolve())


if __name__ == "__main__":
    unittest.main()
