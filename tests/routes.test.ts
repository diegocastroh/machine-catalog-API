import { randomUUID } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { buildApp } from '../src/app.js';
import type {
  CrawlJobCreate,
  DocumentCreate,
  ImageCreate,
  ManufacturerCreate,
  ModelCreate,
  SourceCreate
} from '../src/catalog/schemas.js';
import type { CatalogStore, QueryFilters } from '../src/catalog/store.js';

class InMemoryCatalogStore implements CatalogStore {
  categories = [{ id: randomUUID(), code: 'snack_drink', label: 'Snacks y bebidas', layout_type: 'spiral_slots' }];
  manufacturers: any[] = [];
  models: any[] = [];
  images: any[] = [];
  documents: any[] = [];
  jobs: any[] = [];
  sources: any[] = [];
  sourceConfigs: any[] = [];
  logs: any[] = [];
  duplicates: any[] = [];

  async listCategories() {
    return this.categories;
  }

  async findCategoryByCode(code: string) {
    return this.categories.find((category) => category.code === code) ?? null;
  }

  async listManufacturers(_filters: QueryFilters) {
    return this.manufacturers;
  }

  async getManufacturer(id: string) {
    return this.manufacturers.find((manufacturer) => manufacturer.id === id) ?? null;
  }

  async createManufacturer(input: ManufacturerCreate) {
    const manufacturer = { id: randomUUID(), status: 'pending_review', ...input, slug: input.slug ?? input.name.toLowerCase().replaceAll(' ', '-') };
    this.manufacturers.push(manufacturer);
    return manufacturer;
  }

  async updateManufacturer(id: string, input: Partial<ManufacturerCreate>) {
    const manufacturer = await this.getManufacturer(id);
    Object.assign(manufacturer, input);
    return manufacturer;
  }

  async archiveManufacturer(id: string) {
    const manufacturer = await this.getManufacturer(id);
    if (manufacturer) manufacturer.status = 'archived';
  }

  async listModels(filters: QueryFilters & { publicOnly?: boolean }) {
    return this.models.filter((model) => !filters.publicOnly || model.status === 'approved');
  }

  async getModel(id: string, publicOnly = false) {
    const model = this.models.find((item) => item.id === id);
    if (!model || (publicOnly && model.status !== 'approved')) return null;
    return model;
  }

  async listManufacturerModels(manufacturerId: string, publicOnly = false) {
    return this.models.filter((model) => model.manufacturer_id === manufacturerId && (!publicOnly || model.status === 'approved'));
  }

  async createModel(input: ModelCreate) {
    const category = input.category_code ? await this.findCategoryByCode(input.category_code) : null;
    const model = {
      id: randomUUID(),
      status: 'pending_review',
      image_count: 0,
      document_count: 0,
      primary_category_code: category?.code,
      primary_category_label: category?.label,
      ...input
    };
    this.models.push(model);
    return model;
  }

  async updateModel(id: string, input: Partial<ModelCreate>) {
    const model = await this.getModel(id);
    Object.assign(model, input);
    return model;
  }

  async approveModel(id: string) {
    const model = await this.getModel(id);
    model.status = 'approved';
    return model;
  }

  async rejectModel(id: string) {
    const model = await this.getModel(id);
    model.status = 'rejected';
    return model;
  }

  async createModelImage(modelId: string, input: ImageCreate) {
    const image = { id: randomUUID(), machine_model_id: modelId, ...input };
    this.images.push(image);
    return image;
  }

  async listModelImages(modelId: string) {
    return this.images.filter((image) => image.machine_model_id === modelId);
  }

  async createModelDocument(modelId: string, input: DocumentCreate) {
    const document = { id: randomUUID(), machine_model_id: modelId, ...input };
    this.documents.push(document);
    return document;
  }

  async listModelDocuments(modelId: string) {
    return this.documents.filter((document) => document.machine_model_id === modelId);
  }

  async createSource(input: SourceCreate) {
    const source = { id: randomUUID(), ...input };
    this.sources.push(source);
    return source;
  }

  async updateSource(id: string, input: Partial<SourceCreate>) {
    return { id, ...input };
  }

  async listSources() {
    return this.sources;
  }

  async getSource(id: string) {
    return this.sources.find((source) => source.id === id) ?? null;
  }

  async createSourceConfig(input: any) {
    const config = { id: randomUUID(), ...input };
    this.sourceConfigs.push(config);
    return config;
  }

  async getSourceConfig(id: string) {
    return this.sourceConfigs.find((config) => config.id === id) ?? null;
  }

  async updateSourceConfig(id: string, input: any) {
    const config = await this.getSourceConfig(id);
    Object.assign(config, input);
    return config;
  }

  async createCrawlJob(input: CrawlJobCreate) {
    const job = { id: randomUUID(), status: 'queued', ...input };
    this.jobs.push(job);
    return job;
  }

  async updateCrawlJob(id: string, input: Record<string, unknown>) {
    const job = await this.getCrawlJob(id);
    Object.assign(job, input);
    return job;
  }

  async listCrawlJobs() {
    return this.jobs;
  }

  async getCrawlJob(id: string) {
    return this.jobs.find((job) => job.id === id) ?? null;
  }

  async addCrawlJobLog(jobId: string, level: string, message: string, metadata: Record<string, unknown> = {}) {
    const log = { id: randomUUID(), crawl_job_id: jobId, level, message, metadata };
    this.logs.push(log);
    return log;
  }

  async listCrawlJobLogs(jobId: string) {
    return this.logs.filter((log) => log.crawl_job_id === jobId);
  }

  async reviewQueue() {
    return { manufacturers: this.manufacturers, models: this.models.filter((model) => model.status === 'pending_review') };
  }

  async getReviewQueueItem(id: string) {
    return this.models.find((model) => model.id === id) ?? null;
  }

  async approveReviewQueueItem(id: string) {
    return this.approveModel(id);
  }

  async rejectReviewQueueItem(id: string) {
    return this.rejectModel(id);
  }

  async editReviewQueueItem(id: string, edits: Record<string, unknown>) {
    const item = await this.getReviewQueueItem(id);
    Object.assign(item, edits);
    return item;
  }

  async listDuplicates() {
    return this.duplicates;
  }

  async createDuplicateCandidate(input: Record<string, unknown>) {
    const duplicate = { id: randomUUID(), ...input };
    this.duplicates.push(duplicate);
    return duplicate;
  }

  async mergeModel(sourceModelId: string, targetModelId: string) {
    return { source_model_id: sourceModelId, target_model_id: targetModelId, status: 'merged' };
  }

  async persistCrawlerResult(_jobId: string, _result: Record<string, any>) {}

  async linkMachineToCatalog(operationalMachineId: string, catalogModelId: string) {
    return { id: randomUUID(), operational_machine_id: operationalMachineId, catalog_model_id: catalogModelId };
  }

  async unlinkMachine(_operationalMachineId: string) {}
}

describe('catalog routes', () => {
  it('requires admin key for writes and hides pending models from public API', async () => {
    const store = new InMemoryCatalogStore();
    const app = await buildApp({ store, adminApiKey: 'local-secret' });

    const blocked = await app.inject({
      method: 'POST',
      url: '/api/v1/admin/catalog/manufacturers',
      payload: { name: 'Test Maker' }
    });
    expect(blocked.statusCode).toBe(403);

    const manufacturerResponse = await app.inject({
      method: 'POST',
      url: '/api/v1/admin/catalog/manufacturers',
      headers: { 'x-admin-api-key': 'local-secret' },
      payload: { name: 'Test Maker' }
    });
    expect(manufacturerResponse.statusCode).toBe(200);
    const manufacturer = manufacturerResponse.json().data;

    const modelResponse = await app.inject({
      method: 'POST',
      url: '/api/v1/admin/catalog/machine-models',
      headers: { 'x-admin-api-key': 'local-secret' },
      payload: { manufacturer_id: manufacturer.id, model_name: 'Combo 500', category_code: 'snack_drink' }
    });
    expect(modelResponse.statusCode).toBe(200);
    const model = modelResponse.json().data;

    const hidden = await app.inject({ method: 'GET', url: '/api/v1/catalog/machine-models' });
    expect(hidden.json().data).toHaveLength(0);

    await app.inject({
      method: 'POST',
      url: `/api/v1/admin/catalog/machine-models/${model.id}/approve`,
      headers: { 'x-admin-api-key': 'local-secret' }
    });

    const visible = await app.inject({ method: 'GET', url: '/api/v1/catalog/machine-models' });
    expect(visible.json().data).toHaveLength(1);

    await app.close();
  }, 15000);
});
