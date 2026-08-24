alter table public.orthomosaics
add column if not exists display_order integer;

with ranked as (
  select
    id,
    (
      row_number() over (
        partition by agricultural_cycle_id
        order by capture_date desc, created_at desc, id
      ) - 1
    )::integer as position
  from public.orthomosaics
  where display_order is null
)
update public.orthomosaics as orthomosaic
set display_order = ranked.position
from ranked
where orthomosaic.id = ranked.id;

create index if not exists orthomosaics_cycle_display_order_idx
on public.orthomosaics (agricultural_cycle_id, display_order);
