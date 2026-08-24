# GeoField Dashboard — Frontend

SPA geoespacial de GeoField para administrar ciclos agrícolas y vuelos, visualizar ortomosaicos RGB o multiespectrales, trabajar con regiones de interés (ROI), analizar índices de vegetación y revisar detecciones de árboles.

El frontend forma parte del mismo repositorio que el backend FastAPI ubicado en `../BE`. En desarrollo se ejecuta en `http://localhost:3000` y consume el backend en el puerto `8005`.

## Funcionalidad actual

La interfaz permite:

- Crear, seleccionar y renombrar ciclos agrícolas.
- Consultar la biblioteca de vuelos de un ciclo.
- Cargar ortomosaicos asociados a un ciclo, indicando sensor y fecha de captura.
- Activar un ortomosaico guardado, editar su fecha o eliminarlo.
- Visualizar ortomosaicos RGB y multiespectrales sobre Leaflet.
- Activar simultáneamente `NDVI`, `NDWI` y `NDRE`, cada uno con su propia rampa de color.
- Generar desde el histograma del ROI activo una prescripción con 2 a 10 zonas NDVI y celdas métricas configurables; inicia con 4 zonas y grilla de 3 × 3 m.
- Ajustar el rango visible de cada índice mediante histogramas calculados con datos reales.
- Dibujar, importar, guardar, seleccionar, recortar y eliminar ROI.
- Relacionar los ROI con el ciclo agrícola activo.
- Guardar estadísticas espectrales por ROI y vuelo.
- Consultar, actualizar, exportar y eliminar registros del historial comparativo.
- Comparar vuelos mediante tendencias, métricas y GeoScore.
- Importar detecciones de árboles desde GeoJSON o Shapefile.
- Filtrar detecciones por diámetro y categoría de tamaño.
- Mostrar árboles como puntos o círculos proporcionales al diámetro.
- Agregar detecciones, eliminar una detección o borrar las contenidas en un área.
- Mostrar etiquetas y comparar capas mediante un divisor vertical tipo swipe.

## Stack

- React 18
- TypeScript 5
- Vite 6
- Leaflet 1.9
- Leaflet-Geoman Free
- Tabler Icons React
- noUiSlider
- pnpm

## Requisitos y ejecución

- Node.js 20 o superior recomendado.
- Corepack y pnpm disponibles.
- Backend de GeoField ejecutándose en `http://127.0.0.1:8005`.

Desde `FE/`:

```powershell
corepack pnpm install
corepack pnpm run dev
```

Vite escucha en `0.0.0.0:3000` con `strictPort`; el arranque falla si el puerto `3000` ya está ocupado.

Para usar otro backend, crea `FE/.env.local`:

```dotenv
VITE_BACKEND_URL=http://127.0.0.1:8005
```

Si `VITE_BACKEND_URL` no está definida y la aplicación se abre en el puerto `3000`, el cliente construye la URL del backend con el mismo host y el puerto `8005`. En otros entornos usa rutas relativas.

## Comandos

| Comando | Propósito |
| --- | --- |
| `corepack pnpm run dev` | Inicia Vite en el puerto `3000`. |
| `corepack pnpm run typecheck` | Valida TypeScript sin emitir archivos. |
| `corepack pnpm run build` | Ejecuta `tsc -b` y genera la aplicación en `dist/`. |
| `corepack pnpm run preview` | Sirve localmente el contenido compilado. |

No hay una suite automatizada de pruebas del frontend. Los controles mínimos antes de entregar un cambio son `typecheck` y `build`.

## Arquitectura

```text
src/
├── App.tsx
├── main.tsx
├── styles.css
├── components/
│   ├── ActionBar.tsx
│   ├── AgriculturalCycleDialog.tsx
│   ├── ConfirmDialog.tsx
│   ├── ControlPanel.tsx
│   ├── DetectionDialog.tsx
│   ├── ImportDialog.tsx
│   ├── MapView.tsx
│   ├── RoiComparisonDialog.tsx
│   └── RoiDialog.tsx
├── hooks/
│   ├── useDashboardMap.ts
│   ├── useDashboardMap.helpers.ts
│   ├── useDashboardMap.orthomosaic.ts
│   ├── useDashboardMap.roi.ts
│   └── useDashboardMap.spectral.ts
├── services/
│   └── api.ts
├── types/
│   └── geo.ts
└── utils/
    ├── importFormats.ts
    ├── ndvi.ts
    └── tree.ts
```

### Responsabilidades principales

- `MapView.tsx`: compone la experiencia completa, controla los diálogos y coordina ciclos, biblioteca de vuelos, ROI y análisis guardados.
- `useDashboardMap.ts`: mantiene el estado geoespacial y el ciclo de vida de Leaflet, sus capas, listeners y herramientas de edición.
- `useDashboardMap.orthomosaic.ts`: monta y limpia ortomosaicos cargados o recuperados.
- `useDashboardMap.roi.ts`: aplica recortes y limpia artefactos del ROI.
- `useDashboardMap.spectral.ts`: crea y sustituye capas de índices espectrales.
- `api.ts`: contiene los tipos serializados y todas las llamadas HTTP del frontend.
- `ControlPanel.tsx`: presenta histogramas, filtros, estadísticas y acciones para guardar o comparar análisis.
- `RoiComparisonDialog.tsx`: presenta el historial por índice, tendencias, GeoScore y opciones de exportación/eliminación.
- `PrescriptionDialog.tsx`: configura las zonas y la grilla, y presenta la leyenda del mapa de prescripción.
- `importFormats.ts`: convierte KML, KMZ, SHP, ZIP y GeoJSON a colecciones GeoJSON utilizables.
- `ndvi.ts`: calcula estadísticas y colores para NDVI, NDWI y NDRE.
- `tree.ts`: normaliza diámetros, clasifica tamaños y filtra detecciones.

## Flujo de trabajo

1. El usuario selecciona o crea un ciclo agrícola.
   También puede eliminarlo con confirmación; se eliminan sus vuelos, archivos, ROI y análisis asociados.
2. Importa un ortomosaico o abre un vuelo existente en la biblioteca del ciclo. En la biblioteca puede arrastrar los vuelos para conservar un orden personalizado por ciclo.
3. El backend activa/procesa el raster y el frontend monta sus tiles y bounds.
4. El usuario activa uno o varios índices espectrales.
5. Puede trabajar sobre toda la imagen o seleccionar un ROI guardado.
6. Los rangos del histograma actualizan la visualización y las estadísticas dinámicas.
7. Con un ROI y un ortomosaico activos, puede guardar el análisis.
8. El dashboard comparativo consulta el historial del ROI para el índice seleccionado.
9. Al salir del ciclo se limpian las capas, selecciones y contexto del espacio de trabajo.
10. Para aplicación variable, el ROI debe estar recortado y su histograma NDVI abierto. Desde ese panel se configura la prescripción usando el rango visible; puede retirarse desde el mismo panel o su leyenda.

## Sensores y archivos admitidos

### Ortomosaicos

| Sensor | Modo | Formatos mostrados por la interfaz |
| --- | --- | --- |
| `mavic3m` | Multiespectral | TIFF, JP2, IMG, ZIP |
| `micasense` | Multiespectral | TIFF, JP2, IMG, ZIP |
| `mavic3rgb` | RGB | TIFF, JP2, PNG, JPG |
| `rgb` | RGB | TIFF, JP2, PNG, JPG |

### Geometrías y ROI

El importador general acepta GeoJSON/JSON, KML, KMZ, SHP y ZIP con un Shapefile. Los datos se convierten internamente a un `FeatureCollection`.

### Detecciones

El diálogo de detecciones acepta:

- GeoJSON o JSON;
- un conjunto SHP + DBF, con SHX y PRJ opcionales;
- un ZIP que contenga el Shapefile.

Las detecciones válidas son puntos con coordenadas GeoJSON `[longitud, latitud]`. El diámetro puede obtenerse de propiedades directas, radio, dimensiones de bounding box o medidas en píxeles cuando existe una escala válida. La normalización central está en `src/utils/tree.ts`.

La clasificación visual vigente es:

- pequeño: diámetro `<= 2.5 m`;
- mediano: diámetro `> 2.5 m` y `<= 3.5 m`;
- grande: diámetro `> 3.5 m`;
- desconocido: sin un número de diámetro válido.

## Contrato HTTP consumido

Las rutas se concentran en `src/services/api.ts`. Vite también las redirige al backend configurado.

| Método | Ruta | Uso principal |
| --- | --- | --- |
| `GET`, `POST` | `/agricultural_cycles` | Listar y crear ciclos. |
| `PATCH` | `/agricultural_cycles/{id}` | Renombrar un ciclo. |
| `GET` | `/orthomosaics?cycle_id=...` | Listar vuelos del ciclo. |
| `POST` | `/orthomosaics/upload` | Cargar un ortomosaico con sensor, fecha y ciclo. |
| `POST` | `/orthomosaics/{id}/activate` | Activar un vuelo guardado. |
| `PATCH`, `DELETE` | `/orthomosaics/{id}` | Editar fecha o eliminar el vuelo. |
| `GET` | `/bounds?orthomosaic_id=...` | Obtener los límites del raster. |
| `GET` | `/tiles/rgb/{z}/{x}/{y}.png` | Mostrar tiles RGB. |
| `GET` | `/tiles/index/{name}/{z}/{x}/{y}.png` | Mostrar un índice del raster completo. |
| `GET` | `/tiles/crop/{crop_id}/{z}/{x}/{y}.png` | Mostrar el recorte RGB de un ROI. |
| `GET` | `/tiles/crop-index/{name}/{crop_id}/{z}/{x}/{y}.png` | Mostrar un índice recortado. |
| `GET` | `/ndvi_data` | Obtener la matriz NDVI. |
| `GET` | `/vegetation_indices/{name}` | Obtener NDWI o NDRE. |
| `POST` | `/prescriptions` | Generar la grilla de prescripción para la geometría y el rango NDVI del ROI activo. |
| `POST` | `/roi_ndvi` | Calcular NDVI para una geometría. |
| `POST` | `/roi_indices` | Calcular todos los índices de un ROI. |
| `POST` | `/roi_indices/{name}` | Calcular un índice específico de un ROI. |
| `POST` | `/crop_tiles` | Crear los tiles de recorte de un ROI. |
| `GET`, `POST` | `/rois` | Listar o guardar ROI. |
| `PATCH`, `DELETE` | `/rois/{id}` | Cambiar estado o eliminar un ROI. |
| `GET`, `POST` | `/rois/{id}/analyses` | Consultar o guardar análisis del ROI. |
| `DELETE` | `/rois/{roi_id}/analyses/{analysis_id}` | Eliminar una observación histórica. |
| `POST` | `/tree_points` | Normalizar/procesar detecciones arbóreas. |
| `POST` | `/ortho_analysis` | Analizar un archivo raster enviado directamente. |

Los endpoints de bounds y matrices utilizan bounds Leaflet con la forma `[[sur, oeste], [norte, este]]`. Las respuestas de matrices pueden incluir `matrix`, `mask`, `rgb_matrix` y `bounds`.

## Consideraciones de implementación

- Leaflet mantiene recursos imperativos fuera del árbol React. Toda capa, listener, control y referencia debe retirarse al reemplazarse o al desmontar la vista.
- Se pueden mantener varios índices visibles a la vez; no se debe modelar el análisis espectral como una única capa exclusiva.
- Los cálculos no deben activarse automáticamente solo por dibujar un ROI.
- El contexto persistente está delimitado por el ciclo agrícola activo.
- Los análisis guardados requieren tanto un ROI seleccionado como un ortomosaico activo.
- Los popups y etiquetas deben escapar valores procedentes de archivos o del backend.
- Las rutas HTTP nuevas deben agregarse a `api.ts` y, si son relativas durante desarrollo, al proxy de `vite.config.ts`.
- Los textos visibles se mantienen en español y los archivos en UTF-8.

## Limitaciones actuales

- No existe una suite de pruebas automatizadas del frontend.
- La aplicación depende del backend FastAPI y de la configuración/esquema de Supabase para la persistencia.
- La base satelital y la capa de etiquetas de Esri requieren conectividad desde el navegador.
- El frontend no incluye autenticación ni separación de datos por usuario.
- El estado de trabajo del mapa vive en memoria y se limpia al salir del ciclo o recargar la página; solo los registros enviados al backend son persistentes.

## Diagnóstico rápido

1. Si una ruta devuelve HTML en vez de JSON, revisa `VITE_BACKEND_URL`, el puerto `8005` y el proxy de Vite.
2. Si no aparece el raster, verifica que exista un ortomosaico activo, que `/bounds` responda y que los tiles no fallen en la red.
3. Si no se habilita el guardado, confirma que haya ciclo, ortomosaico y ROI activos, y estadísticas del índice seleccionado.
4. Si no aparecen detecciones, valida el tipo `FeatureCollection`, geometrías `Point`, coordenadas `[lon, lat]` y los archivos auxiliares del Shapefile.
5. Si el build falla, ejecuta primero `corepack pnpm run typecheck` para aislar los errores de tipos.

## Archivos que no deben versionarse

No agregues credenciales, `.env.local`, `node_modules`, `dist`, logs ni archivos generados por TypeScript/Vite. Conserva el contrato con el backend y valida los cambios con los comandos indicados arriba.
