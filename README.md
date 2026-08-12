# GeoField Dashboard

Aplicación geoespacial para visualización y análisis de ortomosaicos RGB y multiespectrales, con flujo de ROI, cálculo de índices, histogramas interactivos, guardado de estadísticas y dashboard comparativo por vuelo.

## Qué hace la aplicación

GeoField Dashboard permite:

- Cargar ortomosaicos RGB o multiespectrales.
- Visualizar capas sobre mapa con Leaflet.
- Dibujar un ROI y trabajar solo sobre esa zona.
- Calcular índices espectrales:
  - `NDVI`
  - `NDWI`
  - `NDRE`
- Ajustar rangos mínimos y máximos desde el histograma.
- Ver estadísticas dinámicas del índice filtrado:
  - mínimo
  - máximo
  - promedio
  - mediana
  - desviación estándar
  - percentiles `P10`, `P25`, `P75`, `P90`
  - píxeles válidos
- Guardar resultados por ROI y por vuelo.
- Consultar un dashboard comparativo con trazabilidad histórica.
- Importar geometrías y detecciones arbóreas.

## Estructura del proyecto

```text
Geofield_dashboard/
├── BE/                      Backend FastAPI
│   ├── app.py
│   ├── requirements.txt
│   ├── geofield/
│   │   ├── app_factory.py
│   │   ├── config.py
│   │   ├── api/routes.py
│   │   └── services/
│   │       ├── application_service.py
│   │       ├── raster_service.py
│   │       ├── supabase_service.py
│   │       └── tree_service.py
│   ├── sql/
│   │   ├── 001_create_rois.sql
│   │   └── 002_create_roi_analyses.sql
│   └── tests/
├── FE/                      Frontend React + Vite + TypeScript
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── components/
│       ├── hooks/
│       ├── services/
│       ├── utils/
│       └── styles.css
├── GeoField-Dashboard-Demo.html
├── gra.jpg
└── README.md
```

## Stack

### Frontend

- React 18
- TypeScript
- Vite
- Leaflet
- `@geoman-io/leaflet-geoman-free`
- `@tabler/icons-react`
- `nouislider`
- `pnpm`

### Backend

- FastAPI
- Uvicorn
- Rasterio
- Shapely
- PyProj
- NumPy
- Pillow
- Matplotlib
- Supabase Python client
- python-dotenv

## Arquitectura funcional

### Frontend

El frontend se encarga de:

- renderizar el mapa;
- manejar la interacción del usuario;
- mostrar ROI, histogramas, estadísticas y dashboard;
- consumir el backend vía HTTP;
- representar resultados por índice;
- administrar el flujo visual de comparación entre vuelos.

Puntos clave del frontend:

- [FE/src/hooks/useDashboardMap.ts](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/FE/src/hooks/useDashboardMap.ts)
  Estado principal del mapa, capas, ROI, índices y overlays.
- [FE/src/services/api.ts](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/FE/src/services/api.ts)
  Contrato HTTP con el backend.
- [FE/src/components/ControlPanel.tsx](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/FE/src/components/ControlPanel.tsx)
  Panel de índices, histogramas y estadísticas.
- [FE/src/components/RoiComparisonDialog.tsx](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/FE/src/components/RoiComparisonDialog.tsx)
  Dashboard comparativo por índice.

### Backend

El backend se encarga de:

- procesar ortomosaicos;
- generar bounds y tiles;
- calcular índices por raster completo o por ROI;
- recortar ROI;
- persistir ROI y análisis;
- guardar y recuperar estadísticas desde Supabase;
- preparar datos para comparación entre vuelos.

Puntos clave del backend:

- [BE/geofield/api/routes.py](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/api/routes.py)
  Endpoints HTTP.
- [BE/geofield/services/raster_service.py](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/raster_service.py)
  Procesamiento raster e índices.
- [BE/geofield/services/supabase_service.py](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/services/supabase_service.py)
  Persistencia de ROI, análisis y ortomosaicos.
- [BE/geofield/config.py](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/geofield/config.py)
  Configuración por entorno.

## Flujo principal de uso

1. Se levanta el backend.
2. Se levanta el frontend.
3. El usuario abre la app en `http://localhost:3000`.
4. Carga un ortomosaico o usa uno ya disponible.
5. El backend calcula información base del raster.
6. El frontend muestra RGB sobre mapa.
7. El usuario selecciona `NDVI`, `NDWI` o `NDRE`.
8. La app calcula el índice seleccionado.
9. Se pinta el color map.
10. Se muestran estadísticas e histograma.
11. El usuario puede mover sliders de rango mínimo/máximo.
12. La tabla dinámica se actualiza con los píxeles válidos.
13. Si desea, guarda las estadísticas.
14. El dashboard comparativo consulta los registros persistidos y los muestra por índice.

## Índices implementados

Actualmente el flujo soporta:

- `NDVI`
- `NDWI`
- `NDRE`

Comportamiento esperado:

- ningún índice se calcula automáticamente al abrir la app;
- el cálculo ocurre solo cuando el usuario activa ese índice;
- el ROI no debe activar índices por sí solo;
- cada índice tiene su propio color map;
- cada índice tiene su propio histograma;
- cada índice tiene sus propias estadísticas;
- cada índice tiene su propio dashboard comparativo.

## Requisitos para desarrollo local

### Software recomendado

- Windows 10 u 11
- Git
- Python `3.11+`
- Node.js `18+`
- Corepack habilitado
- `pnpm`

### Verificar versiones

```powershell
python --version
node --version
corepack --version
```

Si `pnpm` no está activo:

```powershell
corepack enable
```

## Configuración local

### 1. Clonar o abrir el proyecto

Si ya tienes la carpeta local, trabaja desde:

```powershell
C:\Users\Geo\Desktop\DESARROLLO\Geofield_dashboard
```

### 2. Variables de entorno

No subas archivos `.env` al repositorio.

Este proyecto usa variables de entorno para backend y frontend. Deben existir solo en tu entorno local.

### Backend

El backend carga por defecto:

- `BE/.env`

Variables disponibles:

| Variable | Uso | Valor por defecto |
| --- | --- | --- |
| `PORT` | Puerto del backend | `8005` |
| `RASTER_PATH` | Ruta absoluta a un raster inicial | auto-detecta `LA_GARZA.tif` si existe |
| `FRONTEND_ORIGINS` | Orígenes permitidos por CORS | `http://localhost:3000,http://localhost:5173` |
| `SUPABASE_URL` | URL de Supabase | vacío |
| `SUPABASE_SERVICE_ROLE_KEY` | clave service role | vacío |
| `SUPABASE_BUCKET` | bucket de ortomosaicos | `orthomosaics` |
| `ORTHOMOSAIC_STORAGE_MODE` | `local` o modo persistente | `local` |

Ejemplo de `BE/.env` local:

```dotenv
PORT=8005
FRONTEND_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_SERVICE_ROLE_KEY=tu_service_role_key
SUPABASE_BUCKET=orthomosaics
ORTHOMOSAIC_STORAGE_MODE=local
```

Si quieres fijar un raster local por defecto:

```dotenv
RASTER_PATH=C:\ruta\completa\mi_ortomosaico.tif
```

### Frontend

Variable usada por Vite:

- `VITE_BACKEND_URL`

Valor por defecto del frontend si no se define:

- `http://127.0.0.1:8005`

Ejemplo de `FE/.env.local`:

```dotenv
VITE_BACKEND_URL=http://127.0.0.1:8005
```

## Cómo ejecutar la app en local

## Backend

### 1. Crear entorno virtual

Desde `BE/`:

```powershell
cd BE
python -m venv .venv
```

### 2. Activar entorno virtual

```powershell
.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea scripts:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.venv\Scripts\Activate.ps1
```

### 3. Instalar dependencias

```powershell
pip install -r requirements.txt
```

### 4. Levantar backend

```powershell
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8005
```

Backend disponible en:

- `http://127.0.0.1:8005`

Health check esperado:

- `GET http://127.0.0.1:8005/health`

## Frontend

### 1. Instalar dependencias

Desde `FE/`:

```powershell
cd FE
corepack pnpm install
```

### 2. Levantar frontend

```powershell
corepack pnpm run dev
```

Frontend disponible en:

- `http://localhost:3000`

## Arranque rápido en dos terminales

### Terminal 1

```powershell
cd C:\Users\Geo\Desktop\DESARROLLO\Geofield_dashboard\BE
.venv\Scripts\Activate.ps1
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8005
```

### Terminal 2

```powershell
cd C:\Users\Geo\Desktop\DESARROLLO\Geofield_dashboard\FE
corepack pnpm install
corepack pnpm run dev
```

## Base de datos y Supabase

La app puede funcionar con archivos locales, pero el flujo de ROI/análisis comparativos depende de Supabase cuando quieres persistencia real.

### Scripts SQL disponibles

- [BE/sql/001_create_rois.sql](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/sql/001_create_rois.sql)
- [BE/sql/002_create_roi_analyses.sql](C:/Users/Geo/Desktop/DESARROLLO/Geofield_dashboard/BE/sql/002_create_roi_analyses.sql)

### Qué debes ejecutar en Supabase

1. Crear las tablas y objetos para ROI.
2. Crear las tablas y objetos para análisis guardados.

Si el guardado de estadísticas falla con `502`, `422` o errores de esquema, revisa primero que esos scripts ya fueron ejecutados en la base de datos correcta.

### Variables mínimas para persistencia

```dotenv
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_SERVICE_ROLE_KEY=tu_service_role_key
```

## Endpoints relevantes

Los endpoints más usados actualmente son:

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/health` | Verifica que el backend esté arriba |
| `GET` | `/bounds` | Bounds del raster activo |
| `GET` | `/tiles/rgb/{z}/{x}/{y}.png` | Tiles RGB |
| `GET` | `/tiles/ndvi/{z}/{x}/{y}.png` | Tiles NDVI |
| `POST` | `/ortho_analysis` | Procesa ortomosaico cargado |
| `POST` | `/roi_ndvi` | NDVI por ROI |
| `POST` | `/roi_indices/{index}` | Índice por ROI (`NDVI`, `NDWI`, `NDRE`) |
| `POST` | `/recortar` | Recorte por geometría |
| `GET` | `/orthomosaics` | Lista ortomosaicos |
| `POST` | `/rois/.../analyses` | Guarda estadísticas del ROI |
| `GET` | `/rois/.../analyses` | Consulta trazabilidad/dashboard |

## Qué archivos no debes subir a GitHub

No debes versionar:

- `.env`
- `.env.local`
- `.venv`
- `venv`
- `node_modules`
- `dist`
- `uploads`
- logs
- `__pycache__`
- artefactos generados por ejecución local

Este repositorio ya incluye un `.gitignore` base para eso.

## Validaciones mínimas antes de subir cambios

### Frontend

Desde `FE/`:

```powershell
corepack pnpm run typecheck
corepack pnpm run build
```

### Backend

Si tienes el entorno activo en `BE/`:

```powershell
python -m pytest
```

Si no tienes `pytest` instalado aún como dependencia de desarrollo, al menos valida:

1. que el backend levante;
2. que `/health` responda;
3. que se pueda cargar un ortomosaico;
4. que el ROI calcule un índice;
5. que el guardado de estadísticas funcione;
6. que el dashboard recupere registros persistidos.

## Problemas comunes

### El frontend no conecta con el backend

Revisa:

- que el backend esté en `8005`;
- que `VITE_BACKEND_URL` apunte al backend correcto;
- que `FRONTEND_ORIGINS` incluya `http://localhost:3000`.

### No guarda estadísticas

Revisa:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- scripts SQL ejecutados
- estructura de tablas en Supabase

### El mapa no muestra raster

Revisa:

- que el raster exista;
- que `RASTER_PATH` sea válido si lo estás usando;
- que el backend haya calculado `/bounds`;
- que el ortomosaico tenga bandas compatibles.

### Error con PowerShell al activar el entorno virtual

Ejecuta:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### `pnpm` no existe

Ejecuta:

```powershell
corepack enable
corepack pnpm install
```

## Estado actual importante

A la fecha de este README:

- el backend local por defecto usa `8005`;
- el frontend local por defecto usa `3000`;
- el dashboard comparativo trabaja por índice;
- el guardado correcto debe tomar las estadísticas dinámicas del histograma;
- el archivo visual de referencia del dashboard existe como `GeoField-Dashboard-Demo.html`;
- la referencia visual de la gráfica existe como `gra.jpg`.

## Recomendación para GitHub

Antes de hacer el primer `commit` y `push`, revisa:

```powershell
git status
```

Confirma especialmente que no aparezcan:

- `BE/.env`
- `FE/.env.local`
- `.venv/`
- `BE/venv/`
- `node_modules/`
- `dist/`

Si alguno aparece, no lo subas.

## Licencia

Este proyecto no tiene licencia declarada en este momento. Si planeas hacerlo público, conviene definir una licencia explícita antes de distribuirlo.
