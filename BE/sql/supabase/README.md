# Migraciones Supabase

Estas migraciones pertenecen a la base actual de Geofield.

Supabase/base actual conserva la operacion interna:

- ortomosaicos,
- ROI,
- analisis de ROI,
- ciclos agricolas,
- orden de vuelos/ortomosaicos.

## Orden actual

1. `001_create_rois.sql`
2. `002_create_roi_analyses.sql`
3. `003_create_agricultural_cycles.sql`
4. `004_link_rois_to_agricultural_cycles.sql`
5. `005_add_orthomosaic_display_order.sql`

## Nota

Las migraciones de publicacion para el dashboard externo no van aqui. Esas viven en `BE/sql/neon/`.
