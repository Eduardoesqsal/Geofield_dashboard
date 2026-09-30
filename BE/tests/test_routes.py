"""Pruebas de contrato para rutas FastAPI críticas del backend."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from geofield.api.routes import create_router


class FakeRasterService:
    def __init__(self, active_path: Path) -> None:
        self.active_path: Path | None = active_path
        self.active_context = None
        self.sensor: str | None = "mavic3m"
        self.rgb_stretch: tuple[float, float] | None = (1.0, 2.0)
        self.overlay: tuple[int, int, object] | None = (10, 10, object())
        self.crop_geometries: dict[str, Any] = {"crop-1": object()}


class FakeSupabaseService:
    def __init__(self, record: dict[str, Any], cache_dir: Path) -> None:
        self.record = record
        self.settings = type(
            "Settings",
            (),
            {
                "artifact_storage_bucket": "artifacts",
                "artifact_storage_mode": "local",
                "cache_dir": cache_dir,
            },
        )()
        self.created_rois: list[dict[str, Any]] = []
        self.saved_roi_analyses: list[dict[str, Any]] = []
        self.activated_orthomosaic_ids: list[str] = []
        self.detections: dict[str, Any] | None = None
        self.roi_record: dict[str, Any] = {
            "id": "roi-1",
            "geojson": {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-107.0, 24.0],
                            [-106.9, 24.0],
                            [-106.9, 24.1],
                            [-107.0, 24.1],
                            [-107.0, 24.0],
                        ],
                    ],
                },
                "properties": {},
            },
        }

    def list_orthomosaics(
        self,
        _limit: int = 500,
        _cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [self.record]

    def get_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        if orthomosaic_id != self.record["id"]:
            raise KeyError(orthomosaic_id)
        return self.record

    def get_detections(self, orthomosaic_id: str) -> dict[str, Any] | None:
        return self.detections if orthomosaic_id == self.record["id"] else None

    def list_detections(self, _cycle_id: str | None = None) -> list[dict[str, Any]]:
        if not self.detections:
            return []
        return [{key: value for key, value in self.detections.items() if key != "geojson"}]

    def delete_detections(self, _orthomosaic_id: str) -> None:
        self.detections = None

    def save_detections(self, orthomosaic_id: str, geojson: dict[str, Any]) -> dict[str, Any]:
        self.detections = {
            "orthomosaic_id": orthomosaic_id,
            "geojson": geojson,
            "feature_count": len(geojson["features"]),
            "updated_at": "2026-09-30T00:00:00Z",
        }
        return self.detections

    def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        return self.record

    def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, Any]:
        return {
            "cycle": {"id": cycle_id, "name": "Ciclo prueba"},
            "orthomosaics": [self.record],
            "deleted_orthomosaics": 1,
            "deleted_rois": 2,
        }

    def activate_orthomosaic(
        self,
        orthomosaic_id: str,
        _raster: FakeRasterService,
    ) -> dict[str, Any]:
        self.activated_orthomosaic_ids.append(orthomosaic_id)
        return self.record

    def create_roi(
        self,
        name: str,
        geojson: dict[str, Any],
        orthomosaic_id: str | None,
        agricultural_cycle_id: str | None,
    ) -> dict[str, Any]:
        roi = {
            "id": "roi-1",
            "name": name,
            "geojson": geojson,
            "orthomosaic_id": orthomosaic_id,
            "agricultural_cycle_id": agricultural_cycle_id,
        }
        self.created_rois.append(roi)
        return roi

    def get_roi(self, roi_id: str) -> dict[str, Any]:
        if roi_id != self.roi_record["id"]:
            raise KeyError(roi_id)
        return self.roi_record

    def save_roi_analysis(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "id": "analysis-1",
            "roi_id": roi_id,
            "orthomosaic_id": orthomosaic_id,
            "ndvi": stats if index_type == "NDVI" else None,
            "ndwi": stats if index_type == "NDWI" else None,
            "ndre": stats if index_type == "NDRE" else None,
            "created_at": "2026-09-11T00:00:00Z",
            "orthomosaics": {"name": "Vuelo 1", "capture_date": "2026-09-11"},
        }
        self.saved_roi_analyses.append(record)
        return record


class FakeArtifactStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.read_keys: list[str] = []

    def exists(self, key: str) -> bool:
        return key in self.objects

    def read_bytes(self, key: str) -> bytes:
        self.read_keys.append(key)
        return self.objects[key]

    def write_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> str:
        self.objects[key] = content
        return self.public_url(key)

    def public_url(self, key: str) -> str:
        return f"https://storage.example/{key}"


class FakePublicationRepository:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def healthcheck(self) -> dict[str, Any]:
        return {"database": "fake-neon", "ok": True}

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        return {
            "status": "published",
            "publication_id": "publication-1",
            "payload_hash": payload["analysis"]["payload_hash"],
        }

    def delete(self, source_publication_key: str) -> dict[str, Any]:
        return {
            "status": "deleted",
            "source_publication_key": source_publication_key,
            "deleted": True,
        }


class RoutesDeleteOrthomosaicTests(unittest.TestCase):
    def test_deleting_cycle_resets_its_active_orthomosaic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster_path = root / "active.tif"
            raster_path.write_bytes(b"fake-raster")
            raster = FakeRasterService(raster_path)
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(raster_path)},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).delete("/agricultural_cycles/cycle-1")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["deleted_orthomosaics"], 1)
            self.assertEqual(response.json()["deleted_rois"], 2)
            self.assertIsNone(raster.active_path)

    def test_deleting_active_orthomosaic_resets_raster_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster_path = root / "active.tif"
            raster_path.write_bytes(b"fake-raster")

            raster = FakeRasterService(raster_path)
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(raster_path)},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).delete("/orthomosaics/ortho-1")

            self.assertEqual(response.status_code, 200)
            self.assertIsNone(raster.active_path)
            self.assertIsNone(raster.sensor)
            self.assertIsNone(raster.rgb_stretch)
            self.assertIsNone(raster.overlay)
            self.assertEqual(raster.crop_geometries, {})


class RoutesRoiContractTests(unittest.TestCase):
    def test_storage_health_reports_configured_artifact_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster = FakeRasterService(root / "active.tif")
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(root / "active.tif")},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).get("/storage/health")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")
            self.assertEqual(response.json()["mode"], "local")


class RoutesPublicationTests(unittest.TestCase):
    def test_publications_health_reports_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            app = FastAPI()
            app.include_router(
                create_router(
                    FakeRasterService(root / "active.tif"),
                    root,
                    root,
                    FakeSupabaseService({"id": "ortho-1", "file_path": str(root / "active.tif")}, root / "cache"),
                ),  # type: ignore[arg-type]
            )

            response = TestClient(app).get("/publications/health")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "not_configured")

    def test_publish_results_uses_publication_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = FakePublicationRepository()
            app = FastAPI()
            app.include_router(
                create_router(
                    FakeRasterService(root / "active.tif"),
                    root,
                    root,
                    FakeSupabaseService({"id": "ortho-1", "file_path": str(root / "active.tif")}, root / "cache"),
                    publication_repository=repository,
                ),  # type: ignore[arg-type]
            )

            response = TestClient(app).post(
                "/publications",
                json={
                    "project": {"name": "Lote demo"},
                    "analysis": {
                        "source_publication_key": "ortho-1:roi-1:prescription-1",
                        "analysis_type": "roi_prescription",
                    },
                    "roi": {
                        "geometry_geojson": {"type": "Polygon", "coordinates": []},
                    },
                    "indices": [
                        {
                            "index_name": "NDVI",
                            "stats": {"count": 1, "mean": 0.5},
                        },
                    ],
                },
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["publication"]["status"], "published")
            self.assertEqual(len(repository.payloads), 1)
            self.assertRegex(repository.payloads[0]["analysis"]["payload_hash"], r"^[a-f0-9]{64}$")

    def test_delete_publication_uses_publication_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = FakePublicationRepository()
            app = FastAPI()
            app.include_router(
                create_router(
                    FakeRasterService(root / "active.tif"),
                    root,
                    root,
                    FakeSupabaseService({"id": "ortho-1", "file_path": str(root / "active.tif")}, root / "cache"),
                    publication_repository=repository,
                ),  # type: ignore[arg-type]
            )

            response = TestClient(app).delete("/publications/ortho-1%3Aroi-1%3Aindices")

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["publication"]["deleted"])

    def test_create_roi_accepts_feature_collection_and_forwards_cycle_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster = FakeRasterService(root / "active.tif")
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(root / "active.tif")},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]
            payload = {
                "name": "Lote norte",
                "orthomosaic_id": "ortho-1",
                "cycle_id": "cycle-1",
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [-107.0, 24.0],
                                        [-106.9, 24.0],
                                        [-106.9, 24.1],
                                        [-107.0, 24.1],
                                        [-107.0, 24.0],
                                    ],
                                ],
                            },
                            "properties": {},
                        },
                    ],
                },
            }

            response = TestClient(app).post("/rois", json=payload)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["roi"]["name"], "Lote norte")
            self.assertEqual(supabase.created_rois[0]["agricultural_cycle_id"], "cycle-1")

    def test_save_roi_analysis_activates_orthomosaic_and_normalizes_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster = FakeRasterService(root / "active.tif")
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(root / "active.tif")},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).post(
                "/rois/roi-1/analyses",
                json={
                    "orthomosaic_id": "ortho-1",
                    "index": "ndvi",
                    "stats": {
                        "count": "12",
                        "min": "-0.1",
                        "max": "0.8",
                        "mean": "0.45",
                        "median": "0.44",
                        "standard_deviation": "0.12",
                        "p10": "0.1",
                        "p25": "0.2",
                        "p75": "0.6",
                        "p90": "0.7",
                        "range_min": "-0.2",
                        "range_max": "0.9",
                    },
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(supabase.activated_orthomosaic_ids, ["ortho-1"])
            saved = supabase.saved_roi_analyses[0]["ndvi"]
            self.assertEqual(saved["count"], 12)
            self.assertEqual(saved["mean"], 0.45)
            self.assertEqual(saved["range_max"], 0.9)

    def test_save_roi_analysis_requires_orthomosaic_id_before_loading_roi(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster = FakeRasterService(root / "active.tif")
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(root / "active.tif")},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).post(
                "/rois/roi-1/analyses",
                json={"index": "NDVI", "stats": {"count": 1}},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(supabase.activated_orthomosaic_ids, [])
            self.assertEqual(supabase.saved_roi_analyses, [])

    def test_zoning_rejects_non_numeric_grid_payload_before_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster = FakeRasterService(root / "active.tif")
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(root / "active.tif")},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).post(
                "/ndvi_zoning",
                json={
                    "orthomosaic_id": "ortho-1",
                    "zone_count": "cuatro",
                    "geojson": supabase.roi_record["geojson"],
                },
            )

            self.assertEqual(response.status_code, 422)
            self.assertIn("Zonas", response.json()["detail"])
            self.assertEqual(supabase.activated_orthomosaic_ids, [])

    def test_download_prescription_json_uses_local_artifact_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifact_id = "a" * 32
            prescription_dir = root / "prescriptions"
            prescription_dir.mkdir(parents=True)
            (prescription_dir / f"{artifact_id}.json").write_text(
                '{"status":"ok"}',
                encoding="utf-8",
            )
            raster = FakeRasterService(root / "active.tif")
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(root / "active.tif")},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).get(
                f"/prescriptions/{artifact_id}/download.json",
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})
            self.assertIn(
                f'filename="prescripcion_{artifact_id[:8]}.json"',
                response.headers["content-disposition"],
            )

    def test_download_prescription_json_uses_injected_artifact_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifact_id = "b" * 32
            key = f"prescriptions/{artifact_id}.json"
            artifacts = FakeArtifactStorage({key: b'{"source":"storage"}'})
            raster = FakeRasterService(root / "active.tif")
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(root / "active.tif")},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(
                create_router(
                    raster,
                    root,
                    root,
                    supabase,  # type: ignore[arg-type]
                    artifacts,
                ),
            )

            response = TestClient(app).get(
                f"/prescriptions/{artifact_id}/download.json",
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"source": "storage"})
            self.assertEqual(artifacts.read_keys, [key])


class RoutesDetectionTests(unittest.TestCase):
    def test_missing_detection_table_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            supabase = FakeSupabaseService({"id": "ortho-1"}, root / "cache")

            def missing_table(_cycle_id: str | None = None) -> list[dict[str, Any]]:
                raise RuntimeError("PGRST205: public.tree_detection_sets missing")

            supabase.list_detections = missing_table  # type: ignore[method-assign]
            app = FastAPI()
            app.include_router(create_router(FakeRasterService(root / "active.tif"), root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).get("/detections")
            self.assertEqual(response.status_code, 503)
            self.assertIn("006_create_tree_detection_sets.sql", response.json()["detail"])

    def test_save_and_reload_detections_for_orthomosaic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            supabase = FakeSupabaseService({"id": "ortho-1"}, root / "cache")
            app = FastAPI()
            app.include_router(
                create_router(FakeRasterService(root / "active.tif"), root, root, supabase),  # type: ignore[arg-type]
            )
            collection = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-107.0, 24.0]},
                    "properties": {"diameter_m": 2.5},
                }],
            }
            client = TestClient(app)
            saved = client.put("/orthomosaics/ortho-1/detections", json={"geojson": collection})
            loaded = client.get("/orthomosaics/ortho-1/detections")
            listed = client.get("/detections?cycle_id=cycle-1")

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["feature_count"], 1)
            self.assertEqual(loaded.status_code, 200)
            self.assertEqual(loaded.json()["detections"]["geojson"], collection)
            self.assertEqual(listed.json()["items"][0]["feature_count"], 1)
            self.assertNotIn("geojson", listed.json()["items"][0])

            deleted = client.delete("/orthomosaics/ortho-1/detections")
            self.assertEqual(deleted.status_code, 200)
            self.assertIsNone(client.get("/orthomosaics/ortho-1/detections").json()["detections"])


if __name__ == "__main__":
    unittest.main()
