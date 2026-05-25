import type {
  CrawlJobCreate,
  DocumentCreate,
  ImageCreate,
  ManufacturerCreate,
  ModelCreate,
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
  createCrawlJob(input: CrawlJobCreate): Promise<any>;
  listCrawlJobs(): Promise<any[]>;
  getCrawlJob(id: string): Promise<any | null>;
  reviewQueue(): Promise<any>;
  linkMachineToCatalog(operationalMachineId: string, catalogModelId: string): Promise<any>;
  unlinkMachine(operationalMachineId: string): Promise<void>;
};
