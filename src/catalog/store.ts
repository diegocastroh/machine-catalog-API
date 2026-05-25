import type {
  CrawlJobCreate,
  DocumentCreate,
  ImageCreate,
  ManufacturerCreate,
  ModelCreate,
  SourceConfigCreate,
  SourceCreate
} from './schemas.js';

export type QueryFilters = Record<string, string | boolean | undefined>;

export type CatalogStore = {
  listCategories(): Promise<any[]>;
  findCategoryByCode(code: string): Promise<any | null>;
  listManufacturers(filters: QueryFilters): Promise<any[]>;
  getManufacturer(id: string): Promise<any | null>;
  createManufacturer(input: ManufacturerCreate): Promise<any>;
  updateManufacturer(id: string, input: Partial<ManufacturerCreate>): Promise<any>;
  archiveManufacturer(id: string): Promise<void>;
  listModels(filters: QueryFilters & { publicOnly?: boolean }): Promise<any[]>;
  getModel(id: string, publicOnly?: boolean): Promise<any | null>;
  listManufacturerModels(manufacturerId: string, publicOnly?: boolean): Promise<any[]>;
  createModel(input: ModelCreate): Promise<any>;
  updateModel(id: string, input: Partial<ModelCreate>): Promise<any>;
  approveModel(id: string, reviewedBy?: string): Promise<any>;
  rejectModel(id: string, reviewedBy?: string, notes?: string): Promise<any>;
  createModelImage(modelId: string, input: ImageCreate): Promise<any>;
  listModelImages(modelId: string, publicOnly?: boolean): Promise<any[]>;
  createModelDocument(modelId: string, input: DocumentCreate): Promise<any>;
  listModelDocuments(modelId: string, publicOnly?: boolean): Promise<any[]>;
  createSource(input: SourceCreate): Promise<any>;
  updateSource(id: string, input: Partial<SourceCreate>): Promise<any>;
  listSources(): Promise<any[]>;
  getSource(id: string): Promise<any | null>;
  createSourceConfig(input: SourceConfigCreate): Promise<any>;
  getSourceConfig(id: string): Promise<any | null>;
  updateSourceConfig(id: string, input: Partial<SourceConfigCreate>): Promise<any>;
  createCrawlJob(input: CrawlJobCreate): Promise<any>;
  updateCrawlJob(id: string, input: Record<string, unknown>): Promise<any>;
  listCrawlJobs(): Promise<any[]>;
  getCrawlJob(id: string): Promise<any | null>;
  addCrawlJobLog(jobId: string, level: string, message: string, metadata?: Record<string, unknown>): Promise<any>;
  listCrawlJobLogs(jobId: string): Promise<any[]>;
  reviewQueue(): Promise<any>;
  getReviewQueueItem(id: string): Promise<any | null>;
  approveReviewQueueItem(id: string, reviewedBy?: string, edits?: Record<string, unknown>): Promise<any>;
  rejectReviewQueueItem(id: string, reviewedBy?: string, notes?: string): Promise<any>;
  editReviewQueueItem(id: string, edits: Record<string, unknown>): Promise<any>;
  listDuplicates(): Promise<any[]>;
  createDuplicateCandidate(input: Record<string, unknown>): Promise<any>;
  mergeModel(sourceModelId: string, targetModelId: string, reviewedBy?: string): Promise<any>;
  persistCrawlerResult(jobId: string, result: Record<string, any>): Promise<void>;
  linkMachineToCatalog(operationalMachineId: string, catalogModelId: string): Promise<any>;
  unlinkMachine(operationalMachineId: string): Promise<void>;
};
