drop view if exists public.machine_catalog_model_details;

create view public.machine_catalog_model_details
with (security_invoker = true)
as
select
  m.*,
  mf.name as manufacturer_name,
  mf.country as manufacturer_country,
  b.name as brand_name,
  c.code as primary_category_code,
  c.label as primary_category_label,
  c.layout_type,
  s.height_mm,
  s.width_mm,
  s.depth_mm,
  s.weight_kg,
  s.capacity_units,
  s.capacity_description,
  s.temperature_min_c,
  s.temperature_max_c,
  s.refrigerated,
  s.freezer,
  s.heated,
  s.touchscreen,
  s.screen_size_inches,
  s.payment_protocols,
  s.connectivity,
  s.power_requirements,
  s.voltage,
  coalesce(s.raw_specs, '{}'::jsonb) as specs,
  coalesce(img.image_count, 0) as image_count,
  coalesce(doc.document_count, 0) as document_count
from public.machine_catalog_models m
join public.machine_manufacturers mf on mf.id = m.manufacturer_id
left join public.machine_brands b on b.id = m.brand_id
left join public.machine_categories c on c.id = m.primary_category_id
left join public.machine_model_specs s on s.machine_model_id = m.id
left join (
  select machine_model_id, count(*) as image_count
  from public.machine_model_images
  group by machine_model_id
) img on img.machine_model_id = m.id
left join (
  select machine_model_id, count(*) as document_count
  from public.machine_model_documents
  group by machine_model_id
) doc on doc.machine_model_id = m.id;
