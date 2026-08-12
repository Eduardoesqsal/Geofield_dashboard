# Geofield Dashboard — Frontend

Frontend web del dashboard geoespacial de Geofield. La aplicación presenta una vista de mapa a pantalla completa para consultar una ortofoto/RGB, visualizar un índice NDVI, importar detecciones de árboles en GeoJSON y analizar sus diámetros.

## Estado del proyecto

Este repositorio contiene únicamente el frontend. El mapa necesita un backend compatible para cargar los límites del proyecto, los datos NDVI, procesar las detecciones de árboles y servir los tiles RGB.

La interfaz actualmente permite:

- Cargar y ajustar el mapa RGB a los límites entregados por el backend.
- Activar y desactivar la capa NDVI.
- Dibujar un polígono ROI con Leaflet-Geoman y solicitar el NDVI de esa zona.
- Importar un `FeatureCollection` GeoJSON de puntos de árboles.
- Clasificar visualmente los árboles por diámetro: pequeño, mediano, grande o sin diámetro.
- Mostrar u ocultar etiquetas de diámetro.
- Abrir un panel con estadísticas básicas de las detecciones.
- Comparar RGB y NDVI mediante un divisor vertical tipo swipe.

## Stack

- React 18
- TypeScript 5
- Vite 6
- Leaflet 1.9
- Leaflet-Geoman Free para dibujo y edición de ROI
- noUiSlider (dependencia disponible para controles de rango)
- pnpm como gestor recomendado, debido a la presencia de `pnpm-lock.yaml`

## Requisitos

- Node.js compatible con Vite 6 (se recomienda Node.js 20 LTS o superior).
- pnpm instalado y disponible en el `PATH`.
- Backend de Geofield ejecutándose, por defecto, en `http://127.0.0.1:8005`.

## Instalación y ejecución

```bash
pnpm install
pnpm dev
```

La aplicación queda disponible en `http://localhost:3000`. El servidor de desarrollo escucha en `0.0.0.0` y usa `strictPort`, por lo que fallará si el puerto 3000 ya está ocupado.

Para apuntar a otro backend, crea un archivo `.env.local` en la raíz:

```dotenv
VITE_BACKEND_URL=http://127.0.0.1:8005
```

Después de cambiar variables de entorno, reinicia Vite.

## Comandos

| Comando | Propósito |
| --- | --- |
| `pnpm dev` | Inicia Vite en el puerto 3000. |
| `pnpm build` | Ejecuta la compilación TypeScript incremental y genera `dist/`. |
| `pnpm typecheck` | Ejecuta TypeScript sin emitir archivos. |
| `pnpm preview` | Sirve localmente la compilación de `dist/`. |

No hay una suite de tests automatizados configurada actualmente. Toda modificación debe validarse al menos con `pnpm typecheck` y `pnpm build`.

## Arquitectura

```text
src/
├── App.tsx                         Punto de entrada visual; monta MapView.
├── main.tsx                        Bootstrap de React y hojas de estilo externas.
├── styles.css                      Estilos globales y responsive del dashboard.
├── components/
│   ├── ActionBar.tsx               Acciones flotantes del mapa.
│   ├── ControlPanel.tsx             Estadísticas e histograma de árboles.
│   └── MapView.tsx                  Composición de mapa, controles y eventos de UI.
├── hooks/
│   └── useDashboardMap.ts           Estado, ciclo de vida de Leaflet y operaciones geoespaciales.
├── services/
│   └── api.ts                       Cliente HTTP tipado del backend.
├── types/
│   └── geo.ts                       Tipos de GeoJSON y estadísticas.
└── utils/
    └── tree.ts                      Lectura de diámetro, clasificación y estadísticas.
```

### Flujo de inicialización

1. `main.tsx` carga CSS de Leaflet, Geoman, noUiSlider y los estilos propios.
2. `App` monta `MapView`.
3. `MapView` crea el `ref` del contenedor y usa `useDashboardMap`.
4. El hook crea el mapa Leaflet, agrega la base satelital y solicita `/bounds`.
5. Cuando recibe los límites, agrega `/tiles/rgb/{z}/{x}/{y}.png` y ajusta el viewport.

### Responsabilidades

- `MapView` debe coordinar composición y eventos de UI, no contener lógica de API compleja.
- `useDashboardMap` es la fuente de verdad para el estado del mapa y sus capas Leaflet.
- `api.ts` concentra las rutas y la conversión de errores HTTP.
- `tree.ts` concentra la interpretación de propiedades de diámetro y las reglas de clasificación.
- Los componentes visuales deben recibir datos y callbacks por props siempre que sea razonable.

## Contrato esperado del backend

Vite redirige estas rutas al valor de `VITE_BACKEND_URL`:

| Método | Ruta | Respuesta/entrada |
| --- | --- | --- |
| `GET` | `/bounds` | `{ "bounds": [[south, west], [north, east]] }` |
| `GET` | `/ndvi_data` | `{ "matrix": number[][], "bounds": [[...], [...]] }`; puede incluir `mask` y `rgb_matrix`. |
| `POST` | `/roi_ndvi` | Body `{ "geojson": <GeoJSON> }`; devuelve una respuesta NDVI. |
| `POST` | `/tree_points` | Body `{ "geojson": <FeatureCollection> }`; devuelve `{ "status": string, "geojson": <FeatureCollection> }`. |
| `GET` | `/tiles/rgb/{z}/{x}/{y}.png` | Tile PNG RGB. |

Las respuestas JSON deben incluir el `Content-Type: application/json`. Si una ruta devuelve HTML, el cliente lo reporta explícitamente como un problema de URL o proxy.

## GeoJSON de árboles

La importación espera un `FeatureCollection` con geometrías `Point` y coordenadas `[longitud, latitud]`:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [-102.55, 23.63] },
      "properties": { "diameter_m": 2.4 }
    }
  ]
}
```

El diámetro se busca, en este orden, en `diameter_m`, `diameter`, `dbh`, `Diameter` y `DIAMETER`. La clasificación actual es:

- `small`: diámetro `<= 2.5` m.
- `medium`: diámetro `> 2.5` y `<= 3.5` m.
- `large`: diámetro `> 3.5` m.
- `unknown`: valor ausente o no numérico.

## Desarrollo

Al trabajar en el mapa, considera que Leaflet mantiene objetos imperativos fuera del árbol React. Las referencias `mapRef`, `orthoRef`, `ndviRef`, `treeRef` y `labelsRef` deben limpiarse o actualizarse de forma explícita para evitar capas duplicadas y fugas al desmontar.

El NDVI se transforma en un `canvas` en el navegador. La posición del swipe se aplica mediante `clipPath` sobre el `ImageOverlay`. Las etiquetas se agregan en un pane Leaflet separado con interacción desactivada.

### Limitaciones conocidas

- El control de rango del `ControlPanel` se renderiza, pero todavía no filtra las detecciones ni actualiza las capas.
- El histograma actual es visual/estático; no se calcula desde la distribución real de diámetros.
- La base RGB y las etiquetas cartográficas de Esri requieren conectividad de red del navegador y respetan sus atribuciones.
- El backend y su contrato de datos no están incluidos en este repositorio.
- La codificación de archivos debe mantenerse en UTF-8; si aparecen textos corruptos como `Ã`, hay que corregir la fuente, no ocultar el problema con reemplazos en runtime.

## Guía rápida de diagnóstico

1. Si aparece un error de HTML en vez de JSON, revisa `VITE_BACKEND_URL`, que el backend esté levantado y que la ruta esté incluida en el proxy de `vite.config.ts`.
2. Si el mapa no encaja en el proyecto, inspecciona el orden y formato de `bounds` y verifica que las coordenadas sean latitud/longitud donde Leaflet las espera.
3. Si no se muestran árboles, valida que el archivo sea JSON válido, `type` sea `FeatureCollection`, las geometrías sean puntos y el backend devuelva `geojson`.
4. Si falla el build, ejecuta primero `pnpm typecheck` para aislar errores de tipos.

## Convenciones

- Mantener TypeScript estricto y evitar `any`; si una librería Leaflet requiere una excepción, limitarla al punto de integración.
- Usar nombres y mensajes de interfaz en español, manteniendo nombres técnicos de rutas y propiedades tal como exige el backend.
- Mantener los cambios acotados al frontend y no asumir cambios en el backend sin actualizar este contrato.
- No versionar `node_modules`, `dist`, logs, secretos ni archivos `.env*` con credenciales.
