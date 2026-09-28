# GeoField con Docker

Esta configuración ejecuta el frontend y el backend en un solo contenedor.
Los TIFF, la caché y las prescripciones siguen en carpetas de esta PC,
montadas dentro del contenedor. Supabase conserva los registros de la app.

## Requisitos

- Docker Desktop iniciado en modo Linux containers.
- `BE/.env` con las variables de Supabase ya usadas por la app.
- Espacio libre y memoria suficientes para procesar los TIFF grandes.

## Iniciar

Desde la raíz del proyecto:

```powershell
docker compose up --build -d
```

Abrir <http://127.0.0.1:8080/>. La API también queda en ese origen;
por ejemplo <http://127.0.0.1:8080/orthomosaics>.

## Consultar y detener

```powershell
docker compose logs -f geofield
docker compose down
```

`docker compose down` detiene el contenedor y conserva los archivos en
`BE/uploads`, `BE/cache` y `BE/static`.

## Datos locales

- `BE/uploads` contiene los TIFF originales.
- `BE/cache` guarda cálculos y mosaicos temporales.
- `BE/static` guarda archivos publicados por el backend, incluidas prescripciones.

El backend reconoce las rutas antiguas de Windows guardadas en Supabase y
busca el archivo correspondiente bajo `BE/uploads`. Para usar otra PC hay que
copiar esos TIFF a su `BE/uploads`; Docker no sincroniza archivos entre PCs.
El modo de almacenamiento de ortomosaicos permanece en `local`.

El puerto del host es `8080` para convivir con el backend de desarrollo que
usa `8000`. Por defecto se publica solo en la propia PC.
