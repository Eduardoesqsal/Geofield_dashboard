# Geofield Dashboard — Handoff técnico

Actualizado: 2026-08-03

## Objetivo del producto

Dashboard React + Leaflet para cargar ortomosaicos, visualizar RGB e índices, guardar ROI en Supabase, recortar por ROI y comparar vuelos por fecha.

## Ejecución local

```powershell
# Backend
cd BE
python app.py
# http://127.0.0.1:8005

# Frontend
cd FE
npm run dev
# http://127.0.0.1:3000
```

Vite usa `FE/vite.config.js` y envía las rutas de API al backend 8005. Si se modifica `vite.config.ts`, actualizar también el archivo `.js` o reiniciar Vite con la configuración correcta.

## Arquitectura

- `FE/src/components/MapView.tsx`: composición de modales, biblioteca de ortomosaicos y ROI.
- `FE/src/hooks/useDashboardMap.ts`: capas Leaflet, dibujo/importación ROI, tiles RGB/índices y estado del mapa.
- `FE/src/components/ControlPanel.tsx`: histogramas y estadísticas; los sliders recalculan estadísticas filtradas en cliente.
- `FE/src/services/api.ts`: contrato HTTP del frontend.
- `BE/geofield/api/routes.py`: API FastAPI.
- `BE/geofield/services/raster_service.py`: lectura Rasterio, cálculos NDVI/NDWI/NDRE y tiles PNG.
- `BE/geofield/services/supabase_service.py`: ortomosaicos, ROI e historial de análisis.

## Puertos y procesos

- Backend: `8005`.
- Frontend Vite: `3000`.
- Para localizar procesos en Windows: `netstat -ano | Select-String ':8005'` o `':3000'`.
- No dejar procesos duplicados; Vite usa `strictPort: true`.

## Funciones implementadas

### Ortomosaicos

- Modal de carga limitado a ortomosaicos con selección de sensor.
- Tabla de ortomosaicos guardados, activación/desactivación y eliminación.
- Tiles RGB: `/tiles/rgb/{z}/{x}/{y}.png`.
- Índices completos: `/tiles/index/{name}/{z}/{x}/{y}.png`.

### ROI

- Dibujo de polígono y carga múltiple de archivos geométricos.
- Cada polígono de un archivo se guarda como ROI independiente en la tabla `rois`.
- Los ROI nuevos se guardan con `orthomosaic_id = null`: son reutilizables entre vuelos.
- Biblioteca de ROI con selección y eliminación.
- Al seleccionar/cerrar una ROI aparece una tijera; al pulsarla se crea el recorte.

### Recortes y tiles

- `POST /crop_tiles` registra una geometría de recorte en memoria.
- `GET /tiles/crop/{crop_id}/{z}/{x}/{y}.png` entrega RGB de 512×512 enmascarado por ROI.
- `GET /tiles/crop-index/{name}/{crop_id}/{z}/{x}/{y}.png` entrega índice enmascarado por ROI.
- Los `crop_id` son de sesión: se pierden si reinicia backend; seleccionar ROI y pulsar tijera crea uno nuevo.

### Índices y histogramas

- Índices disponibles: NDVI, NDWI y NDRE.
- NDVI MicaSense esperado para este proyecto: `(B6 NIR - B4 Red) / (B6 NIR + B4 Red)`.
- El usuario confirmó el orden MicaSense de su archivo:
  1. Blue
  2. Green
  3. Panchromatic
  4. Red
  5. Red edge
  6. NIR
  7. Alpha
- En `raster_service.py`, `_ndvi_bands()` detecta descripciones y usa para MicaSense B4/B6 cuando hay 6+ bandas; para RedEdge-MX de 5 bandas usa B3/B4.
- El panel mantiene histograma fijo y recalcula cantidad, promedio, mediana, desviación estándar y percentiles al mover sliders.

## Persistencia y comparativa

Migraciones:

- `BE/sql/001_create_rois.sql`: tabla `rois`.
- `BE/sql/002_create_roi_analyses.sql`: tabla histórica `roi_analyses`.

**Pendiente de usuario:** ejecutar `002_create_roi_analyses.sql` en Supabase SQL Editor.

API ya creada:

- `POST /rois/{roi_id}/analyses` guarda estadísticas zonales por ROI y ortomosaico.
- `GET /rois/{roi_id}/analyses` devuelve historial con relación a ortomosaico.

Frontend implementado:

- el hook conserva el `roi_id` del ROI seleccionado, dibujado o importado;
- el panel NDVI zonal permite guardar estadísticas para el ortomosaico activo;
- el guardado usa una medición completa por combinación `ROI + ortomosaico`;
- el modal de comparación muestra fecha, vuelo, promedio NDVI, desviación estándar, cambio frente al vuelo anterior y píxeles válidos.

## Rampa NDVI del ROI — resuelto

La causa era el orden de bandas del render de tiles: `_ndvi_bands()` entrega `(Red, NIR)`, pero `index_tile()` y `crop_index_tile()` aplicaban `(primera - segunda)`, invirtiendo el signo del NDVI respecto de `roi_ndvi()`.

La implementación ahora:

- define las bandas como término positivo y negativo; NDVI usa `(NIR, Red)`;
- comparte cálculo, dominio, rampa RGBA y validación entre el índice completo y el recortado;
- conserva la misma escala global de colores; la ROI solo agrega máscara alfa;
- aplica `low`/`high` como filtro de visibilidad, sin renormalizar colores;
- incluye pruebas de regresión en `BE/tests/test_raster_service.py`.

La comparación con `LA_GARZA.tif` confirmó que todos los píxeles dentro de la ROI tienen el mismo RGBA que el tile completo correspondiente.

## Cambios de UX solicitados por usuario

- Interfaz gris oscuro, modales para importación e índices.
- No usar herramientas Geoman innecesarias (rotar/texto/etc.).
- Índices solo se activan desde botón “Índices”.
- La tijera debe ser el disparador explícito de recorte.
- ROI debe poder reutilizarse con Vuelo 1, Vuelo 2 y futuras fechas.
- Comparativa temporal por ROI es prioridad futura inmediata.

## Verificación mínima

```powershell
cd FE
npm run build

cd ..\BE
.\venv\Scripts\python.exe -m compileall -q .\geofield
```

No hay tests automatizados.

## Seguridad

- No registrar ni copiar valores de `.env` en documentación o commits.
- El proyecto contiene configuración de Supabase en `BE/.env`; preservar su contenido y no exponerlo.
