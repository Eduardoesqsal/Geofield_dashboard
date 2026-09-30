create table if not exists public.tree_detection_sets (
  orthomosaic_id uuid primary key references public.orthomosaics(id) on delete cascade,
  geojson jsonb not null,
  feature_count integer not null default 0 check (feature_count >= 0),
  updated_at timestamptz not null default now()
);

alter table public.tree_detection_sets enable row level security;

-- El backend usa la clave service_role; las detecciones no se exponen directamente al cliente.
grant select, insert, update, delete on public.tree_detection_sets to service_role;

notify pgrst, 'reload schema';
