# AGENTS.md — Contexto y reglas del frontend

## Propósito

Este directorio es el frontend de Geofield Dashboard: una SPA React/TypeScript con Vite y Leaflet para explorar capas geoespaciales, NDVI y detecciones arbóreas. Un agente de IA que trabaje aquí debe tratar el mapa como el núcleo del producto y preservar el contrato con el backend.

## Contexto operativo

- Directorio raíz del frontend: este directorio.
- Servidor local: `pnpm dev`, puerto `3000`, host `0.0.0.0`.
- Backend por defecto: `http://127.0.0.1:8002`.
- Variable configurable: `VITE_BACKEND_URL` en `.env.local`.
- No hay tests automatizados configurados; los checks mínimos son `pnpm typecheck` y `pnpm build`.
- El proyecto usa ESM (`"type": "module"`) y TypeScript.

## Mapa mental del código

- `src/components/MapView.tsx`: composición de la vista, input GeoJSON, barra de acciones, panel y swipe.
- `src/hooks/useDashboardMap.ts`: ciclo de vida de Leaflet, capas, estado, NDVI, ROI e importación de árboles.
- `src/components/ActionBar.tsx`: botones RGB, NDVI, árboles, etiquetas e importación.
- `src/components/ControlPanel.tsx`: estadísticas de `TreeCollection`; no debe asumir que el filtro ya tiene comportamiento.
- `src/services/api.ts`: único lugar preferido para definir o cambiar rutas HTTP.
- `src/types/geo.ts`: contrato local de las estructuras GeoJSON.
- `src/utils/tree.ts`: nombres aceptados para diámetro, umbrales y estadísticas.
- `src/styles.css`: layout a pantalla completa, panel responsive, controles Leaflet y estados visuales.
- `vite.config.ts`: proxy de `/bounds`, `/ndvi_data`, `/roi_ndvi`, `/tree_points` y `/tiles`.

## Contratos que no se deben romper

1. `/bounds` debe devolver `bounds` como dos pares `[latitud, longitud]` utilizables por `L.latLngBounds`.
2. `/ndvi_data` y `/roi_ndvi` deben devolver una matriz numérica y bounds. El hook convierte la matriz en un canvas.
3. `/roi_ndvi` recibe `{ geojson }` mediante `POST`.
4. `/tree_points` recibe `{ geojson }` y devuelve un `geojson` `FeatureCollection`.
5. Los tiles RGB deben seguir la plantilla `/tiles/rgb/{z}/{x}/{y}.png`.
6. El GeoJSON arbóreo usa puntos con coordenadas `[lon, lat]` y puede expresar diámetro como `diameter_m`, `diameter`, `dbh`, `Diameter` o `DIAMETER`.

## Reglas obligatorias para agentes

- Antes de editar, inspecciona los archivos afectados y conserva cambios existentes del usuario.
- Mantén el alcance en `FE`; no modifiques backend, dependencias instaladas o artefactos generados salvo que el usuario lo pida.
- Usa `apply_patch` para editar archivos de código y documentación.
- No agregues librerías si la funcionalidad puede resolverse con las dependencias existentes.
- No muevas lógica de Leaflet a componentes presentacionales sin una razón clara; el hook administra recursos imperativos.
- Limpia mapas, capas, listeners y referencias al desmontar efectos.
- Evita duplicar capas al volver a activar una acción; primero reutiliza la referencia existente o elimínala explícitamente.
- No uses `any` para silenciar errores. Mejora los tipos o encapsula la excepción en una integración pequeña.
- Escapa o evita interpolar datos no confiables en HTML de popups y etiquetas; cualquier cambio en esa zona debe considerar XSS.
- Mantén textos de interfaz en español y archivos UTF-8.
- No reemplaces un endpoint por una URL absoluta si debe funcionar mediante el proxy de Vite.
- No introduzcas secretos en código, `.env` versionados, README o logs.

## Proceso recomendado

1. Identificar si el cambio pertenece a UI, estado Leaflet, API, tipos o utilidades.
2. Leer el archivo objetivo y sus consumidores antes de modificarlo.
3. Implementar el cambio mínimo coherente con las responsabilidades anteriores.
4. Ejecutar `pnpm typecheck`.
5. Ejecutar `pnpm build`.
6. Si el cambio afecta mapa, capas o responsive, verificar manualmente en `pnpm dev` y revisar consola del navegador.
7. Informar archivos modificados, checks ejecutados y cualquier limitación o dependencia del backend.

## Decisiones de dominio actuales

Los umbrales de árboles son parte de la lógica existente y no deben cambiarse incidentalmente: pequeño `<= 2.5 m`, mediano `> 2.5 m` hasta `3.5 m`, grande `> 3.5 m`, desconocido si no existe un número válido. El valor mostrado en etiquetas se redondea a dos decimales.

El NDVI se pinta con una rampa local y opacidad aproximada de `0.72`; el swipe usa una posición entre `2` y `98` por ciento. Si se cambia esta lógica, documenta el impacto visual y valida tanto el estado activado como desactivado.

## Limitaciones conocidas

- El slider del panel todavía no filtra la capa de árboles.
- El histograma usa barras estáticas y no representa la distribución real.
- No existe suite de tests.
- La disponibilidad final depende de backend, tiles remotos y conectividad.

## Criterio de entrega

Un cambio está listo cuando compila sin errores, conserva las rutas y tipos documentados, no deja recursos Leaflet duplicados, mantiene la experiencia responsive y tiene una nota clara si requiere una modificación del backend.
