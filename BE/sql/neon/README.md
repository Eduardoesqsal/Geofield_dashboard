# Migraciones Neon

Estas migraciones se ejecutan en Neon PostgreSQL.

Neon guardara resultados publicados para el dashboard externo:

- proyectos/lotes publicados,
- analisis publicados,
- ROI,
- estadisticas NDVI, NDWI y NDRE,
- zonificacion,
- prescripcion,
- artefactos o URLs de capas,
- eventos de publicacion.

## Orden actual

1. `001_create_publication_schema.sql`

## Conexion esperada

```env
PUBLICATION_DATABASE_URL=postgresql://usuario:password@host/dbname?sslmode=require
```

## Nota

No guardar archivos binarios pesados en Neon. Guardar URLs, storage keys o metadatos en `published_artifacts`.
