# GeoField con Cloudflare Quick Tunnel

Este documento explica como levantar GeoField para pruebas externas usando un Cloudflare Quick Tunnel:

- Backend FastAPI: `http://localhost:8000`
- Frontend React/Vite: `http://localhost:5173`

La URL publica que se comparte es la del frontend. Vite proxifica las rutas API hacia el backend local.

## Requisitos

- Ejecutar los comandos desde CMD.
- Tener el entorno virtual del backend en `BE\venv`.
- Tener dependencias del frontend instaladas.
- Usar el ejecutable incluido en el proyecto: `.tools\cloudflared.exe`.

## 1. Levantar el backend

Abrir una terminal CMD:

```cmd
cd /d C:\Users\Geo\Desktop\DESARROLLO\Geofield_dashboard\BE
venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Debe quedar activo en:

```text
http://localhost:8000
```

No cierres esta terminal.

## 2. Levantar el frontend

```cmd
cd /d C:\Users\Geo\Desktop\DESARROLLO\Geofield_dashboard\FE
set VITE_API_URL=
set VITE_BACKEND_URL=
corepack pnpm run dev -- --host 0.0.0.0 --port 5173
```

Debe quedar activo en:

```text
http://localhost:5173
```

No cierres esta terminal.

## 3. Crear el tunel del frontend

Abrir otra terminal CMD:

```cmd
cd /d C:\Users\Geo\Desktop\DESARROLLO\Geofield_dashboard
.tools\cloudflared.exe tunnel --url http://localhost:5173
```

Cloudflare mostrara una URL parecida a:

```text
https://ejemplo-frontend.trycloudflare.com
```

Esta es la URL publica que debes abrir o compartir.

## Resumen de URLs

- URL para abrir GeoField: URL publica del frontend, por ejemplo `https://ejemplo-frontend.trycloudflare.com`.
- No configures `VITE_API_URL` en este modo.

## Verificacion rapida

Desde CMD puedes probar que el frontend responde:

```cmd
powershell -Command "Invoke-WebRequest -UseBasicParsing https://ejemplo-frontend.trycloudflare.com | Select-Object -ExpandProperty StatusCode"
```

Y que el proxy del frontend responde hacia el backend:

```cmd
powershell -Command "Invoke-WebRequest -UseBasicParsing https://ejemplo-frontend.trycloudflare.com/health | Select-Object -ExpandProperty StatusCode"
```

Ambos deberian devolver `200`.

## Notas

- Los Quick Tunnels cambian de URL cada vez que se reinician.
- Si aparece `Failed to fetch`, revisa que el backend este corriendo en `http://localhost:8000` y que el frontend este corriendo sin `VITE_API_URL`.
- No abras la URL del backend esperando ver el dashboard. El dashboard esta en la URL publica del frontend.
