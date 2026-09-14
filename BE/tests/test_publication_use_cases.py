"""Pruebas del caso de uso de publicacion hacia dashboard externo."""

from __future__ import annotations

import unittest
from typing import Any

from geofield.application.use_cases import DeletePublicationUseCase, PublishResultsUseCase


class RecordingPublicationRepository:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payload = payload
        return {
            "status": "published",
            "publication_id": "publication-1",
            "payload_hash": payload["analysis"]["payload_hash"],
        }

    def healthcheck(self) -> dict[str, Any]:
        return {"database": "fake"}

    def delete(self, source_publication_key: str) -> dict[str, Any]:
        return {
            "status": "deleted",
            "source_publication_key": source_publication_key,
            "deleted": True,
        }


def valid_payload() -> dict[str, Any]:
    return {
        "project": {"name": "Lote demo"},
        "analysis": {
            "source_publication_key": "ortho-1:roi-1:prescription-1",
            "source_orthomosaic_id": "ortho-1",
            "source_roi_id": "roi-1",
            "analysis_type": "roi_prescription",
        },
        "roi": {
            "name": "ROI 1",
            "geometry_geojson": {"type": "Polygon", "coordinates": []},
        },
        "indices": [
            {
                "index_name": "NDVI",
                "stats": {"count": 10, "mean": 0.4, "range_min": -1, "range_max": 1},
            },
        ],
        "prescription": {
            "source_prescription_id": "prescription-1",
            "index_name": "NDVI",
            "legend": [],
        },
    }


class PublishResultsUseCaseTests(unittest.TestCase):
    def test_publish_validates_and_adds_payload_hash(self) -> None:
        repository = RecordingPublicationRepository()

        result = PublishResultsUseCase(repository).execute(valid_payload())

        self.assertEqual(result["status"], "published")
        self.assertIsNotNone(repository.payload)
        assert repository.payload is not None
        self.assertEqual(repository.payload["analysis"]["payload_version"], 1)
        self.assertRegex(repository.payload["analysis"]["payload_hash"], r"^[a-f0-9]{64}$")

    def test_publish_rejects_payload_without_indices(self) -> None:
        payload = valid_payload()
        payload["indices"] = []

        with self.assertRaisesRegex(ValueError, "indices debe contener"):
            PublishResultsUseCase(RecordingPublicationRepository()).execute(payload)

    def test_publish_rejects_invalid_prescription_index(self) -> None:
        payload = valid_payload()
        payload["prescription"]["index_name"] = "EVI"

        with self.assertRaisesRegex(ValueError, "prescription.index_name"):
            PublishResultsUseCase(RecordingPublicationRepository()).execute(payload)

    def test_delete_publication_requires_source_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_publication_key"):
            DeletePublicationUseCase(RecordingPublicationRepository()).execute("")

    def test_delete_publication_delegates_to_repository(self) -> None:
        result = DeletePublicationUseCase(RecordingPublicationRepository()).execute(
            "ortho:roi:indices",
        )

        self.assertTrue(result["deleted"])


if __name__ == "__main__":
    unittest.main()
