# Geofield Dashboard Backend

Backend FastAPI modular para visualización RGB/NDVI y procesamiento de GeoJSON.

## Ejecutar

```powershell
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8005
```

El raster se busca automáticamente como `tabla1.tif` o `LA_GARZA.tif`. Para indicar otro archivo:

```powershell
$env:RASTER_PATH = "C:\ruta\ortomosaico.tif"
$env:FRONTEND_ORIGINS = "http://localhost:5173,http://localhost:3000"
python -m uvicorn app:app --reload --port 8005
```

## Conectar el frontend

Configura una variable como `VITE_BACKEND_URL=http://localhost:8005` y usa:

```javascript
const API_URL = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8005";
fetch(`${API_URL}/bounds`);
const rgbUrl = `${API_URL}/tiles/rgb/{z}/{x}/{y}.png`;
const ndviUrl = `${API_URL}/tiles/ndvi/{z}/{x}/{y}.png?low=-0.05&high=1`;
```

La documentación interactiva queda disponible en `/docs` y el endpoint `/health` sirve para comprobar la conexión.
