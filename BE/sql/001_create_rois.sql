create table if not exists public.rois (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  geojson jsonb not null,
  orthomosaic_id uuid references public.orthomosaics(id) on delete set null,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create index if not exists rois_orthomosaic_id_idx on public.rois (orthomosaic_id);
