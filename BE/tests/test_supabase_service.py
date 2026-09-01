"""Pruebas de normalización del historial persistido en Supabase."""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from geofield.services.supabase_service import SupabaseService
from geofield.services.application_service import OrthomosaicApplicationService


class SupabaseHistoryTests(unittest.TestCase):
    def test_delete_orthomosaic_resets_active_raster_before_file_deletion(self) -> None:
        call_order: list[str] = []

        class Persistence:
            settings = SimpleNamespace(cache_dir=Path("cache"))

            def get_orthomosaic(self, orthomosaic_id: str) -> dict[str, object]:
                call_order.append(f"get:{orthomosaic_id}")
                return {
                    "id": orthomosaic_id,
                    "file_path": "C:/uploads/flight-1.tif",
                    "original_filename": "flight-1.tif",
                }

            def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, object]:
                call_order.append(f"delete:{orthomosaic_id}")
                return {"id": orthomosaic_id}

        raster = SimpleNamespace(
            active_path=Path("C:/uploads/flight-1.tif"),
            sensor="rgb",
            rgb_stretch=(1.0, 2.0),
            overlay=("overlay",),
            crop_geometries={"crop-1": object()},
        )
        service = OrthomosaicApplicationService(raster, Persistence())  # type: ignore[arg-type]

        result = service.delete_orthomosaic("flight-1")

        self.assertEqual(result["id"], "flight-1")
        self.assertEqual(call_order, ["get:flight-1", "delete:flight-1"])
        self.assertIsNone(raster.active_path)
        self.assertIsNone(raster.sensor)
        self.assertIsNone(raster.rgb_stretch)
        self.assertIsNone(raster.overlay)
        self.assertEqual(raster.crop_geometries, {})

    def test_delete_agricultural_cycle_resets_active_rasters_before_deletion(self) -> None:
        call_order: list[str] = []
        cycle_orthomosaics = [
            {
                "id": "flight-1",
                "file_path": "C:/uploads/flight-1.tif",
                "original_filename": "flight-1.tif",
            },
            {
                "id": "flight-2",
                "file_path": "C:/uploads/flight-2.tif",
                "original_filename": "flight-2.tif",
            },
        ]

        class Persistence:
            settings = SimpleNamespace(cache_dir=Path("cache"))

            def list_orthomosaics(
                self,
                _limit: int = 500,
                _cycle_id: str | None = None,
            ) -> list[dict[str, object]]:
                call_order.append("list")
                return cycle_orthomosaics

            def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, object]:
                call_order.append(f"delete:{cycle_id}")
                return {
                    "cycle": {"id": cycle_id},
                    "orthomosaics": cycle_orthomosaics,
                    "deleted_orthomosaics": len(cycle_orthomosaics),
                    "deleted_rois": 0,
                }

        raster = SimpleNamespace(
            active_path=Path("C:/uploads/flight-2.tif"),
            sensor="rgb",
            rgb_stretch=(1.0, 2.0),
            overlay=("overlay",),
            crop_geometries={"crop-1": object()},
        )
        service = OrthomosaicApplicationService(raster, Persistence())  # type: ignore[arg-type]

        result = service.delete_agricultural_cycle("cycle-1")

        self.assertEqual(result["cycle"]["id"], "cycle-1")
        self.assertEqual(call_order, ["list", "delete:cycle-1"])
        self.assertIsNone(raster.active_path)
        self.assertIsNone(raster.sensor)
        self.assertIsNone(raster.rgb_stretch)
        self.assertIsNone(raster.overlay)
        self.assertEqual(raster.crop_geometries, {})

    def test_ensure_zone_for_roi_prefers_explicit_roi_id_column(self) -> None:
        class Query:
            def __init__(self, table_name: str) -> None:
                self.table_name = table_name
                self.filters: dict[str, object] = {}

            def select(self, _columns: str) -> "Query":
                return self

            def eq(self, field: str, value: object) -> "Query":
                self.filters[field] = value
                return self

            def contains(self, *_args: object) -> "Query":
                raise AssertionError("No debe usar fallback legacy si roi_id existe")

            def limit(self, _limit: int) -> "Query":
                return self

            def execute(self) -> object:
                if self.table_name != "zones":
                    raise AssertionError(f"Tabla inesperada: {self.table_name}")
                return SimpleNamespace(
                    data=[{"id": "zone-1", "name": "ROI 1", "roi_id": self.filters.get("roi_id")}],
                )

        class Client:
            def table(self, name: str) -> Query:
                return Query(name)

        service = object.__new__(SupabaseService)
        service.client = Client()
        service.get_roi = lambda _roi_id: {  # type: ignore[method-assign]
            "id": "roi-1",
            "name": "ROI 1",
            "geojson": {"type": "Polygon", "coordinates": []},
            "orthomosaic_id": "flight-1",
        }

        result = service.ensure_zone_for_roi("roi-1")

        self.assertEqual(result["id"], "zone-1")
        self.assertEqual(result["roi_id"], "roi-1")

    def test_ensure_zone_for_roi_falls_back_to_legacy_properties_lookup(self) -> None:
        queries: list[tuple[str, str]] = []

        class Query:
            def __init__(self, table_name: str) -> None:
                self.table_name = table_name
                self.mode = "select"

            def select(self, columns: str) -> "Query":
                queries.append((self.table_name, columns))
                return self

            def eq(self, _field: str, _value: object) -> "Query":
                return self

            def contains(self, *_args: object) -> "Query":
                return self

            def limit(self, _limit: int) -> "Query":
                return self

            def execute(self) -> object:
                if self.table_name != "zones":
                    raise AssertionError(f"Tabla inesperada: {self.table_name}")
                if len(queries) == 1:
                    raise RuntimeError("column zones.roi_id does not exist")
                return SimpleNamespace(data=[{"id": "zone-legacy", "name": "ROI legacy"}])

        class Client:
            def table(self, name: str) -> Query:
                return Query(name)

        service = object.__new__(SupabaseService)
        service.client = Client()
        service.get_roi = lambda _roi_id: {  # type: ignore[method-assign]
            "id": "roi-1",
            "name": "ROI 1",
            "geojson": {"type": "Polygon", "coordinates": []},
            "orthomosaic_id": "flight-1",
        }

        result = service.ensure_zone_for_roi("roi-1")

        self.assertEqual(result["id"], "zone-legacy")
        self.assertEqual(
            queries,
            [
                ("zones", service.ZONE_COLUMNS),
                ("zones", "id,name,geom,source_format,properties,created_at"),
            ],
        )

    def test_ensure_zone_for_roi_falls_back_to_legacy_insert_without_roi_id_column(self) -> None:
        inserts: list[dict[str, object]] = []

        class Query:
            def __init__(self, table_name: str) -> None:
                self.table_name = table_name
                self.action = "select"
                self.payload: dict[str, object] | None = None

            def select(self, _columns: str) -> "Query":
                self.action = "select"
                return self

            def eq(self, _field: str, _value: object) -> "Query":
                return self

            def contains(self, *_args: object) -> "Query":
                return self

            def limit(self, _limit: int) -> "Query":
                return self

            def insert(self, payload: dict[str, object]) -> "Query":
                self.action = "insert"
                self.payload = payload
                return self

            def execute(self) -> object:
                if self.table_name != "zones":
                    raise AssertionError(f"Tabla inesperada: {self.table_name}")
                if self.action == "select":
                    return SimpleNamespace(data=[])
                inserts.append(dict(self.payload or {}))
                if "roi_id" in (self.payload or {}):
                    raise RuntimeError("Could not find the 'roi_id' column of 'zones' in the schema cache")
                return SimpleNamespace(
                    data=[{"id": "zone-legacy", "name": "ROI 1", **(self.payload or {})}],
                )

        class Client:
            def table(self, name: str) -> Query:
                return Query(name)

        service = object.__new__(SupabaseService)
        service.client = Client()
        service.get_roi = lambda _roi_id: {  # type: ignore[method-assign]
            "id": "roi-1",
            "name": "ROI 1",
            "geojson": {
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
            "orthomosaic_id": "flight-1",
        }

        result = service.ensure_zone_for_roi("roi-1")

        self.assertEqual(result["id"], "zone-legacy")
        self.assertEqual(len(inserts), 2)
        self.assertIn("roi_id", inserts[0])
        self.assertNotIn("roi_id", inserts[1])
        self.assertEqual(inserts[1]["properties"], {"roi_id": "roi-1", "orthomosaic_id": "flight-1"})

    def test_empty_modern_history_does_not_query_legacy_roi_id_column(self) -> None:
        selected_columns: list[str] = []

        class Query:
            def select(self, columns: str) -> "Query":
                selected_columns.append(columns)
                return self

            def contains(self, *_args: object) -> "Query":
                return self

            def eq(self, *_args: object) -> "Query":
                return self

            def order(self, *_args: object, **_options: object) -> "Query":
                return self

            def execute(self) -> object:
                return SimpleNamespace(data=[])

        class Client:
            def table(self, name: str) -> Query:
                self.table_name = name
                return Query()

        service = object.__new__(SupabaseService)
        service.client = Client()
        service.get_roi = lambda _roi_id: {  # type: ignore[method-assign]
            "id": "roi-1",
            "agricultural_cycle_id": "cycle-1",
        }

        result = service.list_roi_analyses("roi-1", "NDVI", "cycle-1")

        self.assertEqual(result, [])
        self.assertEqual(
            selected_columns,
            [
                service.INDEX_RESULT_MODERN_COLUMNS,
                service.ROI_ANALYSES_COLUMNS,
            ],
        )

    def test_storage_upload_reconnects_after_read_error(self) -> None:
        uploads: list[tuple[str, bytes, dict[str, str]]] = []

        class Bucket:
            def __init__(self, fail: bool) -> None:
                self.fail = fail

            def upload(
                self,
                path: str,
                content: bytes,
                options: dict[str, str],
            ) -> None:
                if self.fail:
                    raise httpx.ReadError(
                        "Read failed",
                        request=httpx.Request("POST", "https://example.supabase.co"),
                    )
                uploads.append((path, content, options))

        class Storage:
            def __init__(self, fail: bool) -> None:
                self.bucket = Bucket(fail)

            def from_(self, _bucket_name: str) -> Bucket:
                return self.bucket

        class Client:
            def __init__(self, fail: bool) -> None:
                self.storage = Storage(fail)

        service = object.__new__(SupabaseService)
        service.settings = SimpleNamespace(supabase_bucket="orthomosaics")
        service.client = Client(fail=True)
        recovered_client = Client(fail=False)
        service._reconnect_client = lambda: recovered_client  # type: ignore[method-assign]

        service._upload_orthomosaic_object(
            "2026-08-20/flight.tif",
            b"raster",
            "image/tiff",
        )

        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0][0], "2026-08-20/flight.tif")
        self.assertEqual(uploads[0][2]["upsert"], "true")

    def test_list_orthomosaics_falls_back_before_order_migration(self) -> None:
        record = {"id": "flight-1", "name": "Vuelo 1"}

        class Query:
            def __init__(self) -> None:
                self.columns = ""

            def select(self, columns: str) -> "Query":
                self.columns = columns
                return self

            def order(self, *_args: object, **_options: object) -> "Query":
                return self

            def limit(self, _limit: int) -> "Query":
                return self

            def eq(self, *_args: object) -> "Query":
                return self

            def execute(self) -> object:
                if "display_order" in self.columns:
                    raise RuntimeError("column display_order does not exist")
                return SimpleNamespace(data=[record])

        class Client:
            def table(self, _name: str) -> Query:
                return Query()

        service = object.__new__(SupabaseService)
        service.client = Client()

        result = service.list_orthomosaics(100, "cycle-1")

        self.assertEqual(result, [record])

    def test_reorder_orthomosaics_persists_each_position(self) -> None:
        updates: list[tuple[str, int]] = []

        class Query:
            def __init__(self) -> None:
                self.position = -1
                self.orthomosaic_id = ""

            def update(self, payload: dict[str, int]) -> "Query":
                self.position = payload["display_order"]
                return self

            def eq(self, field: str, value: str) -> "Query":
                if field == "id":
                    self.orthomosaic_id = value
                return self

            def execute(self) -> object:
                updates.append((self.orthomosaic_id, self.position))
                return SimpleNamespace(data=[{"id": self.orthomosaic_id}])

        class Client:
            def table(self, _name: str) -> Query:
                return Query()

        service = object.__new__(SupabaseService)
        service.client = Client()
        service.list_orthomosaics = lambda *_args: [  # type: ignore[method-assign]
            {"id": "flight-1", "name": "Vuelo 1"},
            {"id": "flight-2", "name": "Vuelo 2"},
            {"id": "flight-3", "name": "Vuelo 3"},
        ]

        result = service.reorder_orthomosaics(
            "cycle-1",
            ["flight-3", "flight-1", "flight-2"],
        )

        self.assertEqual(
            updates,
            [("flight-3", 0), ("flight-1", 1), ("flight-2", 2)],
        )
        self.assertEqual(
            [item["id"] for item in result],
            ["flight-3", "flight-1", "flight-2"],
        )
        self.assertEqual([item["display_order"] for item in result], [0, 1, 2])

    def test_latest_result_is_kept_per_flight_and_index(self) -> None:
        rows = [
            {
                "id": "old-flight-1",
                "orthomosaic_id": "flight-1",
                "index_type": "NDVI",
                "created_at": "2026-08-01T10:00:00Z",
            },
            {
                "id": "flight-7",
                "orthomosaic_id": "flight-7",
                "index_type": "NDVI",
                "created_at": "2026-08-07T10:00:00Z",
            },
            {
                "id": "edited-flight-1",
                "orthomosaic_id": "flight-1",
                "index_type": "NDVI",
                "created_at": "2026-08-20T10:00:00Z",
            },
        ]

        result = SupabaseService._latest_index_results_per_flight(rows)

        self.assertEqual(len(result), 2)
        self.assertEqual(
            {item["orthomosaic_id"]: item["id"] for item in result},
            {
                "flight-1": "edited-flight-1",
                "flight-7": "flight-7",
            },
        )

    def test_orthomosaic_upsert_reconnects_after_read_error(self) -> None:
        payload = {"id": "flight-1", "name": "Vuelo 1"}

        class Query:
            def __init__(self, result: object = None, error: Exception | None = None):
                self.result = result
                self.error = error

            def upsert(self, _payload: object, **_options: object) -> "Query":
                return self

            def select(self, _columns: str) -> "Query":
                return self

            def eq(self, *_args: object) -> "Query":
                return self

            def limit(self, _limit: int) -> "Query":
                return self

            def execute(self) -> object:
                if self.error:
                    raise self.error
                return self.result

        class Client:
            def __init__(self, query: Query):
                self.query = query

            def table(self, _name: str) -> Query:
                return self.query

        service = object.__new__(SupabaseService)
        service.settings = SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="test-key",
        )
        service.client = Client(
            Query(
                error=httpx.ReadError(
                    "Read failed",
                    request=httpx.Request("POST", "https://example.supabase.co"),
                ),
            ),
        )
        recovered = SimpleNamespace(data=[payload])

        with patch(
            "geofield.services.supabase_service.create_client",
            return_value=Client(Query(result=recovered)),
        ) as reconnect:
            result = service._upsert_orthomosaic_record(payload)

        reconnect.assert_called_once()
        self.assertEqual(result, payload)

    def test_upload_activates_returned_record_without_reading_it_again(self) -> None:
        record = {
            "id": "flight-1",
            "name": "Vuelo 1",
            "sensor_type": "mavic3m",
        }

        class Persistence:
            def upload_orthomosaic(self, **_payload: object) -> dict[str, object]:
                return record

            def activate_orthomosaic_record(
                self,
                selected: dict[str, object],
                _raster: object,
            ) -> dict[str, object]:
                self.activated = selected
                return selected

            def activate_orthomosaic(self, *_args: object) -> None:
                raise AssertionError("No debe volver a consultar el registro recién creado")

        class Raster:
            def validate_uploaded(self, _content: bytes) -> None:
                return None

            def analyze_uploaded(self, *_args: object) -> dict[str, str]:
                return {"status": "ok"}

        persistence = Persistence()
        service = OrthomosaicApplicationService(Raster(), persistence)  # type: ignore[arg-type]

        result = service.upload_orthomosaic(
            content=b"raster",
            filename="flight-1.tif",
            agricultural_cycle_id="cycle-1",
            capture_date=date(2026, 8, 20),
            sensor_type="mavic3m",
            name="Vuelo 1",
            content_type="image/tiff",
            activate=True,
        )

        self.assertIs(persistence.activated, record)
        self.assertIs(result["orthomosaic"], record)

    def test_save_roi_analysis_falls_back_to_roi_analyses_for_ndwi(self) -> None:
        stats = {
            "count": 10,
            "min": -0.6,
            "max": 0.2,
            "mean": -0.1,
            "median": -0.08,
            "standard_deviation": 0.12,
            "p10": -0.5,
            "p25": -0.3,
            "p75": 0.05,
            "p90": 0.15,
            "range_min": -1.0,
            "range_max": 1.0,
        }
        inserts: list[dict[str, object]] = []

        class Query:
            def __init__(self, table_name: str) -> None:
                self.table_name = table_name
                self.filters: dict[str, object] = {}
                self.payload: dict[str, object] | None = None
                self.action = "select"

            def select(self, _columns: str) -> "Query":
                if self.action not in {"insert", "update"}:
                    self.action = "select"
                return self

            def contains(self, *_args: object) -> "Query":
                return self

            def eq(self, field: str, value: object) -> "Query":
                self.filters[field] = value
                return self

            def order(self, *_args: object, **_options: object) -> "Query":
                return self

            def limit(self, _limit: int) -> "Query":
                return self

            def update(self, payload: dict[str, object]) -> "Query":
                self.action = "update"
                self.payload = payload
                return self

            def insert(self, payload: dict[str, object]) -> "Query":
                self.action = "insert"
                self.payload = payload
                return self

            def execute(self) -> object:
                if self.table_name == "index_results":
                    if self.action == "select" and "zone_id" in self.filters:
                        return SimpleNamespace(data=[])
                    if self.action == "select" and "roi_id" in self.filters:
                        raise RuntimeError("column index_results.roi_id does not exist")
                    raise RuntimeError(
                        'new row for relation "index_results" violates check constraint '
                        '"index_results_index_type_check"',
                    )

                if self.table_name == "roi_analyses":
                    if self.action == "select":
                        return SimpleNamespace(data=[])
                    if self.action == "insert":
                        inserts.append(dict(self.payload or {}))
                        row = {
                            "id": "ra-1",
                            "roi_id": "roi-1",
                            "orthomosaic_id": "flight-1",
                            "ndvi": (self.payload or {}).get("ndvi"),
                            "ndwi": (self.payload or {}).get("ndwi"),
                            "ndre": (self.payload or {}).get("ndre"),
                            "created_at": "2026-08-27T03:02:30Z",
                            "orthomosaics": {"name": "Vuelo 1", "capture_date": "2026-08-20"},
                        }
                        return SimpleNamespace(data=[row])
                raise AssertionError(f"Tabla inesperada: {self.table_name}")

        class Client:
            def table(self, name: str) -> Query:
                return Query(name)

        service = object.__new__(SupabaseService)
        service.client = Client()
        service.get_roi = lambda _roi_id: {"id": "roi-1"}  # type: ignore[method-assign]
        service.get_orthomosaic = lambda _orthomosaic_id: {"id": "flight-1"}  # type: ignore[method-assign]
        service.ensure_zone_for_roi = lambda _roi_id: {"id": "zone-1"}  # type: ignore[method-assign]

        result = service.save_roi_analysis("roi-1", "flight-1", "NDWI", stats)

        self.assertEqual(result["ndwi"], stats)
        self.assertIsNone(result["ndvi"])
        self.assertTrue(str(result["id"]).startswith("roi_analyses:ra-1:NDWI"))
        self.assertEqual(inserts[0]["ndvi"], {})
        self.assertEqual(inserts[0]["ndwi"], stats)

    def test_list_roi_analyses_falls_back_to_roi_analyses_table(self) -> None:
        roi_analysis_row = {
            "id": "ra-1",
            "roi_id": "roi-1",
            "orthomosaic_id": "flight-1",
            "ndvi": {},
            "ndwi": {
                "count": 10,
                "min": -0.6,
                "max": 0.2,
                "mean": -0.1,
            },
            "ndre": None,
            "created_at": "2026-08-27T03:02:30Z",
            "orthomosaics": {"name": "Vuelo 1", "capture_date": "2026-08-20"},
        }

        class Query:
            def __init__(self, table_name: str) -> None:
                self.table_name = table_name
                self.filters: dict[str, object] = {}
                self.action = "select"

            def select(self, _columns: str) -> "Query":
                self.action = "select"
                return self

            def contains(self, *_args: object) -> "Query":
                return self

            def eq(self, field: str, value: object) -> "Query":
                self.filters[field] = value
                return self

            def order(self, *_args: object, **_options: object) -> "Query":
                return self

            def execute(self) -> object:
                if self.table_name == "index_results":
                    if "roi_id" in self.filters:
                        raise RuntimeError("column index_results.roi_id does not exist")
                    return SimpleNamespace(data=[])
                if self.table_name == "roi_analyses":
                    return SimpleNamespace(data=[roi_analysis_row])
                raise AssertionError(f"Tabla inesperada: {self.table_name}")

        class Client:
            def table(self, name: str) -> Query:
                return Query(name)

        service = object.__new__(SupabaseService)
        service.client = Client()
        service.get_roi = lambda _roi_id: {  # type: ignore[method-assign]
            "id": "roi-1",
            "agricultural_cycle_id": "cycle-1",
        }

        result = service.list_roi_analyses("roi-1", "NDWI", "cycle-1")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ndwi"], roi_analysis_row["ndwi"])
        self.assertEqual(result[0]["id"], "roi_analyses:ra-1:NDWI")


if __name__ == "__main__":
    unittest.main()
