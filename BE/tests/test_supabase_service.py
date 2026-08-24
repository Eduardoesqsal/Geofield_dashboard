"""Pruebas de normalización del historial persistido en Supabase."""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from geofield.services.supabase_service import SupabaseService
from geofield.services.application_service import OrthomosaicApplicationService


class SupabaseHistoryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
