# Migraciones SQL

Las migraciones estan separadas por destino para evitar mezclar la base operativa actual con la base de publicacion del dashboard.

## Carpetas

- `supabase/`: migraciones de la base actual usada por Geofield para operar, guardar ROI, ortomosaicos, ciclos agricolas y analisis internos.
- `neon/`: migraciones de la base nueva de publicacion para alimentar el dashboard externo.

## Orden de ejecucion

Cada carpeta tiene numeracion independiente.

Para Supabase:

```text
BE/sql/supabase/001_...
BE/sql/supabase/002_...
BE/sql/supabase/003_...
```

Para Neon:

```text
BE/sql/neon/001_...
BE/sql/neon/002_...
BE/sql/neon/003_...
```

## Regla de arquitectura

No mezclar responsabilidades:

- Supabase/base actual: procesamiento y operacion interna de Geofield.
- Neon/base dashboard: resultados publicados para consulta externa.

El backend puede leer de la base actual y publicar hacia Neon mediante una API/caso de uso, pero Neon no debe reemplazar la base operativa.
