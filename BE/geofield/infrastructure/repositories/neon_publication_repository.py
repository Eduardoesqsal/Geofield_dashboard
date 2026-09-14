"""Repositorio PostgreSQL/Neon para publicaciones del dashboard."""

from __future__ import annotations

from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - depende del entorno instalado.
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment]


class NeonPublicationRepository:
    """Persiste publicaciones en la base Neon separada de Supabase."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url.strip()
        if not self.database_url:
            raise ValueError("PUBLICATION_DATABASE_URL no esta configurada.")

    def healthcheck(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("select 1 as ok").fetchone()
        return {"database": "neon", "ok": row["ok"] == 1}

    def list(self, source_project_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if source_project_id:
                rows = connection.execute(
                    """
                    select
                      analysis.id,
                      analysis.source_publication_key,
                      analysis.source_orthomosaic_id,
                      analysis.source_roi_id,
                      analysis.analysis_type,
                      analysis.status,
                      analysis.published_at,
                      project.name as project_name,
                      project.field_name,
                      project.crop_name,
                      project.cycle_name,
                      coalesce(index_counts.count, 0) as index_count,
                      zoning.id is not null as has_zoning,
                      prescription.id is not null as has_prescription,
                      coalesce(artifact_counts.count, 0) as artifact_count
                    from public.published_analyses as analysis
                    left join public.published_projects as project
                      on project.id = analysis.project_id
                    left join lateral (
                      select count(*)::int as count
                      from public.published_index_results as result
                      where result.analysis_id = analysis.id
                    ) as index_counts on true
                    left join lateral (
                      select id
                      from public.published_zonings as item
                      where item.analysis_id = analysis.id
                      limit 1
                    ) as zoning on true
                    left join lateral (
                      select id
                      from public.published_prescriptions as item
                      where item.analysis_id = analysis.id
                      limit 1
                    ) as prescription on true
                    left join lateral (
                      select count(*)::int as count
                      from public.published_artifacts as artifact
                      where artifact.analysis_id = analysis.id
                    ) as artifact_counts on true
                    where project.source_project_id = %s
                    order by analysis.published_at desc
                    limit 200
                    """,
                    (source_project_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    select
                      analysis.id,
                      analysis.source_publication_key,
                      analysis.source_orthomosaic_id,
                      analysis.source_roi_id,
                      analysis.analysis_type,
                      analysis.status,
                      analysis.published_at,
                      project.name as project_name,
                      project.field_name,
                      project.crop_name,
                      project.cycle_name,
                      coalesce(index_counts.count, 0) as index_count,
                      zoning.id is not null as has_zoning,
                      prescription.id is not null as has_prescription,
                      coalesce(artifact_counts.count, 0) as artifact_count
                    from public.published_analyses as analysis
                    left join public.published_projects as project
                      on project.id = analysis.project_id
                    left join lateral (
                      select count(*)::int as count
                      from public.published_index_results as result
                      where result.analysis_id = analysis.id
                    ) as index_counts on true
                    left join lateral (
                      select id
                      from public.published_zonings as item
                      where item.analysis_id = analysis.id
                      limit 1
                    ) as zoning on true
                    left join lateral (
                      select id
                      from public.published_prescriptions as item
                      where item.analysis_id = analysis.id
                      limit 1
                    ) as prescription on true
                    left join lateral (
                      select count(*)::int as count
                      from public.published_artifacts as artifact
                      where artifact.analysis_id = analysis.id
                    ) as artifact_counts on true
                    order by analysis.published_at desc
                    limit 200
                    """
                ).fetchall()
        return [self._serialize_publication(row) for row in rows]

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.transaction():
                project_id = self._insert_project(connection, payload["project"])
                analysis = payload["analysis"]
                analysis_row = self._upsert_analysis(connection, project_id, analysis)
                analysis_id = analysis_row["id"]

                self._clear_children(connection, analysis_id)
                self._insert_roi(connection, analysis_id, payload["roi"])
                self._insert_indices(connection, analysis_id, payload.get("indices", []))
                if payload.get("zoning"):
                    self._insert_zoning(connection, analysis_id, payload["zoning"])
                if payload.get("prescription"):
                    self._insert_prescription(connection, analysis_id, payload["prescription"])
                self._insert_artifacts(connection, analysis_id, payload.get("artifacts", []))
                self._insert_event(
                    connection,
                    analysis_id,
                    analysis_row["status"],
                    "Publicacion guardada en Neon.",
                )

        return {
            "status": analysis_row["status"],
            "publication_id": str(analysis_id),
            "source_publication_key": analysis["source_publication_key"],
            "payload_hash": analysis.get("payload_hash"),
        }

    def delete(self, source_publication_key: str) -> dict[str, Any]:
        with self._connect() as connection:
            with connection.transaction():
                row = connection.execute(
                    """
                    select id, project_id
                    from public.published_analyses
                    where source_publication_key = %s
                    """,
                    (source_publication_key,),
                ).fetchone()
                if not row:
                    return {
                        "status": "not_found",
                        "source_publication_key": source_publication_key,
                        "deleted": False,
                    }
                connection.execute(
                    "delete from public.published_analyses where id = %s",
                    (row["id"],),
                )
                if row.get("project_id"):
                    connection.execute(
                        """
                        delete from public.published_projects as project
                        where project.id = %s
                          and not exists (
                            select 1
                            from public.published_analyses as analysis
                            where analysis.project_id = project.id
                          )
                        """,
                        (row["project_id"],),
                    )
        return {
            "status": "deleted",
            "source_publication_key": source_publication_key,
            "deleted": True,
        }

    def _connect(self) -> Any:
        if psycopg is None:
            raise RuntimeError("Instala psycopg[binary] para conectar con Neon.")
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _serialize_publication(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "id": str(row["id"]),
            "published_at": row["published_at"].isoformat() if row.get("published_at") else None,
        }

    def _insert_project(self, connection: Any, project: dict[str, Any]) -> Any:
        row = connection.execute(
            """
            insert into public.published_projects (
              source_project_id, name, field_name, crop_name, cycle_name, source_metadata
            )
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                project.get("source_project_id"),
                project["name"],
                project.get("field_name"),
                project.get("crop_name"),
                project.get("cycle_name"),
                Jsonb(project.get("source_metadata") or {}),
            ),
        ).fetchone()
        return row["id"]

    def _upsert_analysis(self, connection: Any, project_id: Any, analysis: dict[str, Any]) -> dict[str, Any]:
        return connection.execute(
            """
            insert into public.published_analyses (
              project_id,
              source_publication_key,
              source_orthomosaic_id,
              source_roi_id,
              source_roi_analysis_id,
              analysis_type,
              status,
              payload_version,
              payload_hash
            )
            values (%s, %s, %s, %s, %s, %s, 'published', %s, %s)
            on conflict (source_publication_key) do update set
              project_id = excluded.project_id,
              source_orthomosaic_id = excluded.source_orthomosaic_id,
              source_roi_id = excluded.source_roi_id,
              source_roi_analysis_id = excluded.source_roi_analysis_id,
              analysis_type = excluded.analysis_type,
              status = 'updated',
              payload_version = excluded.payload_version,
              payload_hash = excluded.payload_hash,
              published_at = now(),
              updated_at = now()
            returning id, status
            """,
            (
                project_id,
                analysis["source_publication_key"],
                analysis.get("source_orthomosaic_id"),
                analysis.get("source_roi_id"),
                analysis.get("source_roi_analysis_id"),
                analysis.get("analysis_type", "roi_prescription"),
                analysis.get("payload_version", 1),
                analysis.get("payload_hash"),
            ),
        ).fetchone()

    def _clear_children(self, connection: Any, analysis_id: Any) -> None:
        for table in (
            "published_artifacts",
            "published_prescriptions",
            "published_zonings",
            "published_index_results",
            "published_rois",
        ):
            connection.execute(f"delete from public.{table} where analysis_id = %s", (analysis_id,))

    def _insert_roi(self, connection: Any, analysis_id: Any, roi: dict[str, Any]) -> None:
        connection.execute(
            """
            insert into public.published_rois (
              analysis_id, name, geometry_geojson, area_hectares, bounds
            )
            values (%s, %s, %s, %s, %s)
            """,
            (
                analysis_id,
                roi.get("name"),
                Jsonb(roi["geometry_geojson"]),
                roi.get("area_hectares"),
                Jsonb(roi.get("bounds")),
            ),
        )

    def _insert_indices(self, connection: Any, analysis_id: Any, indices: list[dict[str, Any]]) -> None:
        for item in indices:
            stats = item.get("stats") or {}
            connection.execute(
                """
                insert into public.published_index_results (
                  analysis_id, index_name, stats_json, range_min, range_max
                )
                values (%s, %s, %s, %s, %s)
                """,
                (
                    analysis_id,
                    item["index_name"],
                    Jsonb(stats),
                    stats.get("range_min"),
                    stats.get("range_max"),
                ),
            )

    def _insert_zoning(self, connection: Any, analysis_id: Any, zoning: dict[str, Any]) -> None:
        connection.execute(
            """
            insert into public.published_zonings (
              analysis_id, source_zoning_id, index_name, classification_method,
              cell_value_mode, zone_count, cell_size_m, grid_angle_deg, detail_level,
              field_mean, valid_cell_count, area_hectares, thresholds_json,
              histogram_json, legend_json, zones_geojson, grid_geojson, response_json
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                analysis_id,
                zoning.get("source_zoning_id"),
                zoning["index_name"],
                zoning.get("classification_method"),
                zoning.get("cell_value_mode"),
                zoning.get("zone_count"),
                zoning.get("cell_size_m"),
                zoning.get("grid_angle_deg"),
                zoning.get("detail_level"),
                zoning.get("field_mean"),
                zoning.get("valid_cell_count"),
                zoning.get("area_hectares"),
                Jsonb(zoning.get("thresholds") or []),
                Jsonb(zoning.get("histogram") or {}),
                Jsonb(zoning.get("legend") or []),
                Jsonb(zoning.get("zones_geojson")),
                Jsonb(zoning.get("grid_geojson")),
                Jsonb(zoning.get("response") or {}),
            ),
        )

    def _insert_prescription(self, connection: Any, analysis_id: Any, prescription: dict[str, Any]) -> None:
        connection.execute(
            """
            insert into public.published_prescriptions (
              analysis_id, source_prescription_id, index_name, product_name, unit,
              classification_method, cell_value_mode, zone_count, cell_size_m,
              grid_angle_deg, detail_level, field_mean, valid_cell_count,
              area_hectares, thresholds_json, histogram_json, legend_json,
              rates_json, prescription_geojson, grid_geojson, response_json
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                analysis_id,
                prescription.get("source_prescription_id"),
                prescription["index_name"],
                prescription.get("product_name"),
                prescription.get("unit"),
                prescription.get("classification_method"),
                prescription.get("cell_value_mode"),
                prescription.get("zone_count"),
                prescription.get("cell_size_m"),
                prescription.get("grid_angle_deg"),
                prescription.get("detail_level"),
                prescription.get("field_mean"),
                prescription.get("valid_cell_count"),
                prescription.get("area_hectares"),
                Jsonb(prescription.get("thresholds") or []),
                Jsonb(prescription.get("histogram") or {}),
                Jsonb(prescription.get("legend") or []),
                Jsonb(prescription.get("rates") or []),
                Jsonb(prescription.get("prescription_geojson")),
                Jsonb(prescription.get("grid_geojson")),
                Jsonb(prescription.get("response") or {}),
            ),
        )

    def _insert_artifacts(self, connection: Any, analysis_id: Any, artifacts: list[dict[str, Any]]) -> None:
        for artifact in artifacts:
            connection.execute(
                """
                insert into public.published_artifacts (
                  analysis_id, artifact_type, name, url, storage_key, metadata_json
                )
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    analysis_id,
                    artifact.get("artifact_type"),
                    artifact.get("name"),
                    artifact.get("url"),
                    artifact.get("storage_key"),
                    Jsonb(artifact.get("metadata") or artifact.get("metadata_json") or {}),
                ),
            )

    def _insert_event(self, connection: Any, analysis_id: Any, status: str, message: str) -> None:
        connection.execute(
            """
            insert into public.publication_events (analysis_id, status, message)
            values (%s, %s, %s)
            """,
            (analysis_id, status, message),
        )
