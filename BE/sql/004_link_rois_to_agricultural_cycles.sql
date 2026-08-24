alter table public.rois
  add column if not exists agricultural_cycle_id uuid references public.agricultural_cycles(id) on delete set null;

create index if not exists rois_agricultural_cycle_id_idx
  on public.rois (agricultural_cycle_id);

update public.rois as r
set agricultural_cycle_id = o.agricultural_cycle_id
from public.orthomosaics as o
where r.orthomosaic_id = o.id
  and r.agricultural_cycle_id is null
  and o.agricultural_cycle_id is not null;
