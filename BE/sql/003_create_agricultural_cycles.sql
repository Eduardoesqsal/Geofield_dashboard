create table if not exists public.agricultural_cycles (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  crop_name text,
  start_date date not null,
  end_date date,
  notes text,
  created_at timestamptz not null default now()
);

alter table public.orthomosaics
  add column if not exists agricultural_cycle_id uuid references public.agricultural_cycles(id) on delete set null;

create index if not exists orthomosaics_agricultural_cycle_id_idx
  on public.orthomosaics (agricultural_cycle_id);
