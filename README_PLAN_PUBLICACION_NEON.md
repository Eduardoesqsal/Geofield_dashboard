# Plan de publicacion de resultados a Neon

## Objetivo

Agregar a Geofield un flujo para publicar resultados ya generados por la app actual hacia una base de datos nueva en Neon PostgreSQL. Esa base sera consumida despues por un dashboard externo.

La app actual no se reemplaza. Geofield sigue calculando ROI, NDVI, NDWI, NDRE, estadisticas, zonificacion y prescripcion. La nueva funcionalidad solo envia esos resultados a Neon para visualizarlos en otro dashboard.

Flujo objetivo:

```text
Geofield actual -> Boton Publicar resultados -> API backend -> Neon PostgreSQL -> Dashboard externo
```

## Alcance funcional

El boton **Publicar resultados** debe permitir enviar a Neon el resultado completo de un analisis ya realizado:

- Proyecto, lote, ciclo agricola u ortomosaico relacionado.
- ROI usado para el analisis.
- Indices generados: NDVI, NDWI y NDRE.
- Estadisticas por indice: minimo, maximo, promedio, mediana, desviacion estandar, percentiles y conteo, segun lo disponible.
- Zonificacion generada a partir del ROI o indice.
- Prescripcion generada: zonas, dosis, productos y valores calculados.
- Archivos o capas generadas: GeoJSON, URLs, artefactos, tiles o referencias necesarias para el dashboard.
- Estado de publicacion: pendiente, publicada, error o actualizada.

## Principio clave

El dashboard externo no debe recalcular los resultados. Solo debe consultar datos publicados.

Geofield es la fuente de procesamiento. Neon sera la fuente de consulta para el dashboard.

## Arquitectura propuesta

### 1. Base de datos Neon

Crear una base PostgreSQL en Neon separada de la base actual de Geofield.

Variable esperada:

```env
PUBLICATION_DATABASE_URL=postgresql://usuario:password@host/dbname?sslmode=require
```

Esta conexion debe usarse solo para publicaciones y dashboard, no para reemplazar la persistencia actual.

### 2. API de publicacion

Agregar endpoints en el backend de Geofield para publicar y consultar el estado:

```http
POST /api/publications
GET /api/publications/{publication_id}
GET /api/publications
```

El endpoint principal recibira o construira un paquete JSON con los resultados actuales y los guardara en Neon.

### 3. Boton en frontend

Agregar un boton **Publicar resultados** cuando exista un resultado listo para publicar.

El boton debe:

- Validar que exista un ROI/analisis/prescripcion lista.
- Llamar a la API de publicacion.
- Mostrar estado de carga.
- Mostrar exito o error.
- Evitar publicaciones duplicadas cuando sea posible.

### 4. Dashboard externo

El dashboard externo consumira Neon directamente o mediante otra API, segun se defina despues.

Debe poder mostrar:

- Lista de publicaciones.
- Detalle por proyecto/lote/ROI.
- Mapas o geometria del ROI.
- Resultados NDVI, NDWI, NDRE.
- Estadisticas.
- Zonificacion.
- Prescripcion.
- Archivos/capas asociadas.

## Modelo inicial de tablas

Este esquema es inicial y puede ajustarse segun lo que necesite el dashboard.

### `published_projects`

Guarda contexto general del proyecto o lote.

Campos sugeridos:

- `id`
- `source_project_id`
- `name`
- `field_name`
- `crop_name`
- `cycle_name`
- `created_at`
- `updated_at`

### `published_analyses`

Representa un analisis publicado desde Geofield.

Campos sugeridos:

- `id`
- `project_id`
- `source_orthomosaic_id`
- `source_roi_id`
- `analysis_type`
- `status`
- `published_at`
- `source_payload_hash`
- `created_at`
- `updated_at`

### `published_rois`

Guarda la geometria y metadatos del ROI.

Campos sugeridos:

- `id`
- `analysis_id`
- `name`
- `geometry_geojson`
- `area`
- `created_at`

### `published_index_results`

Guarda resultados por indice.

Campos sugeridos:

- `id`
- `analysis_id`
- `index_name`
- `stats_json`
- `range_min`
- `range_max`
- `created_at`

Ejemplos de `index_name`:

- `NDVI`
- `NDWI`
- `NDRE`

### `published_zones`

Guarda la zonificacion.

Campos sugeridos:

- `id`
- `analysis_id`
- `index_name`
- `zones_geojson`
- `classes_json`
- `created_at`

### `published_prescriptions`

Guarda la prescripcion generada.

Campos sugeridos:

- `id`
- `analysis_id`
- `prescription_geojson`
- `rates_json`
- `product_name`
- `unit`
- `created_at`

### `published_artifacts`

Guarda referencias a archivos o capas.

Campos sugeridos:

- `id`
- `analysis_id`
- `artifact_type`
- `name`
- `url`
- `metadata_json`
- `created_at`

Ejemplos de `artifact_type`:

- `geojson`
- `raster`
- `tile_layer`
- `prescription_file`
- `preview_image`

### `publication_events`

Guarda historial de intentos de publicacion.

Campos sugeridos:

- `id`
- `analysis_id`
- `status`
- `message`
- `error_detail`
- `created_at`

## Contrato JSON inicial

Ejemplo conceptual del payload a publicar:

```json
{
  "project": {
    "source_project_id": "local-or-supabase-id",
    "name": "Proyecto demo",
    "field_name": "Lote 1",
    "crop_name": "Maiz",
    "cycle_name": "Ciclo 2026"
  },
  "analysis": {
    "source_orthomosaic_id": "orthomosaic-id",
    "source_roi_id": "roi-id",
    "analysis_type": "roi_prescription"
  },
  "roi": {
    "name": "ROI Norte",
    "geometry_geojson": {}
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
        "standard_deviation": 0.14
      }
    }
  ],
  "zoning": {
    "index_name": "NDVI",
    "zones_geojson": {},
    "classes": []
  },
  "prescription": {
    "prescription_geojson": {},
    "rates": [],
    "product_name": "Producto",
    "unit": "kg/ha"
  },
  "artifacts": [
    {
      "artifact_type": "geojson",
      "name": "prescripcion.geojson",
      "url": "https://..."
    }
  ]
}
```

## Fases de implementacion

### Fase 1: Definir contrato minimo

- Confirmar datos exactos que necesita el dashboard.
- Definir si se publica por ROI, por ortomosaico, por prescripcion o por proyecto completo.
- Definir campos obligatorios y opcionales.
- Definir si se permite actualizar una publicacion existente.

Resultado esperado:

- Contrato JSON version 1.
- SQL inicial de Neon.

Entregables iniciales en este repo:

- `BE/docs/publication_payload_v1.md`
- `BE/sql/neon/001_create_publication_schema.sql`

### Fase 2: Crear Neon y esquema SQL

- Crear proyecto en Neon.
- Obtener `PUBLICATION_DATABASE_URL`.
- Crear tablas iniciales.
- Agregar indices y relaciones.
- Probar conexion desde backend.

Resultado esperado:

- BD Neon lista.
- Migracion SQL documentada.

### Fase 3: Backend de publicacion

- Agregar configuracion `PUBLICATION_DATABASE_URL`.
- Crear repositorio de publicaciones para Neon.
- Crear caso de uso `PublishResultsUseCase`.
- Crear endpoint `POST /api/publications`.
- Guardar eventos de exito/error.
- Evitar duplicados con hash o identificador de origen.

Resultado esperado:

- API capaz de guardar una publicacion completa en Neon.

### Fase 4: Recoleccion de resultados actuales

- Identificar donde vive cada resultado actual:
  - ROI.
  - NDVI, NDWI, NDRE.
  - Estadisticas.
  - Zonificacion.
  - Prescripcion.
  - Artefactos/capas.
- Construir el payload desde datos existentes.
- No recalcular innecesariamente si el resultado ya existe.

Resultado esperado:

- Payload real construido desde Geofield.

### Fase 5: Boton en frontend

- Agregar boton **Publicar resultados**.
- Conectar con endpoint backend.
- Mostrar loading, exito y error.
- Mostrar si el resultado ya fue publicado.

Resultado esperado:

- Usuario puede publicar desde la interfaz.

### Fase 6: Validacion para dashboard

- Consultar Neon y confirmar que los datos publicados son suficientes.
- Crear queries de ejemplo para el dashboard.
- Ajustar estructura si falta algun campo.

Resultado esperado:

- Datos listos para que otro dashboard los consuma.

## Riesgos y decisiones pendientes

- Definir si Neon guardara geometria como JSONB o con PostGIS.
- Definir donde viviran archivos grandes: Neon no debe guardar binarios pesados.
- Definir si los mapas se publican como GeoJSON, URLs de tiles o ambos.
- Definir autenticacion de la API.
- Definir manejo de duplicados.
- Definir si una publicacion puede actualizarse.
- Definir si el dashboard consumira Neon directo o una API intermedia.

## Recomendacion inicial

Empezar simple:

1. Guardar en Neon una publicacion completa por ROI/analisis.
2. Usar JSONB para resultados complejos como estadisticas, clases, zonas y prescripcion.
3. Guardar archivos pesados como URLs o referencias, no como binarios en Neon.
4. Agregar despues normalizacion extra si el dashboard necesita filtros avanzados.

Este enfoque permite avanzar rapido sin romper la app actual.
