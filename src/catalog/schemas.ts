import { z } from 'zod';

export const idParamsSchema = z.object({ id: z.string().uuid() });

export const manufacturerCreateSchema = z.object({
  name: z.string().min(2),
  legal_name: z.string().optional().nullable(),
  slug: z.string().min(2).optional(),
  country: z.string().optional().nullable(),
  website_url: z.string().url().optional().nullable(),
  description: z.string().optional().nullable(),
  status: z.enum(['active', 'inactive', 'pending_review', 'archived']).optional(),
  source_confidence: z.number().min(0).max(1).optional()
});

export const manufacturerUpdateSchema = manufacturerCreateSchema.partial();

export const modelCreateSchema = z.object({
  manufacturer_id: z.string().uuid(),
  brand_id: z.string().uuid().optional().nullable(),
  model_name: z.string().min(1),
  model_slug: z.string().min(1).optional(),
  family_name: z.string().optional().nullable(),
  short_description: z.string().optional().nullable(),
  long_description: z.string().optional().nullable(),
  primary_category_id: z.string().uuid().optional().nullable(),
  category_code: z.string().optional(),
  status: z.enum(['draft', 'pending_review', 'approved', 'rejected', 'archived']).optional(),
  lifecycle_status: z.enum(['active', 'discontinued', 'unknown']).optional(),
  source_url: z.string().url().optional().nullable(),
  official_product_url: z.string().url().optional().nullable(),
  confidence_score: z.number().min(0).max(1).optional(),
  specs: z.record(z.unknown()).optional()
});

export const modelUpdateSchema = modelCreateSchema.partial().omit({ manufacturer_id: true });

export const imageCreateSchema = z.object({
  source_image_url: z.string().url(),
  source_page_url: z.string().url().optional().nullable(),
  storage_url: z.string().url().optional().nullable(),
  image_type: z.enum(['front_photo', 'side_photo', 'gallery', 'diagram', 'mechanism', 'logo', 'unknown']).optional(),
  alt_text: z.string().optional().nullable(),
  caption: z.string().optional().nullable(),
  is_primary: z.boolean().optional(),
  is_official: z.boolean().optional(),
  license_status: z.enum([
    'unknown',
    'official_reference_only',
    'licensed',
    'creative_commons',
    'manual_upload',
    'internal_cached_only',
    'blocked'
  ]).optional()
});

export const documentCreateSchema = z.object({
  document_type: z.enum(['brochure', 'datasheet', 'manual', 'catalog', 'unknown']).optional(),
  title: z.string().optional().nullable(),
  source_url: z.string().url(),
  storage_url: z.string().url().optional().nullable(),
  language: z.string().optional().nullable(),
  metadata: z.record(z.unknown()).optional()
});

export const sourceCreateSchema = z.object({
  manufacturer_id: z.string().uuid().optional().nullable(),
  url: z.string().url(),
  source_type: z.enum(['official_site', 'catalog_page', 'product_page', 'pdf', 'image', 'search_result', 'manual']),
  crawl_allowed: z.boolean().optional().nullable()
});

export const crawlJobCreateSchema = z.object({
  manufacturer_id: z.string().uuid().optional().nullable(),
  job_type: z.enum(['discovery', 'manufacturer_crawl', 'product_page', 'pdf_extract', 'image_check', 'refresh']),
  source_page_id: z.string().uuid().optional().nullable(),
  created_by: z.string().uuid().optional().nullable()
});

export const linkCreateSchema = z.object({
  operational_machine_id: z.string().min(1).optional(),
  catalog_model_id: z.string().uuid().optional()
});

export type ManufacturerCreate = z.infer<typeof manufacturerCreateSchema>;
export type ModelCreate = z.infer<typeof modelCreateSchema>;
export type ImageCreate = z.infer<typeof imageCreateSchema>;
export type DocumentCreate = z.infer<typeof documentCreateSchema>;
export type SourceCreate = z.infer<typeof sourceCreateSchema>;
export type CrawlJobCreate = z.infer<typeof crawlJobCreateSchema>;
