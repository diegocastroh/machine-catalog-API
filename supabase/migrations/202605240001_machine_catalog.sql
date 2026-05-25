create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.machine_manufacturers (
  id uuid primary key default gen_random_uuid(),
  name varchar not null,
  legal_name varchar,
  slug varchar unique not null,
  country varchar,
  website_url text,
  description text,
  status varchar not null default 'pending_review' check (status in ('active','inactive','pending_review','archived')),
  source_confidence numeric(5,2) not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.machine_brands (
  id uuid primary key default gen_random_uuid(),
  manufacturer_id uuid not null references public.machine_manufacturers(id) on delete cascade,
  name varchar not null,
  slug varchar not null,
  website_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (manufacturer_id, slug)
);

create table if not exists public.machine_categories (
  id uuid primary key default gen_random_uuid(),
  code varchar unique not null,
  label varchar not null,
  description text,
  layout_type varchar,
  requires_slots boolean not null default false,
  requires_temperature_control boolean not null default false,
  requires_recipes boolean not null default false,
  requires_freezer boolean not null default false,
  requires_heating boolean not null default false,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.machine_catalog_models (
  id uuid primary key default gen_random_uuid(),
  manufacturer_id uuid not null references public.machine_manufacturers(id),
  brand_id uuid references public.machine_brands(id),
  model_name varchar not null,
  normalized_model_name varchar not null,
  model_slug varchar not null,
  family_name varchar,
  short_description text,
  long_description text,
  primary_category_id uuid references public.machine_categories(id),
  status varchar not null default 'pending_review' check (status in ('draft','pending_review','approved','rejected','archived')),
  lifecycle_status varchar not null default 'unknown' check (lifecycle_status in ('active','discontinued','unknown')),
  source_url text,
  official_product_url text,
  confidence_score numeric(5,2) not null default 0,
  reviewed_by uuid,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  unique (manufacturer_id, normalized_model_name)
);

create table if not exists public.machine_model_categories (
  id uuid primary key default gen_random_uuid(),
  machine_model_id uuid not null references public.machine_catalog_models(id) on delete cascade,
  category_id uuid not null references public.machine_categories(id),
  is_primary boolean not null default false,
  unique (machine_model_id, category_id)
);

create table if not exists public.machine_model_specs (
  id uuid primary key default gen_random_uuid(),
  machine_model_id uuid not null unique references public.machine_catalog_models(id) on delete cascade,
  height_mm numeric,
  width_mm numeric,
  depth_mm numeric,
  weight_kg numeric,
  capacity_units integer,
  capacity_description text,
  temperature_min_c numeric,
  temperature_max_c numeric,
  refrigerated boolean,
  freezer boolean,
  heated boolean,
  touchscreen boolean,
  screen_size_inches numeric,
  payment_protocols text[],
  connectivity text[],
  power_requirements text,
  voltage text,
  raw_specs jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.machine_model_images (
  id uuid primary key default gen_random_uuid(),
  machine_model_id uuid not null references public.machine_catalog_models(id) on delete cascade,
  source_image_url text not null,
  source_page_url text,
  storage_url text,
  image_type varchar not null default 'unknown' check (image_type in ('front_photo','side_photo','gallery','diagram','mechanism','logo','unknown')),
  alt_text text,
  caption text,
  is_primary boolean not null default false,
  is_official boolean not null default false,
  license_status varchar not null default 'unknown' check (license_status in ('unknown','official_reference_only','licensed','creative_commons','manual_upload','internal_cached_only','blocked')),
  hash_sha256 varchar,
  width_px integer,
  height_px integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.machine_model_documents (
  id uuid primary key default gen_random_uuid(),
  machine_model_id uuid not null references public.machine_catalog_models(id) on delete cascade,
  document_type varchar not null default 'unknown' check (document_type in ('brochure','datasheet','manual','catalog','unknown')),
  title varchar,
  source_url text not null,
  storage_url text,
  language varchar,
  hash_sha256 varchar,
  extracted_text text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.source_pages (
  id uuid primary key default gen_random_uuid(),
  manufacturer_id uuid references public.machine_manufacturers(id),
  url text unique not null,
  domain varchar not null,
  source_type varchar not null check (source_type in ('official_site','catalog_page','product_page','pdf','image','search_result','manual')),
  crawl_allowed boolean,
  robots_checked_at timestamptz,
  last_crawled_at timestamptz,
  http_status integer,
  content_hash varchar,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.crawl_jobs (
  id uuid primary key default gen_random_uuid(),
  manufacturer_id uuid references public.machine_manufacturers(id),
  source_page_id uuid references public.source_pages(id),
  job_type varchar not null check (job_type in ('discovery','manufacturer_crawl','product_page','pdf_extract','image_check','refresh')),
  status varchar not null default 'queued' check (status in ('queued','running','success','partial_success','failed','cancelled','blocked_by_robots','blocked_by_site','needs_manual_review')),
  started_at timestamptz,
  finished_at timestamptz,
  error_message text,
  stats jsonb not null default '{}',
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.raw_extractions (
  id uuid primary key default gen_random_uuid(),
  crawl_job_id uuid not null references public.crawl_jobs(id) on delete cascade,
  source_page_id uuid not null references public.source_pages(id),
  raw_html text,
  raw_text text,
  raw_json jsonb,
  raw_pdf_text text,
  detected_images jsonb not null default '[]',
  detected_links jsonb not null default '[]',
  created_at timestamptz not null default now()
);

create table if not exists public.normalized_extractions (
  id uuid primary key default gen_random_uuid(),
  raw_extraction_id uuid not null references public.raw_extractions(id) on delete cascade,
  manufacturer_name varchar,
  brand_name varchar,
  model_name varchar,
  category_code varchar,
  description text,
  specs jsonb not null default '{}',
  images jsonb not null default '[]',
  documents jsonb not null default '[]',
  confidence_score numeric(5,2) not null default 0,
  validation_flags jsonb not null default '[]',
  created_at timestamptz not null default now()
);

create table if not exists public.admin_reviews (
  id uuid primary key default gen_random_uuid(),
  entity_type varchar not null check (entity_type in ('manufacturer','model','image','document','extraction')),
  entity_id uuid not null,
  review_action varchar not null check (review_action in ('approved','rejected','merged','edited','needs_more_info')),
  notes text,
  reviewed_by uuid,
  created_at timestamptz not null default now()
);

create table if not exists public.catalog_change_history (
  id uuid primary key default gen_random_uuid(),
  entity_type varchar not null,
  entity_id uuid not null,
  change_type varchar not null check (change_type in ('created','updated','approved','rejected','merged','archived','source_refreshed')),
  before jsonb,
  after jsonb,
  changed_by uuid,
  created_at timestamptz not null default now()
);

create table if not exists public.machine_catalog_links (
  id uuid primary key default gen_random_uuid(),
  operational_machine_id text unique not null,
  catalog_model_id uuid not null references public.machine_catalog_models(id),
  snapshot jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_machine_catalog_models_status on public.machine_catalog_models(status);
create index if not exists idx_machine_catalog_models_category on public.machine_catalog_models(primary_category_id);
create index if not exists idx_machine_catalog_models_search on public.machine_catalog_models using gin (to_tsvector('simple', coalesce(model_name, '') || ' ' || coalesce(short_description, '')));
create index if not exists idx_source_pages_domain on public.source_pages(domain);
create index if not exists idx_crawl_jobs_status on public.crawl_jobs(status);

create or replace view public.machine_catalog_model_details
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
  coalesce(img.image_count, 0) as image_count,
  coalesce(doc.document_count, 0) as document_count
from public.machine_catalog_models m
join public.machine_manufacturers mf on mf.id = m.manufacturer_id
left join public.machine_brands b on b.id = m.brand_id
left join public.machine_categories c on c.id = m.primary_category_id
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

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'machine_manufacturers',
    'machine_brands',
    'machine_categories',
    'machine_catalog_models',
    'machine_model_categories',
    'machine_model_specs',
    'machine_model_images',
    'machine_model_documents',
    'source_pages',
    'crawl_jobs',
    'machine_catalog_links'
  ]
  loop
    execute format('drop trigger if exists set_%I_updated_at on public.%I', table_name, table_name);
    execute format('create trigger set_%I_updated_at before update on public.%I for each row execute function public.set_updated_at()', table_name, table_name);
  end loop;
end $$;

alter table public.machine_manufacturers enable row level security;
alter table public.machine_brands enable row level security;
alter table public.machine_categories enable row level security;
alter table public.machine_catalog_models enable row level security;
alter table public.machine_model_categories enable row level security;
alter table public.machine_model_specs enable row level security;
alter table public.machine_model_images enable row level security;
alter table public.machine_model_documents enable row level security;
alter table public.source_pages enable row level security;
alter table public.crawl_jobs enable row level security;
alter table public.raw_extractions enable row level security;
alter table public.normalized_extractions enable row level security;
alter table public.admin_reviews enable row level security;
alter table public.catalog_change_history enable row level security;
alter table public.machine_catalog_links enable row level security;

grant usage on schema public to service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;

insert into public.machine_categories (code, label, description, layout_type, requires_slots, requires_temperature_control, requires_recipes, requires_freezer, requires_heating, metadata)
values
  ('coffee','Cafe','Maquinas de cafe, espresso automatico, bean-to-cup y bebidas calientes.','ingredient_modules',false,false,true,false,false,'{"compatible_modules":["recipes","ingredients","cups","cleaning_cycles","cashless_payment"]}'),
  ('snack_drink','Snacks y bebidas','Maquinas de espirales, bandejas, bebidas frias, snacks secos o combos.','spiral_slots',true,true,false,false,false,'{"compatible_modules":["planogram","slot_replenishment","stock","temperature"]}'),
  ('cold_beverage','Bebidas frias','Maquinas refrigeradas de latas, botellas y bebidas.','columns_or_trays',true,true,false,false,false,'{}'),
  ('ice_cream','Helados / congelados','Maquinas de helados, frozen food o productos congelados.','frozen_trays_or_robotic',false,true,false,true,false,'{"compatible_modules":["temperature","frozen_inventory","robotic_pickup_optional"]}'),
  ('hot_food','Comida caliente','Maquinas que mantienen o calientan alimentos.','heated_compartments',false,true,false,false,true,'{}'),
  ('fresh_food','Fresh food','Maquinas para ensaladas, frutas, sandwiches y alimentos refrigerados.','refrigerated_compartments',false,true,false,false,false,'{"requires_expiration_control":true}'),
  ('smart_locker','Locker inteligente','Lockers o casilleros inteligentes para retiro, venta o entrega.','locker_doors',false,false,false,false,false,'{"requires_door_control":true}'),
  ('ice_water','Hielo / agua','Maquinas de despacho de hielo, agua o ambos.','bulk_dispensing',false,false,false,false,false,'{"requires_water_or_ice_module":true}'),
  ('industrial','Industrial / EPP','Maquinas para herramientas, EPP, repuestos o insumos industriales.','industrial_slots_or_lockers',false,false,false,false,false,'{"requires_audit_control":true}'),
  ('other','Otros','Tipo no clasificado o pendiente de revision.',null,false,false,false,false,false,'{}')
on conflict (code) do update set
  label = excluded.label,
  description = excluded.description,
  layout_type = excluded.layout_type,
  requires_slots = excluded.requires_slots,
  requires_temperature_control = excluded.requires_temperature_control,
  requires_recipes = excluded.requires_recipes,
  requires_freezer = excluded.requires_freezer,
  requires_heating = excluded.requires_heating,
  metadata = excluded.metadata;

insert into public.machine_manufacturers (name, slug, status, source_confidence)
values
  ('Crane / CPI','crane-cpi','pending_review',0),
  ('Evoca Group / Necta','evoca-group-necta','pending_review',0),
  ('Azkoyen / Coffetek','azkoyen-coffetek','pending_review',0),
  ('Fuji Electric','fuji-electric','pending_review',0),
  ('SandenVendo','sandenvendo','pending_review',0),
  ('FAS International','fas-international','pending_review',0),
  ('Bianchi Vending','bianchi-vending','pending_review',0),
  ('Jofemar','jofemar','pending_review',0),
  ('Sielaff','sielaff','pending_review',0),
  ('AMS Vendors','ams-vendors','pending_review',0),
  ('Seaga','seaga','pending_review',0),
  ('Royal Vendors','royal-vendors','pending_review',0),
  ('U-Select-It / USI','u-select-it-usi','pending_review',0),
  ('Westomatic','westomatic','pending_review',0),
  ('Rhea Vendors','rhea-vendors','pending_review',0),
  ('Fastcorp','fastcorp','pending_review',0),
  ('TCN Vending','tcn-vending','pending_review',0),
  ('Vendlife','vendlife','pending_review',0),
  ('XY Vending','xy-vending','pending_review',0),
  ('WMF Professional Coffee Machines','wmf-professional-coffee-machines','pending_review',0),
  ('Schaerer','schaerer','pending_review',0),
  ('Eversys','eversys','pending_review',0),
  ('Bravilor Bonamat','bravilor-bonamat','pending_review',0),
  ('BUNN','bunn','pending_review',0),
  ('Saeco Professional','saeco-professional','pending_review',0),
  ('Huaxin Vending','huaxin-vending','pending_review',0),
  ('SweetRobo','sweetrobo','pending_review',0),
  ('ColdSnap','coldsnap','pending_review',0),
  ('Kooler Ice','kooler-ice','pending_review',0)
on conflict (slug) do nothing;
