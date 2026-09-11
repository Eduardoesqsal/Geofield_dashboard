# Contrato de publicacion v1

Este documento define el paquete minimo que Geofield debe publicar hacia Neon cuando el usuario presiona **Publicar resultados**.

La publicacion representa un resultado ya generado por Geofield. El dashboard externo debe leer estos datos desde Neon y no recalcular ROI, indices, zonificacion ni prescripcion.

## Fuente de datos actual

El contrato v1 se alinea con contratos que ya existen en el codigo:

- ROI: `RoiRecord` en `FE/src/services/api.ts`.
- Estadisticas: `RoiAnalysisStats` y `RoiAnalysisRecord`.
- Zonificacion: respuesta de `POST /ndvi_zoning`.
- Prescripcion: respuesta de `POST /prescriptions`.
- Descarga de prescripcion: `GET /prescriptions/{artifact_id}/download.json`.

## Payload requerido

```json
{
  "project": {
    "source_project_id": "optional-source-id",
    "name": "Proyecto o lote",
    "field_name": "Lote 1",
    "crop_name": "Maiz",
    "cycle_name": "Ciclo 2026",
    "source_metadata": {}
  },
  "analysis": {
    "source_publication_key": "orthomosaic-id:roi-id:prescription-id",
    "source_orthomosaic_id": "orthomosaic-id",
    "source_roi_id": "roi-id",
    "source_roi_analysis_id": "roi-analysis-id",
    "analysis_type": "roi_prescription",
    "payload_version": 1
  },
  "roi": {
    "name": "ROI Norte",
    "geometry_geojson": {},
    "area_hectares": 12.4,
    "bounds": [[-103.1, 20.1], [-103.0, 20.2]]
  },
  "indices": [
    {
      "index_name": "NDVI",
      "stats": {
        "count": 1000,
        "min": 0.12,
        "max": 0.88,
        "mean": 0.55,
        "median": 0.57,
        "standard_deviation": 0.14,
        "p10": 0.32,
        "p25": 0.45,
        "p75": 0.68,
        "p90": 0.79,
        "range_min": -1,
        "range_max": 1
      }
    },
    {
      "index_name": "NDWI",
      "stats": {}
    },
    {
      "index_name": "NDRE",
      "stats": {}
    }
  ],
  "zoning": {
    "source_zoning_id": "zoning-id",
    "index_name": "NDVI",
    "classification_method": "quantiles",
    "cell_value_mode": "mean",
    "zone_count": 4,
    "cell_size_m": 3,
    "grid_angle_deg": 0,
    "detail_level": 1,
    "field_mean": 0.55,
    "valid_cell_count": 1000,
    "area_hectares": 12.4,
    "thresholds": [],
    "histogram": {},
    "legend": [],
    "zones_geojson": {},
    "grid_geojson": {},
    "response": {}
  },
  "prescription": {
    "source_prescription_id": "prescription-id",
    "index_name": "NDVI",
    "product_name": "Producto",
    "unit": "kg/ha",
    "classification_method": "quantiles",
    "cell_value_mode": "mean",
    "zone_count": 4,
    "cell_size_m": 3,
    "grid_angle_deg": 0,
    "detail_level": 1,
    "field_mean": 0.55,
    "valid_cell_count": 1000,
    "area_hectares": 12.4,
    "thresholds": [],
    "histogram": {},
    "legend": [
      {
        "class_id": 1,
        "label": "Zona 1",
        "ndvi_min": 0.12,
        "ndvi_max": 0.32,
        "mean": 0.22,
        "color": "#d7191c",
        "cell_count": 250,
        "area_hectares": 3.1,
        "dosage": 80
      }
    ],
    "rates": [
      {
        "class_id": 1,
        "dosage": 80
      }
    ],
    "prescription_geojson": {},
    "grid_geojson": {},
    "response": {}
  },
  "artifacts": [
    {
      "artifact_type": "tile_layer",
      "name": "Tiles de prescripcion",
      "url": "/tiles/prescription/prescription-id/{z}/{x}/{y}.png",
      "storage_key": null,
      "metadata": {}
    },
    {
      "artifact_type": "prescription_json",
      "name": "Prescripcion JSON",
      "url": "/prescriptions/prescription-id/download.json",
      "storage_key": "prescriptions/prescription-id.json",
      "metadata": {}
    }
  ]
}
```

## Campos obligatorios

- `project.name`
- `analysis.source_publication_key`
- `analysis.analysis_type`
- `roi.geometry_geojson`
- Al menos un elemento en `indices`

Para publicar prescripcion completa tambien deben existir:

- `prescription.source_prescription_id`
- `prescription.index_name`
- `prescription.legend`

## Llave anti-duplicados

`analysis.source_publication_key` debe ser estable e identificar una publicacion unica.

Formato recomendado para v1:

```text
{source_orthomosaic_id}:{source_roi_id}:{source_prescription_id}
```

Si todavia no existe prescripcion, usar:

```text
{source_orthomosaic_id}:{source_roi_id}:indices
```

En Neon este campo tiene una restriccion `unique`.

## Mapeo a tablas Neon

- `project` -> `published_projects`
- `analysis` -> `published_analyses`
- `roi` -> `published_rois`
- `indices[]` -> `published_index_results`
- `zoning` -> `published_zonings`
- `prescription` -> `published_prescriptions`
- `artifacts[]` -> `published_artifacts`
- eventos de exito/error -> `publication_events`

## Decision v1

Para la primera version, guardar geometria y objetos complejos como `jsonb`.

Esto evita bloquear la implementacion por PostGIS. Si el dashboard despues necesita queries geoespaciales avanzadas, se puede agregar PostGIS y columnas `geometry` sin romper el contrato JSON.
