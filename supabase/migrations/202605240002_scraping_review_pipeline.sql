create table if not exists public.catalog_source_configs (
  id uuid primary key default gen_random_uuid(),
  manufacturer_id uuid not null references public.machine_manufacturers(id),
  base_url text not null,
  allowed_domains text[] not null default '{}',
  crawl_strategy varchar not null default 'sitemap' check (crawl_strategy in ('sitemap','product_urls','single_page')),
  product_url_patterns text[] not null default array['/products/','/machines/','/vending/'],
  exclude_patterns text[] not null default array['/blog/','/news/','/careers/'],
  data_sources text[] not null default array['html','jsonld','opengraph','pdf'],
  image_selectors text[] not null default array['meta[property=''og:image'']','img'],
  refresh_frequency_days integer not null default 30,
  max_pages_per_run integer not null default 50,
  delay_seconds numeric not null default 2,
  dynamic_rendering boolean not null default false,
  status varchar not null default 'active' check (status in ('active','inactive','blocked','needs_review')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.crawl_jobs
  add column if not exists source_config_id uuid references public.catalog_source_configs(id),
  add column if not exists max_pages integer,
  add column if not exists pages_processed integer not null default 0,
  add column if not exists models_detected integer not null default 0;

create table if not exists public.crawl_job_logs (
  id uuid primary key default gen_random_uuid(),
  crawl_job_id uuid not null references public.crawl_jobs(id) on delete cascade,
  level varchar not null default 'info' check (level in ('debug','info','warning','error')),
  message text not null,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists public.duplicate_candidates (
  id uuid primary key default gen_random_uuid(),
  source_model_id uuid references public.machine_catalog_models(id),
  target_model_id uuid references public.machine_catalog_models(id),
  source_extraction_id uuid references public.normalized_extractions(id),
  target_extraction_id uuid references public.normalized_extractions(id),
  score numeric(5,2) not null default 0,
  match_type varchar not null default 'none',
  reasons jsonb not null default '[]',
  status varchar not null default 'open' check (status in ('open','merged','dismissed')),
  reviewed_by uuid,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.normalized_extractions
  add column if not exists rejection_notes text;

create index if not exists idx_catalog_source_configs_manufacturer on public.catalog_source_configs(manufacturer_id);
create index if not exists idx_crawl_jobs_source_config on public.crawl_jobs(source_config_id);
create index if not exists idx_crawl_job_logs_job on public.crawl_job_logs(crawl_job_id);
create index if not exists idx_duplicate_candidates_status on public.duplicate_candidates(status);

drop trigger if exists set_catalog_source_configs_updated_at on public.catalog_source_configs;
create trigger set_catalog_source_configs_updated_at
before update on public.catalog_source_configs
for each row execute function public.set_updated_at();

drop trigger if exists set_duplicate_candidates_updated_at on public.duplicate_candidates;
create trigger set_duplicate_candidates_updated_at
before update on public.duplicate_candidates
for each row execute function public.set_updated_at();

alter table public.catalog_source_configs enable row level security;
alter table public.crawl_job_logs enable row level security;
alter table public.duplicate_candidates enable row level security;

grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;
