create table if not exists public.roi_analyses (
  id uuid primary key default gen_random_uuid(),
  roi_id uuid not null references public.rois(id) on delete cascade,
  orthomosaic_id uuid not null references public.orthomosaics(id) on delete cascade,
  ndvi jsonb not null,
  ndwi jsonb,
  ndre jsonb,
  created_at timestamptz not null default now(),
  unique (roi_id, orthomosaic_id)
);

create index if not exists roi_analyses_roi_id_idx on public.roi_analyses (roi_id, created_at desc);
