import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { MachineCatalogNormalizer } from './normalizer.js';
import type { CatalogStore, QueryFilters } from './store.js';
import type {
  CrawlJobCreate,
  DocumentCreate,
  ImageCreate,
  ManufacturerCreate,
  ModelCreate,
  SourceConfigCreate,
  SourceCreate
} from './schemas.js';
import { MachineCatalogReviewService } from './review-service.js';

export class SupabaseCatalogStore implements CatalogStore {
  private readonly normalizer = new MachineCatalogNormalizer();
  private readonly reviewService = new MachineCatalogReviewService();

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
      await this.insertOne('machine_model_specs', this.buildSpecPayload(model.id, input.specs));
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

  async listSources(): Promise<any[]> {
    return this.selectMany(this.client.from('source_pages').select('*').order('created_at', { ascending: false }));
  }

  async getSource(id: string): Promise<any | null> {
    return this.selectOne(this.client.from('source_pages').select('*').eq('id', id).maybeSingle());
  }

  async createSourceConfig(input: SourceConfigCreate): Promise<any> {
    const url = this.normalizer.validateExternalHttpUrl(input.base_url);
    if (!input.allowed_domains.includes(url.hostname)) {
      throw new Error('base_url host must be included in allowed_domains');
    }
    return this.insertOne('catalog_source_configs', input as unknown as Record<string, unknown>);
  }

  async getSourceConfig(id: string): Promise<any | null> {
    return this.selectOne(
      this.client
        .from('catalog_source_configs')
        .select('*, machine_manufacturers(name)')
        .eq('id', id)
        .maybeSingle()
    ).then((config) =>
      config
        ? {
            ...config,
            manufacturer_name: config.machine_manufacturers?.name
          }
        : null
    );
  }

  async updateSourceConfig(id: string, input: Partial<SourceConfigCreate>): Promise<any> {
    return this.updateOne('catalog_source_configs', id, input as Record<string, unknown>);
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
    return this.insertOne('crawl_jobs', { ...input, status: 'queued', stats: {}, max_pages: input.max_pages ?? null });
  }

  async updateCrawlJob(id: string, input: Record<string, unknown>): Promise<any> {
    return this.updateOne('crawl_jobs', id, input);
  }

  async listCrawlJobs(): Promise<any[]> {
    return this.selectMany(this.client.from('crawl_jobs').select('*').order('created_at', { ascending: false }));
  }

  async getCrawlJob(id: string): Promise<any | null> {
    return this.selectOne(this.client.from('crawl_jobs').select('*').eq('id', id).maybeSingle());
  }

  async addCrawlJobLog(jobId: string, level: string, message: string, metadata: Record<string, unknown> = {}): Promise<any> {
    return this.insertOne('crawl_job_logs', { crawl_job_id: jobId, level, message, metadata });
  }

  async listCrawlJobLogs(jobId: string): Promise<any[]> {
    return this.selectMany(
      this.client.from('crawl_job_logs').select('*').eq('crawl_job_id', jobId).order('created_at', { ascending: true })
    );
  }

  async reviewQueue(): Promise<any> {
    const [manufacturers, models, extractions] = await Promise.all([
      this.selectMany(this.client.from('machine_manufacturers').select('*').eq('status', 'pending_review').is('deleted_at', null)),
      this.selectMany(this.client.from('machine_catalog_model_details').select('*').eq('status', 'pending_review').is('deleted_at', null)),
      this.selectMany(
        this.client
          .from('normalized_extractions')
          .select('*, raw_extractions(source_page_id, crawl_job_id, source_pages(url, domain))')
          .not('validation_flags', 'cs', '["rejected"]')
          .order('created_at', { ascending: false })
      )
    ]);
    return { manufacturers, models, extractions };
  }

  async getReviewQueueItem(id: string): Promise<any | null> {
    return this.selectOne(
      this.client
        .from('normalized_extractions')
        .select('*, raw_extractions(source_page_id, crawl_job_id)')
        .eq('id', id)
        .maybeSingle()
    );
  }

  async approveReviewQueueItem(id: string, reviewedBy?: string, edits: Record<string, unknown> = {}): Promise<any> {
    const item = await this.getReviewQueueItem(id);
    if (!item) throw new Error('Review item not found');
    const approval = this.reviewService.buildApproval({
      rawExtractionId: item.raw_extraction_id,
      sourcePageId: item.raw_extractions?.source_page_id,
      reviewedBy,
      extraction: item,
      edits
    });
    const manufacturer = await this.upsertManufacturerBySlug(approval.manufacturer);
    const category = approval.model.category_code ? await this.findCategoryByCode(approval.model.category_code) : null;
    const model = await this.createModel({
      manufacturer_id: manufacturer.id,
      model_name: approval.model.model_name,
      category_code: category?.code,
      short_description: approval.model.short_description,
      source_url: approval.model.source_url,
      confidence_score: approval.model.confidence_score,
      status: 'pending_review',
      specs: approval.specs
    });
    for (const image of approval.images) {
      if (image.source_image_url) await this.createModelImage(model.id, image as any);
    }
    for (const document of approval.documents) {
      if (document.source_url) await this.createModelDocument(model.id, document as any);
    }
    await this.insertOne('admin_reviews', approval.review);
    await this.insertOne('catalog_change_history', { ...approval.history, entity_id: model.id, entity_type: 'model' });
    return model;
  }

  async rejectReviewQueueItem(id: string, reviewedBy?: string, notes?: string): Promise<any> {
    const review = this.reviewService.buildRejection({ entityId: id, entityType: 'extraction', reviewedBy, notes });
    await this.insertOne('admin_reviews', review);
    return this.updateOne('normalized_extractions', id, { validation_flags: ['rejected'], rejection_notes: notes ?? null });
  }

  async editReviewQueueItem(id: string, edits: Record<string, unknown>): Promise<any> {
    return this.updateOne('normalized_extractions', id, edits);
  }

  async listDuplicates(): Promise<any[]> {
    return this.selectMany(this.client.from('duplicate_candidates').select('*').order('created_at', { ascending: false }));
  }

  async createDuplicateCandidate(input: Record<string, unknown>): Promise<any> {
    return this.insertOne('duplicate_candidates', input);
  }

  async mergeModel(sourceModelId: string, targetModelId: string, reviewedBy?: string): Promise<any> {
    await this.updateOne('machine_catalog_models', sourceModelId, { status: 'archived', deleted_at: new Date().toISOString() });
    await this.insertOne('admin_reviews', {
      entity_type: 'model',
      entity_id: sourceModelId,
      review_action: 'merged',
      reviewed_by: reviewedBy ?? null,
      notes: `Merged into ${targetModelId}`
    });
    return this.insertOne('catalog_change_history', {
      entity_type: 'model',
      entity_id: sourceModelId,
      change_type: 'merged',
      before: { source_model_id: sourceModelId },
      after: { target_model_id: targetModelId },
      changed_by: reviewedBy ?? null
    });
  }

  async persistCrawlerResult(jobId: string, result: Record<string, any>): Promise<void> {
    const raw = result.raw ?? {};
    const normalized = result.normalized ?? {};
    const source = await this.upsertSourcePage({
      manufacturer_id: result.manufacturer_id ?? null,
      url: result.url,
      source_type: result.source_type ?? 'product_page',
      crawl_allowed: result.crawl_allowed ?? true
    });
    const rawExtraction = await this.insertOne('raw_extractions', {
      crawl_job_id: jobId,
      source_page_id: source.id,
      raw_html: raw.raw_html ?? null,
      raw_text: raw.raw_text ?? null,
      raw_json: raw.raw_json ?? null,
      raw_pdf_text: raw.raw_pdf_text ?? null,
      detected_images: raw.detected_images ?? [],
      detected_links: raw.detected_links ?? []
    });
    await this.insertOne('normalized_extractions', {
      raw_extraction_id: rawExtraction.id,
      manufacturer_name: normalized.manufacturer_name ?? null,
      brand_name: normalized.brand_name ?? null,
      model_name: normalized.model_name ?? null,
      category_code: normalized.category_code ?? null,
      description: normalized.description ?? null,
      specs: normalized.specs ?? {},
      images: normalized.images ?? [],
      documents: normalized.documents ?? [],
      confidence_score: normalized.confidence_score ?? 0,
      validation_flags: normalized.validation_flags ?? []
    });
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

  private async upsertManufacturerBySlug(payload: Record<string, unknown>): Promise<any> {
    const { data, error } = await this.client
      .from('machine_manufacturers')
      .upsert(payload, { onConflict: 'slug' })
      .select('*')
      .single();
    if (error) throw error;
    return data;
  }

  private async upsertSourcePage(input: SourceCreate): Promise<any> {
    const url = this.normalizer.validateExternalHttpUrl(input.url);
    const { data, error } = await this.client
      .from('source_pages')
      .upsert({ ...input, domain: url.hostname }, { onConflict: 'url' })
      .select('*')
      .single();
    if (error) throw error;
    return data;
  }

  private buildSpecPayload(machineModelId: string, specs: Record<string, unknown>): Record<string, unknown> {
    const physical = this.objectValue(specs.especificaciones_fisicas);
    const energy = this.objectValue(specs.especificaciones_electricas);
    const hardware = this.objectValue(specs.componentes_hardware);
    return {
      machine_model_id: machineModelId,
      height_mm: this.numberValue(physical.alto_mm),
      width_mm: this.numberValue(physical.ancho_mm),
      depth_mm: this.numberValue(physical.profundidad_mm),
      weight_kg: this.numberValue(physical.peso_kg),
      capacity_units: this.numberValue(hardware.capacidad_vasos),
      capacity_description: this.stringValue(hardware.capacidad_canales_o_espirales),
      voltage: this.stringValue(energy.voltaje),
      power_requirements: this.stringValue(energy.potencia_watts),
      refrigerated: this.stringValue(energy.gas_refrigerante) ? true : null,
      raw_specs: specs
    };
  }

  private objectValue(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
  }

  private stringValue(value: unknown): string | null {
    if (value === null || value === undefined || value === '') return null;
    return String(value);
  }

  private numberValue(value: unknown): number | null {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
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
