# Contexto Para Continuar - Geofield Dashboard

## Proyecto

Ruta local:
`C:\Users\Geo\Desktop\DESARROLLO\Geofield_dashboard`

Repo remoto:
`https://github.com/Eduardoesqsal/Geofield_dashboard.git`

Branch:
`main`

Ultimo commit subido:
`092dbd6 Refactor dashboard code organization`

## Estado General

Se hizo un refactor grande de modularidad en frontend y backend sin cambiar la logica funcional. El objetivo era que no hubiera archivos de codigo de mas de 1300 lineas.

Validaciones realizadas:

Backend:

```powershell
cd BE
.\venv\Scripts\python.exe -m unittest discover -s tests
```

Resultado: `73 tests OK`

Frontend typecheck:

```powershell
cd FE
corepack pnpm run typecheck
```

Resultado: OK

Frontend build:

```powershell
cd FE
corepack pnpm run build
```

Resultado: OK, con warning normal de Vite por chunk grande.

Conteo:
No hay archivos `.py`, `.ts`, `.tsx` mayores a 1300 lineas en `FE/BE`, excluyendo `node_modules`, `venv`, `dist`, `static`, `__pycache__`.

## Cambios Ya Subidos

Commit:
`092dbd6 Refactor dashboard code organization`

### Backend

Se modularizo `RasterService`:

- `BE/geofield/services/raster_service.py`
- `BE/geofield/services/raster_classification.py`
- `BE/geofield/services/raster_classification_artifacts.py`
- `BE/geofield/services/raster_classification_filters.py`
- `BE/geofield/services/raster_classification_helpers.py`
- `BE/geofield/services/raster_indices.py`
- `BE/geofield/services/raster_tiles_export.py`

Se modularizo `SupabaseService`:

- `BE/geofield/services/supabase_service.py`
- `BE/geofield/services/supabase_activation.py`
- `BE/geofield/services/supabase_orthomosaics.py`
- `BE/geofield/services/supabase_roi_analysis.py`

Se separaron rutas/schemas de prescripcion:

- `BE/geofield/api/prescription_routes.py`
- `BE/geofield/api/schemas.py`
- `BE/geofield/api/routes.py` ahora registra esas rutas.

Se dividio test grande:

- `BE/tests/test_raster_service.py`
- `BE/tests/test_raster_service_tiles.py`

Se agrego a `.gitignore`:

```gitignore
BE/static/prescriptions/
```

### Frontend

Se modularizo `useDashboardMap.ts`:

- `FE/src/hooks/useDashboardMap.ts`
- `FE/src/hooks/useDashboardMap.prescription.ts`
- `FE/src/hooks/useDashboardMap.roiActions.ts`
- `FE/src/hooks/useDashboardMap.spectralActions.ts`
- `FE/src/hooks/useDashboardMap.treeActions.ts`
- `FE/src/hooks/useDashboardMap.treeCore.ts`
- `FE/src/hooks/useDashboardMap.workspace.ts`

Se modularizo `MapView`:

- `FE/src/components/MapView.tsx`
- `FE/src/components/MapViewLibraries.tsx`

Se separo leyenda de prescripcion:

- `FE/src/components/PrescriptionDialog.tsx`
- `FE/src/components/PrescriptionLegend.tsx`

Se separo dialog comparativo ROI:

- `FE/src/components/RoiComparisonDialog.tsx`
- `FE/src/components/RoiComparisonDialog.parts.tsx`

## Estado Actual Del Workspace

Despues del commit/push quedaron cambios NO incluidos en el commit porque ya estaban o no eran parte directa del refactor:

```text
 D DATA_VECTORIAL/TEST_POL.cpg
 D DATA_VECTORIAL/TEST_POL.dbf
 D DATA_VECTORIAL/TEST_POL.prj
 D DATA_VECTORIAL/TEST_POL.qmd
 D DATA_VECTORIAL/TEST_POL.shp
 D DATA_VECTORIAL/TEST_POL.shx
 D "DATA_VECTORIAL/tabla 2.kml"
 D "DATA_VECTORIAL/tabla 3.kml"
 D DATA_VECTORIAL/test_kml.kml
 D DATA_VECTORIAL/test_kml.qmd
 M FE/src/hooks/useDashboardMap.spectral.ts
 M FE/src/utils/ndvi.ts
 M FE/tsconfig.app.tsbuildinfo
 D "OBJETIVO_ REPLICAR EL COMPORTAMIENTO DE ZONIFICACION Y _ZONE DETAIL_ DE PIX4DFIELDS.md"
 D ZONIFICACION_TECNICA.md
 D histograma.png
 D referencias_pix4d/A.png
 D referencias_pix4d/B.png
 D referencias_pix4d/C.png
 D referencias_pix4d/D.png
 D referencias_pix4d/E.png
 D referencias_pix4d/F.png
 D referencias_pix4d/G.png
 D referencias_pix4d/H.png
 D referencias_pix4d/I.png
 D referencias_pix4d/J.png
 D referencias_pix4d/K.png
 D referencias_pix4d/detallado.mp4
?? README_contexto_publicacion_dashboard.md
```

Importante:
No revertir esos cambios sin preguntar. Pueden ser cambios del usuario o previos.

## Diagnostico De Arquitectura

El proyecto ya esta mejor:

- Paso de archivos gigantes a modulos por responsabilidad.
- Backend tiene servicios mas legibles.
- Frontend esta menos concentrado.
- Tests siguen pasando.
- Es una base razonable de modular monolith.

Pero todavia NO es Clean Architecture pura.

### Riesgos Para Escalar

1. `RasterService` todavia puede conservar estado vivo como ortomosaico activo, sensor, geometrias, etc.
2. `SupabaseService` todavia mezcla infraestructura, compatibilidad y logica de datos.
3. Las rutas todavia conocen servicios concretos.
4. Falta una capa formal de casos de uso.
5. Artefactos generados dependen del filesystem local.
6. Operaciones pesadas todavia son sincronas.
7. Para multiusuario/publicacion, hay que evitar estado compartido en memoria.

## Proximo Objetivo Recomendado

Continuar con refactor evolutivo para preparar produccion/publicacion sin romper funcionalidad.

Orden recomendado:

### Fase 1: Limpiar estado del workspace

Antes de tocar mas arquitectura:

- Revisar si los borrados de `DATA_VECTORIAL`, docs, imagenes y referencias son intencionales.
- Decidir que hacer con:
  - `FE/src/hooks/useDashboardMap.spectral.ts`
  - `FE/src/utils/ndvi.ts`
  - `FE/tsconfig.app.tsbuildinfo`
  - `README_contexto_publicacion_dashboard.md`
- Evitar mezclar esos cambios con nuevos refactors.

### Fase 2: Fortalecer tests

Agregar/confirmar cobertura para:

- activar ortomosaico
- crop/ROI
- NDVI/NDWI/NDRE
- zonificacion
- prescripcion
- rutas API principales
- publicacion dashboard cuando se implemente

### Fase 3: Casos de Uso

Crear capa de aplicacion/casos de uso:

- `ActivateOrthomosaicUseCase`
- `AnalyzeRoiUseCase`
- `GenerateZoningUseCase`
- `GeneratePrescriptionUseCase`
- `PublishDashboardUseCase`

Ubicacion sugerida:
`BE/geofield/application/use_cases/`

### Fase 4: Puertos/Interfaces

Crear contratos para:

- raster repository/storage
- supabase data access
- artifact storage
- crop storage
- publication repository

Ubicacion sugerida:
`BE/geofield/application/ports/`

### Fase 5: Quitar Estado Vivo De RasterService

Meta:
Que las operaciones reciban `orthomosaic_id`, `crop_id`, `artifact_id`, paths o contexto explicito.
Evitar depender de `active_path`, `sensor`, geometrias activas globales.

### Fase 6: Storage De Artefactos

Primero mantener compatibilidad local.
Luego permitir Supabase Storage/S3.
No meter mas artefactos generados en Git.

### Fase 7: Jobs

Preparar operaciones pesadas para worker:

- zonificacion
- prescripcion
- analisis raster
- publicacion

Al inicio puede seguir sincrono, pero con interfaz que permita migrar a worker despues.

## Comandos Utiles

Backend tests:

```powershell
cd BE
.\venv\Scripts\python.exe -m unittest discover -s tests
```

Frontend typecheck:

```powershell
cd FE
corepack pnpm run typecheck
```

Frontend build:

```powershell
cd FE
corepack pnpm run build
```

Conteo de archivos largos:

```powershell
$files = rg --files FE BE | Where-Object { $_ -match '\.(ts|tsx|py)$' -and $_ -notmatch '(^|\\)(node_modules|venv|dist|static|__pycache__)(\\|$)' }
$files | ForEach-Object { [pscustomobject]@{ Lines=(Get-Content $_).Count; Path=$_ } } | Where-Object { $_.Lines -gt 1300 } | Sort-Object Lines -Descending
```

Git status:

```powershell
git status --short
```

## Nota Importante Para El Siguiente Agente

No hacer `git reset --hard`.
No revertir borrados o cambios pendientes sin preguntar.
El refactor importante ya esta en remoto en `main`.
El siguiente trabajo deberia empezar revisando el estado actual del workspace y preguntando si los borrados pendientes son intencionales.
