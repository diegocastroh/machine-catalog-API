import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { MachineCatalogNormalizer } from './normalizer.js';
import type { CatalogStore, QueryFilters } from './store.js';
import type {
  CrawlJobCreate,
  DocumentCreate,
  ImageCreate,
  ManufacturerCreate,
  ModelCreate,
  SourceCreate
} from './schemas.js';

export class SupabaseCatalogStore implements CatalogStore {
  private readonly normalizer = new MachineCatalogNormalizer();

  constructor(private readonly client: SupabaseClient) {}

  static fromCredentials(url: string, serviceRoleKey: string): SupabaseCatalogStore {
    return new SupabaseCatalogStore(createClient(url, serviceRoleKey, { auth: { persistSession: false } }));
  }

  async listCategories(): Promise<any[]> {
    return this.selectMany(this.client.from('machine_categories').select('*').order('label'));
  }

  async findCategoryByCode(code: string): Promise<any | null> {
    return this.selectOne(this.client.from('machine_categories').select('*').eq('code', code).maybeSingle());
  }

  async listManufacturers(filters: QueryFilters): Promise<any[]> {
    let query = this.client.from('machine_manufacturers').select('*').is('deleted_at', null).order('name');
    if (filters.status) query = query.eq('status', filters.status);
    if (filters.q) query = query.ilike('name', `%${filters.q}%`);
    return this.selectMany(query);
  }

  async getManufacturer(id: string): Promise<any | null> {
    return this.selectOne(this.client.from('machine_manufacturers').select('*').eq('id', id).is('deleted_at', null).maybeSingle());
  }

  async createManufacturer(input: ManufacturerCreate): Promise<any> {
    const payload = {
      ...input,
      slug: input.slug ?? this.normalizer.slugify(input.name),
      status: input.status ?? 'pending_review',
      source_confidence: input.source_confidence ?? 0
    };
    return this.insertOne('machine_manufacturers', payload);
  }

  async updateManufacturer(id: string, input: Partial<ManufacturerCreate>): Promise<any> {
    const payload = { ...input, updated_at: new Date().toISOString() };
    if (input.name && !input.slug) payload.slug = this.normalizer.slugify(input.name);
    return this.updateOne('machine_manufacturers', id, payload);
  }

  async archiveManufacturer(id: string): Promise<void> {
    await this.updateOne('machine_manufacturers', id, { status: 'archived', deleted_at: new Date().toISOString() });
  }

  async listModels(filters: QueryFilters & { publicOnly?: boolean }): Promise<any[]> {
    let query = this.client
      .from('machine_catalog_model_details')
      .select('*')
      .is('deleted_at', null)
      .order('model_name');
    if (filters.publicOnly) query = query.eq('status', 'approved');
    if (filters.status && !filters.publicOnly) query = query.eq('status', filters.status);
    if (filters.manufacturer) query = query.eq('manufacturer_id', filters.manufacturer);
    if (filters.category) query = query.eq('primary_category_code', filters.category);
    if (filters.has_images === true) query = query.gt('image_count', 0);
    if (filters.q) query = query.or(`model_name.ilike.%${filters.q}%,manufacturer_name.ilike.%${filters.q}%`);
    return this.selectMany(query);
  }

  async getModel(id: string, publicOnly = false): Promise<any | null> {
    let query = this.client.from('machine_catalog_model_details').select('*').eq('id', id).is('deleted_at', null);
    if (publicOnly) query = query.eq('status', 'approved');
    return this.selectOne(query.maybeSingle());
  }

  async listManufacturerModels(manufacturerId: string, publicOnly = false): Promise<any[]> {
    return this.listModels({ manufacturer: manufacturerId, publicOnly });
  }

  async createModel(input: ModelCreate): Promise<any> {
    const category = input.category_code ? await this.findCategoryByCode(input.category_code) : null;
    const modelSlug = input.model_slug ?? this.normalizer.slugify(input.model_name);
    const payload = {
      manufacturer_id: input.manufacturer_id,
      brand_id: input.brand_id ?? null,
      model_name: this.normalizer.cleanModelName(input.model_name),
      normalized_model_name: this.normalizer.slugify(input.model_name),
      model_slug: modelSlug,
      family_name: input.family_name ?? null,
      short_description: input.short_description ?? null,
      long_description: input.long_description ?? null,
      primary_category_id: input.primary_category_id ?? category?.id ?? null,
      status: input.status ?? 'pending_review',
      lifecycle_status: input.lifecycle_status ?? 'unknown',
      source_url: input.source_url ?? null,
      official_product_url: input.official_product_url ?? null,
      confidence_score: input.confidence_score ?? 0
    };
    const model = await this.insertOne('machine_catalog_models', payload);
    if (input.specs) {
      await this.insertOne('machine_model_specs', { machine_model_id: model.id, raw_specs: input.specs });
    }
    if (payload.primary_category_id) {
      await this.insertOne('machine_model_categories', {
        machine_model_id: model.id,
        category_id: payload.primary_category_id,
        is_primary: true
      });
    }
    return model;
  }

  async updateModel(id: string, input: Partial<ModelCreate>): Promise<any> {
    const payload: Record<string, unknown> = { ...input, updated_at: new Date().toISOString() };
    delete payload.category_code;
    delete payload.specs;
    if (input.model_name && !input.model_slug) {
      payload.model_slug = this.normalizer.slugify(input.model_name);
      payload.normalized_model_name = this.normalizer.slugify(input.model_name);
    }
    if (input.category_code) {
      const category = await this.findCategoryByCode(input.category_code);
      payload.primary_category_id = category?.id ?? null;
    }
    return this.updateOne('machine_catalog_models', id, payload);
  }

  async approveModel(id: string, reviewedBy?: string): Promise<any> {
    await this.insertOne('admin_reviews', {
      entity_type: 'model',
      entity_id: id,
      review_action: 'approved',
      reviewed_by: reviewedBy ?? null
    });
    return this.updateOne('machine_catalog_models', id, {
      status: 'approved',
      reviewed_by: reviewedBy ?? null,
      reviewed_at: new Date().toISOString()
    });
  }

  async rejectModel(id: string, reviewedBy?: string, notes?: string): Promise<any> {
    await this.insertOne('admin_reviews', {
      entity_type: 'model',
      entity_id: id,
      review_action: 'rejected',
      notes: notes ?? null,
      reviewed_by: reviewedBy ?? null
    });
    return this.updateOne('machine_catalog_models', id, {
      status: 'rejected',
      reviewed_by: reviewedBy ?? null,
      reviewed_at: new Date().toISOString()
    });
  }

  async createModelImage(modelId: string, input: ImageCreate): Promise<any> {
    this.normalizer.validateExternalHttpUrl(input.source_image_url);
    return this.insertOne('machine_model_images', { ...input, machine_model_id: modelId });
  }

  async listModelImages(modelId: string, publicOnly = false): Promise<any[]> {
    let query = this.client.from('machine_model_images').select('*').eq('machine_model_id', modelId).order('is_primary', { ascending: false });
    if (publicOnly) query = query.neq('license_status', 'blocked');
    return this.selectMany(query);
  }

  async createModelDocument(modelId: string, input: DocumentCreate): Promise<any> {
    this.normalizer.validateExternalHttpUrl(input.source_url);
    return this.insertOne('machine_model_documents', { ...input, machine_model_id: modelId });
  }

  async listModelDocuments(modelId: string, publicOnly = false): Promise<any[]> {
    let query = this.client.from('machine_model_documents').select('*').eq('machine_model_id', modelId);
    if (publicOnly) query = query.neq('document_type', 'unknown');
    return this.selectMany(query);
  }

  async createSource(input: SourceCreate): Promise<any> {
    const url = this.normalizer.validateExternalHttpUrl(input.url);
    return this.insertOne('source_pages', { ...input, domain: url.hostname });
  }

  async updateSource(id: string, input: Partial<SourceCreate>): Promise<any> {
    const payload: Record<string, unknown> = { ...input, updated_at: new Date().toISOString() };
    if (input.url) {
      const url = this.normalizer.validateExternalHttpUrl(input.url);
      payload.domain = url.hostname;
    }
    return this.updateOne('source_pages', id, payload);
  }

  async createCrawlJob(input: CrawlJobCreate): Promise<any> {
    return this.insertOne('crawl_jobs', { ...input, status: 'queued', stats: {} });
  }

  async listCrawlJobs(): Promise<any[]> {
    return this.selectMany(this.client.from('crawl_jobs').select('*').order('created_at', { ascending: false }));
  }

  async getCrawlJob(id: string): Promise<any | null> {
    return this.selectOne(this.client.from('crawl_jobs').select('*').eq('id', id).maybeSingle());
  }

  async reviewQueue(): Promise<any> {
    const [manufacturers, models] = await Promise.all([
      this.selectMany(this.client.from('machine_manufacturers').select('*').eq('status', 'pending_review').is('deleted_at', null)),
      this.selectMany(this.client.from('machine_catalog_model_details').select('*').eq('status', 'pending_review').is('deleted_at', null))
    ]);
    return { manufacturers, models };
  }

  async linkMachineToCatalog(operationalMachineId: string, catalogModelId: string): Promise<any> {
    const model = await this.getModel(catalogModelId, true);
    if (!model) throw new Error('Approved catalog model not found');
    return this.insertOne('machine_catalog_links', {
      operational_machine_id: operationalMachineId,
      catalog_model_id: catalogModelId,
      snapshot: {
        model_name: model.model_name,
        manufacturer_name: model.manufacturer_name,
        primary_category_code: model.primary_category_code
      }
    });
  }

  async unlinkMachine(operationalMachineId: string): Promise<void> {
    const { error } = await this.client.from('machine_catalog_links').delete().eq('operational_machine_id', operationalMachineId);
    if (error) throw error;
  }

  private async insertOne(table: string, payload: Record<string, unknown>): Promise<any> {
    const { data, error } = await this.client.from(table).insert(payload).select('*').single();
    if (error) throw error;
    return data;
  }

  private async updateOne(table: string, id: string, payload: Record<string, unknown>): Promise<any> {
    const { data, error } = await this.client.from(table).update(payload).eq('id', id).select('*').single();
    if (error) throw error;
    return data;
  }

  private async selectMany(query: PromiseLike<{ data: any[] | null; error: any }>): Promise<any[]> {
    const { data, error } = await query;
    if (error) throw error;
    return data ?? [];
  }

  private async selectOne(query: PromiseLike<{ data: any | null; error: any }>): Promise<any | null> {
    const { data, error } = await query;
    if (error) throw error;
    return data;
  }
}
