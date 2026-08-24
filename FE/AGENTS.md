# AGENTS.md — Contexto y reglas del frontend

## Propósito

Este directorio contiene la SPA React/TypeScript de GeoField Dashboard. El mapa es el núcleo del producto y el frontend coordina ciclos agrícolas, vuelos, ortomosaicos, ROI, análisis espectral y detecciones arbóreas. Cualquier cambio debe preservar el contrato con el backend FastAPI de `../BE`.

## Contexto operativo

- Raíz del frontend: `FE/`.
- Servidor local: `corepack pnpm run dev`.
- URL local: `http://localhost:3000`; host `0.0.0.0` y `strictPort` habilitado.
- Backend por defecto: `http://127.0.0.1:8005`.
- URL configurable: `VITE_BACKEND_URL` en `FE/.env.local`.
- Gestor de paquetes: pnpm mediante Corepack.
- El proyecto usa ESM y TypeScript estricto.
- No hay tests automatizados del frontend; los checks mínimos son `corepack pnpm run typecheck` y `corepack pnpm run build`.

## Mapa mental del código

- `src/components/MapView.tsx`: composición principal, ciclo activo, diálogos, bibliotecas de vuelos/ROI y coordinación del historial.
- `src/components/ActionBar.tsx`: accesos a vuelos, índices, ROI, detecciones, etiquetas e importación.
- `src/components/AgriculturalCycleDialog.tsx`: creación, selección y renombrado de ciclos.
- `src/components/ImportDialog.tsx`: selección de sensor y carga de ortomosaicos.
- `src/components/RoiDialog.tsx`: dibujo, importación, selección y gestión de ROI.
- `src/components/DetectionDialog.tsx`: importación, filtros, representación y edición de detecciones.
- `src/components/ControlPanel.tsx`: histogramas reales, rangos, estadísticas y acciones de análisis.
- `src/components/RoiComparisonDialog.tsx`: historial comparativo, gráficas, GeoScore, exportación y eliminación.
- `src/hooks/useDashboardMap.ts`: estado principal, ciclo de vida Leaflet y operaciones geoespaciales.
- `src/hooks/useDashboardMap.helpers.ts`: estado inicial, filtros y HTML seguro para popups.
- `src/hooks/useDashboardMap.orthomosaic.ts`: montaje/limpieza de vuelos cargados y guardados.
- `src/hooks/useDashboardMap.roi.ts`: recortes y artefactos visuales del ROI.
- `src/hooks/useDashboardMap.spectral.ts`: creación y reemplazo de capas espectrales.
- `src/services/api.ts`: única fachada preferida para tipos y llamadas HTTP.
- `src/utils/importFormats.ts`: KML, KMZ, SHP, ZIP y GeoJSON.
- `src/utils/ndvi.ts`: estadísticas y rampas de NDVI, NDWI y NDRE.
- `src/utils/tree.ts`: normalización, clasificación y filtrado de diámetros.
- `src/styles.css`: layout, responsive, controles Leaflet y estados visuales.
- `vite.config.ts`: servidor de desarrollo y proxy de rutas hacia el backend.

## Contratos que no se deben romper

1. El contexto persistente del usuario se organiza por ciclo agrícola.
2. La carga de un ortomosaico requiere archivo, sensor, fecha de captura e ID del ciclo.
3. Los bounds usados por Leaflet tienen la forma `[[sur, oeste], [norte, este]]`.
4. Los tiles RGB siguen `/tiles/rgb/{z}/{x}/{y}.png`; los índices completos usan `/tiles/index/{name}/{z}/{x}/{y}.png`.
5. Los recortes usan un `crop_id` y las plantillas `/tiles/crop/...` y `/tiles/crop-index/...`.
6. NDVI, NDWI y NDRE pueden estar visibles al mismo tiempo y conservan estados/rangos independientes.
7. Dibujar o seleccionar un ROI no debe activar índices automáticamente.
8. Un análisis persistido debe quedar asociado al ROI, ortomosaico, ciclo e índice correctos.
9. Las comparaciones deben solicitar datos sin caché para reflejar eliminaciones recientes.
10. El GeoJSON arbóreo usa puntos `[lon, lat]`; la interpretación de diámetros pertenece a `utils/tree.ts`.
11. Los valores no confiables usados en popups o etiquetas deben escaparse.
12. Al salir de un ciclo se debe limpiar el espacio de trabajo completo del mapa.

## Reglas obligatorias para agentes

- Antes de editar, inspecciona los archivos afectados y conserva cambios existentes del usuario.
- Mantén el alcance en `FE` salvo que el usuario pida expresamente cambios coordinados en backend.
- Usa `apply_patch` para editar código y documentación.
- No edites `dist`, archivos `*.tsbuildinfo`, logs, `node_modules` ni otros artefactos generados.
- No agregues librerías si la funcionalidad se resuelve con las dependencias existentes.
- Mantén las operaciones imperativas de Leaflet en el hook o en sus módulos auxiliares, no en componentes presentacionales.
- Limpia mapas, capas, panes, controles, listeners y referencias al desmontar o cambiar de contexto.
- Evita duplicar capas al reactivar una acción; reutiliza o elimina explícitamente la referencia anterior.
- No reduzcas la selección espectral a una sola capa: el diseño vigente admite varias capas activas.
- No uses `any` para ocultar errores de tipos.
- No interpolar datos no confiables directamente en HTML.
- Mantén textos de interfaz en español y archivos UTF-8.
- Define o modifica rutas HTTP exclusivamente en `src/services/api.ts` y sincroniza el proxy cuando corresponda.
- No introduzcas secretos en código, archivos `.env` versionados, documentación o logs.

## Proceso de trabajo

1. Identifica si el cambio pertenece a UI, estado React, recursos Leaflet, API, tipos o utilidades.
2. Lee el archivo objetivo y sus consumidores antes de modificarlo.
3. Comprueba si la acción depende de ciclo, ortomosaico o ROI activos.
4. Implementa el cambio mínimo compatible con las responsabilidades existentes.
5. Ejecuta `corepack pnpm run typecheck`.
6. Ejecuta `corepack pnpm run build`.
7. Si afecta mapa, capas, diálogos o responsive, valida manualmente con `corepack pnpm run dev` y revisa la consola del navegador.
8. Informa archivos modificados, checks ejecutados y cualquier dependencia del backend o Supabase.

## Decisiones de dominio vigentes

- Índices espectrales disponibles: `NDVI`, `NDWI` y `NDRE`.
- Sensores: `mavic3m`, `micasense`, `mavic3rgb` y `rgb`.
- `mavic3m` y `micasense` se tratan como multiespectrales; `mavic3rgb` y `rgb`, como RGB.
- Árbol pequeño: diámetro `<= 2.5 m`.
- Árbol mediano: diámetro `> 2.5 m` y `<= 3.5 m`.
- Árbol grande: diámetro `> 3.5 m`.
- Árbol desconocido: sin diámetro numérico válido.
- El swipe se limita al intervalo de `2` a `98` por ciento.
- Los rangos espectrales actualizan tanto la representación como las estadísticas que se guardan.

## Limitaciones conocidas

- No hay suite de pruebas automatizadas del frontend.
- Persistencia, biblioteca e historial requieren backend y esquema Supabase compatibles.
- No existe autenticación ni aislamiento de información por usuario.
- Las capas base de Esri requieren conectividad del navegador.
- El estado no persistido del mapa se pierde al salir del ciclo o recargar.

## Criterio de entrega

Un cambio está listo cuando compila sin errores, conserva los contratos documentados, no deja recursos Leaflet duplicados, respeta el contexto del ciclo agrícola, mantiene la experiencia responsive y documenta cualquier cambio requerido en backend o Supabase.
