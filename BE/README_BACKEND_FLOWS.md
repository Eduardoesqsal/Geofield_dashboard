# Backend Flows for Diagramming

Documento orientado a un agente que necesite crear un diagrama de arquitectura y flujos del backend actual de GeoField Dashboard.

Fecha de referencia: 2026-09-02.

## 1. Objetivo del backend

El backend expone una API FastAPI que:

- activa y sirve ortomosaicos;
- calcula índices espectrales;
- genera tiles RGB, NDVI, NDWI y NDRE;
- recorta ROI;
- genera zonificación y prescripción;
- exporta prescripciones en JSON;
- persiste ciclos, ortomosaicos, ROI y análisis en Supabase;
- normaliza detecciones de árboles.

## 2. Capas principales

El backend está organizado en 5 capas:

1. Entry point
   - [app.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/app.py:1)
2. App factory y wiring
   - [app_factory.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/app_factory.py:1)
3. API HTTP
   - [routes.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/api/routes.py:27)
4. Servicios de aplicación
   - [application_service.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/application_service.py:1)
5. Servicios base
   - [raster_service.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/raster_service.py:43)
   - [supabase_service.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/supabase_service.py:41)
   - [tree_service.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/tree_service.py:14)

## 3. Wiring inicial

### Flujo de arranque

1. `app.py` carga `Settings.from_env()`.
2. `app.py` llama `create_app(settings)`.
3. `app_factory.py` crea `FastAPI`.
4. Registra CORS.
5. Monta `/static` sobre `output_dir`.
6. Construye:
   - `RasterService(config)`
   - `SupabaseService(config)`
7. Inyecta ambos en `create_router(...)`.
8. `routes.py` crea además:
   - `OrthomosaicApplicationService(raster, supabase)`
   - `RoiApplicationService(raster, supabase)`

### Nodos sugeridos para diagrama

- `app.py`
- `Settings`
- `create_app`
- `FastAPI`
- `RasterService`
- `SupabaseService`
- `create_router`
- `OrthomosaicApplicationService`
- `RoiApplicationService`

## 4. Configuración central

Archivo:
- [config.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/config.py:1)

### Responsabilidades

- leer variables de entorno;
- resolver rutas base;
- crear directorios de trabajo;
- definir defaults de puertos, cache y límites de render;
- normalizar URL de Supabase.

### Entradas

- `PORT`
- `RASTER_PATH`
- `FRONTEND_ORIGINS`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_BUCKET`
- `ORTHOMOSAIC_STORAGE_MODE`

### Salidas clave

- `base_dir`
- `output_dir`
- `cache_dir`
- `uploads_dir`
- `raster_path`
- `port`
- credenciales de Supabase

## 5. API HTTP: rutas y roles

Archivo:
- [routes.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/api/routes.py:27)

### Grupos de rutas

1. Salud y raíz
   - `/`
   - `/health`
   - `/supabase/health`

2. Ciclos agrícolas
   - `GET /agricultural_cycles`
   - `POST /agricultural_cycles`
   - `PATCH /agricultural_cycles/{cycle_id}`
   - `DELETE /agricultural_cycles/{cycle_id}`
   - `PATCH /agricultural_cycles/{cycle_id}/orthomosaics/order`

3. Ortomosaicos
   - `GET /orthomosaics`
   - `POST /orthomosaics/upload`
   - `POST /orthomosaics/{orthomosaic_id}/activate`
   - `PATCH /orthomosaics/{orthomosaic_id}`
   - `DELETE /orthomosaics/{orthomosaic_id}`
   - `GET /bounds`

4. Tiles y render
   - `GET /tiles/rgb/{z}/{x}/{y}.png`
   - `GET /tiles/ndvi/{z}/{x}/{y}.png`
   - `GET /tiles/index/{name}/{z}/{x}/{y}.png`
   - `GET /tiles/crop/{crop_id}/{z}/{x}/{y}.png`
   - `GET /tiles/crop-index/{name}/{crop_id}/{z}/{x}/{y}.png`
   - `GET /tiles/prescription/{artifact_id}/{z}/{x}/{y}.png`

5. Índices y análisis raster
   - `POST /ortho_analysis`
   - `GET /ndvi_data`
   - `GET /vegetation_indices/{name}`
   - `POST /roi_ndvi`
   - `POST /roi_indices`
   - `POST /roi_indices/{name}`

6. ROI y recortes
   - `GET /rois`
   - `POST /rois`
   - `PATCH /rois/{roi_id}`
   - `DELETE /rois/{roi_id}`
   - `POST /recortar`
   - `POST /crop_tiles`
   - `GET /crop_tiles/{crop_id}/download`

7. Análisis persistidos
   - `GET /rois/{roi_id}/analyses`
   - `POST /rois/{roi_id}/analyses`
   - `DELETE /rois/{roi_id}/analyses/{analysis_id}`

8. Prescripción
   - `POST /ndvi_zoning`
   - `POST /prescriptions`
   - `GET /prescriptions/{artifact_id}/download.json`

9. Árboles
   - `POST /tree_points`

## 6. Helpers internos de routes.py

### `payload_geometry`

Responsabilidad:
- validar el `geojson` recibido;
- aceptar `Feature`, `FeatureCollection` o `geometry`;
- convertir a geometría `shapely`.

### `ensure_orthomosaic`

Responsabilidad:
- si llega `orthomosaic_id`, activar ese ortomosaico antes de operar;
- delegar a `OrthomosaicApplicationService.activate_orthomosaic`.

Este helper aparece en muchos flujos y es importante para el diagrama porque conecta API HTTP con persistencia y estado raster activo.

## 7. Servicio RasterService

Archivo:
- [raster_service.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/raster_service.py:43)

### Rol general

Es el motor geoespacial. No conoce HTTP. Se encarga de:

- abrir el raster activo;
- validar GeoTIFF;
- reproyectar;
- generar overlays;
- calcular índices;
- producir tiles PNG;
- construir recortes;
- clasificar grillas;
- generar zonificación;
- generar prescripción;
- exportar JSON de prescripción.

### Estado interno relevante

- `active_path`
- `sensor`
- `overlay`
- `rgb_stretch`
- `crop_geometries`

### Subflujos principales

1. Validación de raster
   - `validate_uploaded`
   - `validate_path`

2. Lectura base
   - `_path`
   - `ensure_overlay`
   - `geometry_window`

3. Cálculo de índices
   - `ndvi_data`
   - `vegetation_index_data`
   - `roi_ndvi`
   - `roi_vegetation_index`

4. Render y tiles
   - `tile`
   - `index_tile`
   - `crop_tile`
   - `crop_index_tile`
   - `prescription_tile`

5. Recortes
   - `crop`
   - `begin_crop_tiles`
   - `export_crop`
   - `export_crop_visual`

6. Clasificación y prescripción
   - `_prepare_index_classification`
   - `ndvi_zoning_map`
   - `prescription_map_with_doses`
   - `_save_prescription_geojson`

### Componentes lógicos a diagramar dentro de RasterService

- carga de raster activo;
- transformación CRS;
- máscara geométrica;
- cálculo de índice;
- agregación a celdas;
- clasificación en zonas;
- render de artifact PNG/TIF;
- exportación JSON.

## 8. Servicio SupabaseService

Archivo:
- [supabase_service.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/supabase_service.py:41)

### Rol general

Es el adaptador de persistencia. Centraliza:

- conexión a Supabase;
- CRUD de ciclos;
- CRUD de ortomosaicos;
- activación de ortomosaicos;
- CRUD de ROI;
- guardado y lectura de análisis;
- acceso a bucket de almacenamiento si aplica.

### Responsabilidades clave

1. Cliente y reconexión
   - `require_client`
   - `_reconnect_client`

2. Ortomosaicos
   - `upload_orthomosaic`
   - `activate_orthomosaic`
   - `activate_orthomosaic_record`
   - `get_orthomosaic`
   - `list_orthomosaics`
   - `delete_orthomosaic`
   - `update_orthomosaic_capture_date`

3. Ciclos agrícolas
   - `list_agricultural_cycles`
   - `create_agricultural_cycle`
   - `update_agricultural_cycle`
   - `delete_agricultural_cycle`
   - `reorder_orthomosaics`

4. ROI
   - `list_rois`
   - `get_roi`
   - `create_roi`
   - `set_roi_active`
   - `delete_roi`

5. Análisis
   - `save_roi_analysis`
   - `list_roi_analyses`
   - `delete_roi_analysis`

### Interfaz hacia RasterService

`SupabaseService` no procesa índices, pero sí participa en el cambio de estado del raster activo cuando:

- activa un ortomosaico;
- descarga o resuelve su archivo;
- carga metadatos geográficos;
- limpia o reemplaza el raster activo.

## 9. Servicios de aplicación

Archivo:
- [application_service.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/application_service.py:1)

### OrthomosaicApplicationService

Rol:
- coordinar reglas de negocio de ortomosaicos entre rutas HTTP, raster y persistencia.

Flujos clave:

1. `upload_orthomosaic`
   - valida el GeoTIFF con `RasterService.validate_uploaded`;
   - persiste en Supabase;
   - activa el registro si corresponde;
   - ejecuta `raster.analyze_uploaded(...)`;
   - devuelve metadata + análisis.

2. `activate_orthomosaic`
   - delega en Supabase la activación y sincronización con `RasterService`.

3. `delete_orthomosaic`
   - resuelve el registro;
   - si era el activo, limpia estado raster;
   - elimina el registro persistido.

4. `delete_agricultural_cycle`
   - resetea ortomosaicos activos asociados;
   - elimina el ciclo completo.

### RoiApplicationService

Rol:
- encapsular persistencia y consistencia de análisis ROI.

Flujos clave:

1. `create_roi`
   - delega creación a Supabase.

2. `save_roi_analysis`
   - si el frontend ya manda estadísticas, las normaliza y persiste;
   - si no, calcula estadísticas desde `RasterService.roi_vegetation_index`;
   - guarda el análisis en Supabase.

3. `stats_match`
   - compara lo calculado/enviado con lo persistido.

## 10. TreeService

Archivo:
- [tree_service.py](/C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/tree_service.py:14)

Rol:
- normalizar un `FeatureCollection` de puntos;
- inferir diámetro;
- clasificar tamaño;
- agregar propiedades de estilo;
- devolver estadísticas simples.

Es un flujo aislado. No depende de raster ni de Supabase.

## 11. Flujo completo: carga de ortomosaico

### Secuencia

1. Cliente llama `POST /orthomosaics/upload`.
2. `routes.py` lee `UploadFile`, `capture_date`, `sensor_type`, `cycle_id`.
3. Llama `OrthomosaicApplicationService.upload_orthomosaic`.
4. `RasterService.validate_uploaded(content)` valida integridad TIFF.
5. `SupabaseService.upload_orthomosaic(...)` persiste archivo y registro.
6. Si `activate=true`, Supabase activa ese registro y sincroniza el raster.
7. `RasterService.analyze_uploaded(...)` genera análisis preliminar.
8. Respuesta HTTP devuelve:
   - `orthomosaic`
   - `analysis`

### Nodos

- `POST /orthomosaics/upload`
- `OrthomosaicApplicationService.upload_orthomosaic`
- `RasterService.validate_uploaded`
- `SupabaseService.upload_orthomosaic`
- `SupabaseService.activate_orthomosaic_record`
- `RasterService.analyze_uploaded`

## 12. Flujo completo: activación de ortomosaico

### Secuencia

1. Cliente llama `POST /orthomosaics/{id}/activate` o envía `orthomosaic_id` en otra ruta.
2. `ensure_orthomosaic(id)` se ejecuta.
3. `OrthomosaicApplicationService.activate_orthomosaic(id)`.
4. `SupabaseService.activate_orthomosaic(id, raster)`.
5. El estado activo en `RasterService` queda actualizado:
   - `active_path`
   - `sensor`
   - caches relacionadas

### Impacto

Este flujo es transversal. Muchas rutas lo usan antes de calcular índices, bounds o prescripciones.

## 13. Flujo completo: ROI y análisis de índice

### Crear ROI

1. Cliente llama `POST /rois`.
2. `routes.py` valida el `geojson` con `payload_geometry`.
3. `RoiApplicationService.create_roi(...)`.
4. `SupabaseService.create_roi(...)`.

### Consultar índice ROI

1. Cliente llama `POST /roi_ndvi` o `POST /roi_indices/{name}`.
2. `ensure_orthomosaic(...)` activa raster si hace falta.
3. `payload_geometry` convierte el ROI a `shapely`.
4. `RasterService.roi_ndvi(...)` o `roi_vegetation_index(...)`.
5. Respuesta incluye:
   - matriz;
   - máscara;
   - rango real;
   - bounds.

### Guardar análisis ROI

1. Cliente llama `POST /rois/{roi_id}/analyses`.
2. Se obtiene ROI persistido desde Supabase.
3. Se activa el ortomosaico.
4. Se resuelve la geometría.
5. `RoiApplicationService.save_roi_analysis(...)`.
6. Si el frontend envió stats, se normalizan.
7. Si no, se recalculan desde raster.
8. `SupabaseService.save_roi_analysis(...)`.
9. `routes.py` compara stats enviadas vs persistidas.

## 14. Flujo completo: recorte

### Recorte visual base

1. Cliente llama `POST /recortar`.
2. `ensure_orthomosaic(...)`.
3. `payload_geometry(...)`.
4. `RasterService.crop(geom)`.
5. El servicio genera `recorte_overlay.png`.
6. Devuelve `overlay_path` + bounds.

### Recorte con tiles descargables

1. Cliente llama `POST /crop_tiles`.
2. `RasterService.begin_crop_tiles(geom)`.
3. El servicio registra la geometría en `crop_geometries`.
4. Devuelve `crop_id`.
5. Luego el frontend usa:
   - `GET /tiles/crop/...`
   - `GET /tiles/crop-index/...`
   - `GET /crop_tiles/{crop_id}/download`

## 15. Flujo completo: zonificación

Ruta:
- `POST /ndvi_zoning`

### Secuencia

1. Cliente envía:
   - `orthomosaic_id`
   - `index_name`
   - `geojson`
   - `zone_count`
   - `cell_size_m`
   - `grid_angle_deg`
   - `classification_method`
   - `cell_value_mode`
   - `manual_breaks`
   - `detail_level`
   - `analysis_min`
   - `analysis_max`

2. `routes.py` valida tipos numéricos.
3. `payload_geometry` construye geometría `shapely`.
4. `ensure_orthomosaic(...)`.
5. `RasterService.ndvi_zoning_map(...)`.
6. Internamente llama `_prepare_index_classification(...)`.
7. Ese bloque:
   - calcula índice por pixel;
   - enmascara por ROI;
   - agrega a celdas;
   - clasifica según cuantiles, intervalos iguales o manual;
   - regulariza zonas por `detail_level`;
   - arma leyenda, histogramas y thresholds.
8. Genera artifact raster PNG/TIF para tiles.
9. Devuelve metadata de zonificación.

### Salidas

- `zoning_id`
- `tile_url`
- `bounds`
- `legend`
- `histogram`
- `thresholds`

## 16. Flujo completo: prescripción

Ruta:
- `POST /prescriptions`

### Secuencia HTTP

1. Cliente envía todo lo de zonificación más `doses`.
2. `routes.py` valida payload.
3. `ensure_orthomosaic(...)`.
4. `payload_geometry(...)`.
5. `RasterService.prescription_map_with_doses(...)`.

### Secuencia dentro de RasterService

1. `_prepare_index_classification(...)` genera la base espacial.
2. Se construye matriz RGBA por clase.
3. `_render_classification_artifact(...)` guarda:
   - PNG para vista estática;
   - TIF para servir tiles de prescripción.
4. Se clona `legend`.
5. Si llegaron `doses`:
   - valida longitud;
   - convierte a `float`;
   - asigna `zone["dosage"]`.
6. Si no llegaron:
   - usa `0.0`.
7. `_save_prescription_geojson(...)` construye JSON final.

### JSON de prescripción

Campos principales:

- `cellSize`
- `columns`
- `rows`
- `dataType`
- `dataTypeLevel`
- `guid`
- `originLat`
- `originLng`
- `originEndLat`
- `originEndLng`
- `rotation`
- `weightData`
- `workType`

### Regla actual de exportación para EAVision

La app conserva la dosis capturada por el usuario en la leyenda interna, pero al exportar JSON:

- `dataTypeLevel.dosage` se escala con `0.1x`.

Motivo:
- EAVision estaba interpretando el `dosage` del JSON con un factor 10x.
- Ejemplo:
  - dosis capturada: `12`
  - dosis exportada en JSON: `1.2`
  - lectura esperada en EAVision: `12`

### Descarga

1. El JSON se escribe en `output_dir/prescriptions/{id}.json`.
2. Se expone por `GET /prescriptions/{artifact_id}/download.json`.

## 17. Flujo completo: tiles de prescripción

1. El frontend pide `GET /tiles/prescription/{artifact_id}/{z}/{x}/{y}.png`.
2. `RasterService.prescription_tile(...)` abre el TIF exportado.
3. Reproyecta al tile XYZ exacto en EPSG:3857.
4. Devuelve PNG RGBA.

## 18. Dependencias entre módulos

### Dependencias de alto nivel

- `routes.py` depende de:
  - `RasterService`
  - `SupabaseService`
  - `OrthomosaicApplicationService`
  - `RoiApplicationService`
  - `TreeService`

- `OrthomosaicApplicationService` depende de:
  - `RasterService`
  - `SupabaseService`

- `RoiApplicationService` depende de:
  - `RasterService`
  - `SupabaseService`

- `SupabaseService` depende de:
  - `Settings`
  - `RasterService` durante activación

- `TreeService` no depende de otros servicios internos.

## 19. Estado compartido importante

Para un diagrama conviene marcar que el backend no es completamente stateless.

### Estado vivo en memoria

- raster activo;
- sensor activo;
- overlay/cache de raster;
- recortes registrados en `crop_geometries`.

### Implicaciones

- cambiar de ortomosaico modifica el contexto de trabajo posterior;
- muchas rutas dependen del ortomosaico activo o lo activan implícitamente;
- los `crop_id` y algunos artifacts viven en disco/memoria local.

## 20. Artefactos físicos generados

### En disco

- `static/recorte_overlay.png`
- `static/prescriptions/{id}.png`
- `static/prescriptions/{id}.tif`
- `static/prescriptions/{id}.json`
- tiles cacheados en `cache/`

### En Supabase

- registros de ciclos agrícolas;
- registros de ortomosaicos;
- ROI;
- análisis persistidos;
- objetos de bucket si `orthomosaic_storage_mode = supabase`

## 21. Qué debe mostrar un diagrama útil

### Diagrama 1: arquitectura estática

Nodos mínimos:

- Client / Frontend
- FastAPI routes
- OrthomosaicApplicationService
- RoiApplicationService
- RasterService
- SupabaseService
- TreeService
- Static output dir
- Cache dir
- Supabase DB
- Supabase Storage

### Diagrama 2: secuencia de prescripción

Pasos:

1. Frontend -> `POST /prescriptions`
2. Routes -> `ensure_orthomosaic`
3. Routes -> `payload_geometry`
4. Routes -> `RasterService.prescription_map_with_doses`
5. RasterService -> `_prepare_index_classification`
6. RasterService -> `_render_classification_artifact`
7. RasterService -> `_save_prescription_geojson`
8. RasterService -> `static/prescriptions/*.json|*.png|*.tif`
9. Routes -> JSON response

### Diagrama 3: secuencia de análisis ROI

Pasos:

1. Frontend -> `POST /roi_indices/{name}`
2. Routes -> `ensure_orthomosaic`
3. Routes -> `payload_geometry`
4. Routes -> `RasterService.roi_vegetation_index`
5. Routes -> response con matrix/mask/range/bounds

## 22. Resumen corto para agente generador de diagrama

El backend tiene un router FastAPI que orquesta dos tipos de servicios:

- servicios de aplicación para reglas de negocio y persistencia;
- servicios base para geoprocesamiento y almacenamiento.

`RasterService` es el núcleo del procesamiento espacial. `SupabaseService` es el núcleo de persistencia. `routes.py` conecta HTTP con ambos. La prescripción nace de una clasificación espacial del índice dentro de un ROI, se renderiza como PNG/TIF, y luego se exporta como JSON tipo Pix4D ajustado para compatibilidad con EAVision.

## 23. Prompt sugerido para otro agente

Usa este sistema de nodos y relaciones para crear el diagrama:

- `Frontend -> FastAPI routes`
- `FastAPI routes -> OrthomosaicApplicationService`
- `FastAPI routes -> RoiApplicationService`
- `FastAPI routes -> RasterService`
- `FastAPI routes -> TreeService`
- `OrthomosaicApplicationService <-> SupabaseService`
- `OrthomosaicApplicationService <-> RasterService`
- `RoiApplicationService <-> SupabaseService`
- `RoiApplicationService <-> RasterService`
- `RasterService -> static/`
- `RasterService -> cache/`
- `SupabaseService -> Supabase DB`
- `SupabaseService -> Supabase Storage`

Y dibuja tres secuencias:

1. carga/activación de ortomosaico;
2. ROI + cálculo de índice;
3. prescripción + exportación JSON.
