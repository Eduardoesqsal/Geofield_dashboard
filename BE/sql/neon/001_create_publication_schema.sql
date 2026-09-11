-- Esquema inicial para la base Neon que alimentara el dashboard externo.
-- Esta migracion esta pensada para ejecutarse en Neon PostgreSQL, no en la
-- base operativa actual de Geofield.

create extension if not exists pgcrypto;

create table if not exists public.published_projects (
  id uuid primary key default gen_random_uuid(),
  source_project_id text,
  name text not null,
  field_name text,
  crop_name text,
  cycle_name text,
  source_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.published_analyses (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references public.published_projects(id) on delete set null,
  source_publication_key text not null,
  source_orthomosaic_id text,
  source_roi_id text,
  source_roi_analysis_id text,
  analysis_type text not null default 'roi_prescription',
  status text not null default 'published',
  payload_version integer not null default 1,
  payload_hash text,
  published_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source_publication_key),
  check (status in ('pending', 'published', 'failed', 'updated'))
);

create table if not exists public.published_rois (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.published_analyses(id) on delete cascade,
  name text,
  geometry_geojson jsonb not null,
  area_hectares numeric,
  bounds jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.published_index_results (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.published_analyses(id) on delete cascade,
  index_name text not null,
  stats_json jsonb not null default '{}'::jsonb,
  range_min numeric,
  range_max numeric,
  created_at timestamptz not null default now(),
  unique (analysis_id, index_name),
  check (index_name in ('NDVI', 'NDWI', 'NDRE'))
);

create table if not exists public.published_zonings (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.published_analyses(id) on delete cascade,
  source_zoning_id text,
  index_name text not null,
  classification_method text,
  cell_value_mode text,
  zone_count integer,
  cell_size_m numeric,
  grid_angle_deg numeric,
  detail_level numeric,
  field_mean numeric,
  valid_cell_count integer,
  area_hectares numeric,
  thresholds_json jsonb not null default '[]'::jsonb,
  histogram_json jsonb not null default '{}'::jsonb,
  legend_json jsonb not null default '[]'::jsonb,
  zones_geojson jsonb,
  grid_geojson jsonb,
  response_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (index_name in ('NDVI', 'NDWI', 'NDRE'))
);

create table if not exists public.published_prescriptions (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.published_analyses(id) on delete cascade,
  source_prescription_id text,
  index_name text not null,
  product_name text,
  unit text,
  classification_method text,
  cell_value_mode text,
  zone_count integer,
  cell_size_m numeric,
  grid_angle_deg numeric,
  detail_level numeric,
  field_mean numeric,
  valid_cell_count integer,
  area_hectares numeric,
  thresholds_json jsonb not null default '[]'::jsonb,
  histogram_json jsonb not null default '{}'::jsonb,
  legend_json jsonb not null default '[]'::jsonb,
  rates_json jsonb not null default '[]'::jsonb,
  prescription_geojson jsonb,
  grid_geojson jsonb,
  response_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (index_name in ('NDVI', 'NDWI', 'NDRE'))
);

create table if not exists public.published_artifacts (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid not null references public.published_analyses(id) on delete cascade,
  artifact_type text not null,
  name text,
  url text not null,
  storage_key text,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.publication_events (
  id uuid primary key default gen_random_uuid(),
  analysis_id uuid references public.published_analyses(id) on delete cascade,
  status text not null,
  message text,
  error_detail text,
  created_at timestamptz not null default now(),
  check (status in ('pending', 'published', 'failed', 'updated'))
);

create index if not exists published_projects_source_project_id_idx
  on public.published_projects (source_project_id);

create index if not exists published_analyses_project_id_idx
  on public.published_analyses (project_id, published_at desc);

create index if not exists published_analyses_source_orthomosaic_id_idx
  on public.published_analyses (source_orthomosaic_id);

create index if not exists published_analyses_source_roi_id_idx
  on public.published_analyses (source_roi_id);

create index if not exists published_index_results_analysis_idx
  on public.published_index_results (analysis_id, index_name);

create index if not exists published_zonings_analysis_idx
  on public.published_zonings (analysis_id, index_name);

create index if not exists published_prescriptions_analysis_idx
  on public.published_prescriptions (analysis_id, index_name);

create index if not exists published_artifacts_analysis_idx
  on public.published_artifacts (analysis_id, artifact_type);

create index if not exists publication_events_analysis_idx
  on public.publication_events (analysis_id, created_at desc);
