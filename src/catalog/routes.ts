import type { FastifyInstance, FastifyRequest } from 'fastify';
import { nanoid } from 'nanoid';
import { MachineCatalogNormalizer } from './normalizer.js';
import {
  crawlJobCreateSchema,
  documentCreateSchema,
  idParamsSchema,
  imageCreateSchema,
  linkCreateSchema,
  manufacturerCreateSchema,
  manufacturerUpdateSchema,
  modelCreateSchema,
  modelUpdateSchema,
  sourceCreateSchema
} from './schemas.js';
import type { CatalogStore } from './store.js';

type RouteOptions = {
  store: CatalogStore;
  adminApiKey: string;
};

export async function registerCatalogRoutes(app: FastifyInstance, options: RouteOptions): Promise<void> {
  const normalizer = new MachineCatalogNormalizer();

  function requireAdmin(request: FastifyRequest): void {
    const header = request.headers['x-admin-api-key'];
    if (!options.adminApiKey || header !== options.adminApiKey) {
      throw httpError(403, 'Admin API key required');
    }
  }

  app.get('/api/v1/catalog/categories', async () => ({ success: true, data: await options.store.listCategories() }));

  app.get('/api/v1/catalog/manufacturers', async (request) => {
    const query = request.query as Record<string, string | undefined>;
    return { success: true, data: await options.store.listManufacturers(query) };
  });

  app.get('/api/v1/catalog/manufacturers/:id', async (request) => {
    const { id } = idParamsSchema.parse(request.params);
    const manufacturer = await options.store.getManufacturer(id);
    if (!manufacturer) throw httpError(404, 'Manufacturer not found');
    return { success: true, data: manufacturer };
  });

  app.get('/api/v1/catalog/manufacturers/:id/models', async (request) => {
    const { id } = idParamsSchema.parse(request.params);
    return { success: true, data: await options.store.listManufacturerModels(id, true) };
  });

  app.get('/api/v1/catalog/machine-models', async (request) => {
    const query = normalizePublicQuery(request.query as Record<string, string | undefined>);
    return { success: true, data: await options.store.listModels({ ...query, publicOnly: true }) };
  });

  app.get('/api/v1/catalog/search', async (request) => {
    const query = normalizePublicQuery(request.query as Record<string, string | undefined>);
    return { success: true, data: await options.store.listModels({ ...query, publicOnly: true }) };
  });

  app.get('/api/v1/catalog/machine-models/:id', async (request) => {
    const { id } = idParamsSchema.parse(request.params);
    const model = await options.store.getModel(id, true);
    if (!model) throw httpError(404, 'Approved model not found');
    return { success: true, data: model };
  });

  app.get('/api/v1/catalog/machine-models/:id/images', async (request) => {
    const { id } = idParamsSchema.parse(request.params);
    return { success: true, data: await options.store.listModelImages(id, true) };
  });

  app.get('/api/v1/catalog/machine-models/:id/documents', async (request) => {
    const { id } = idParamsSchema.parse(request.params);
    return { success: true, data: await options.store.listModelDocuments(id, true) };
  });

  app.get('/api/v1/catalog/machine-models/:id/compatibility', async (request) => {
    const { id } = idParamsSchema.parse(request.params);
    const model = await options.store.getModel(id, true);
    if (!model) throw httpError(404, 'Approved model not found');
    return { success: true, data: compatibilityFor(model) };
  });

  app.post('/api/v1/admin/catalog/manufacturers', async (request) => {
    requireAdmin(request);
    const payload = manufacturerCreateSchema.parse(request.body);
    return { success: true, data: await options.store.createManufacturer(payload) };
  });

  app.patch('/api/v1/admin/catalog/manufacturers/:id', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    const payload = manufacturerUpdateSchema.parse(request.body);
    return { success: true, data: await options.store.updateManufacturer(id, payload) };
  });

  app.delete('/api/v1/admin/catalog/manufacturers/:id', async (request, reply) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    await options.store.archiveManufacturer(id);
    return reply.code(204).send();
  });

  app.post('/api/v1/admin/catalog/machine-models', async (request) => {
    requireAdmin(request);
    const payload = modelCreateSchema.parse(request.body);
    return { success: true, data: await options.store.createModel(payload) };
  });

  app.patch('/api/v1/admin/catalog/machine-models/:id', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    const payload = modelUpdateSchema.parse(request.body);
    return { success: true, data: await options.store.updateModel(id, payload) };
  });

  app.post('/api/v1/admin/catalog/machine-models/:id/approve', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    return { success: true, data: await options.store.approveModel(id, request.headers['x-user-id'] as string | undefined) };
  });

  app.post('/api/v1/admin/catalog/machine-models/:id/reject', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    const body = (request.body ?? {}) as { notes?: string };
    return { success: true, data: await options.store.rejectModel(id, request.headers['x-user-id'] as string | undefined, body.notes) };
  });

  app.post('/api/v1/admin/catalog/machine-models/:id/images', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    return { success: true, data: await options.store.createModelImage(id, imageCreateSchema.parse(request.body)) };
  });

  app.post('/api/v1/admin/catalog/machine-models/:id/documents', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    return { success: true, data: await options.store.createModelDocument(id, documentCreateSchema.parse(request.body)) };
  });

  app.post('/api/v1/admin/catalog/sources', async (request) => {
    requireAdmin(request);
    return { success: true, data: await options.store.createSource(sourceCreateSchema.parse(request.body)) };
  });

  app.patch('/api/v1/admin/catalog/sources/:id', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    return { success: true, data: await options.store.updateSource(id, sourceCreateSchema.partial().parse(request.body)) };
  });

  app.post('/api/v1/admin/catalog/crawl-jobs', async (request) => {
    requireAdmin(request);
    return { success: true, data: await options.store.createCrawlJob(crawlJobCreateSchema.parse(request.body)) };
  });

  app.get('/api/v1/admin/catalog/crawl-jobs', async (request) => {
    requireAdmin(request);
    return { success: true, data: await options.store.listCrawlJobs() };
  });

  app.get('/api/v1/admin/catalog/crawl-jobs/:id', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    const job = await options.store.getCrawlJob(id);
    if (!job) throw httpError(404, 'Crawl job not found');
    return { success: true, data: job };
  });

  app.get('/api/v1/admin/catalog/review-queue', async (request) => {
    requireAdmin(request);
    return { success: true, data: await options.store.reviewQueue() };
  });

  app.post('/api/v1/machines/from-catalog/:id', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    const body = linkCreateSchema.parse(request.body ?? {});
    const operationalMachineId = body.operational_machine_id ?? `local-${nanoid(10)}`;
    return { success: true, data: await options.store.linkMachineToCatalog(operationalMachineId, id) };
  });

  app.patch('/api/v1/machines/:id/catalog-link', async (request) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    const body = linkCreateSchema.required({ catalog_model_id: true }).parse(request.body ?? {});
    return { success: true, data: await options.store.linkMachineToCatalog(id, body.catalog_model_id) };
  });

  app.delete('/api/v1/machines/:id/catalog-link', async (request, reply) => {
    requireAdmin(request);
    const { id } = idParamsSchema.parse(request.params);
    await options.store.unlinkMachine(id);
    return reply.code(204).send();
  });

  app.get('/api/v1/admin/catalog/normalize/preview', async (request) => {
    requireAdmin(request);
    const query = request.query as { text?: string };
    const text = query.text ?? '';
    return {
      success: true,
      data: {
        category_code: normalizer.detectCategory(text),
        dimensions: normalizer.extractDimensions(text),
        payment_protocols: normalizer.detectPaymentProtocols(text),
        connectivity: normalizer.detectConnectivity(text)
      }
    };
  });
}

function normalizePublicQuery(query: Record<string, string | undefined>): Record<string, string | boolean | undefined> {
  return {
    q: query.q,
    category: query.category,
    manufacturer: query.manufacturer,
    status: 'approved',
    has_images: query.has_images === 'true' ? true : undefined
  };
}

function httpError(statusCode: number, message: string): Error & { statusCode: number } {
  return Object.assign(new Error(message), { statusCode });
}

function compatibilityFor(model: any): Record<string, unknown> {
  const category = model.primary_category_code ?? 'other';
  const byCategory: Record<string, { layout: string; modules: string[]; warnings: string[] }> = {
    coffee: {
      layout: 'ingredient_modules',
      modules: ['recipes', 'ingredients', 'cups', 'cleaning_cycles', 'cashless_payment'],
      warnings: ['No asumir estructura de slots. Validar modulos de ingredientes y limpieza.']
    },
    snack_drink: {
      layout: 'spiral_slots',
      modules: ['planogram', 'slot_replenishment', 'stock', 'temperature'],
      warnings: ['Validar bandejas, espirales y capacidad fisica antes de crear planograma operativo.']
    },
    ice_cream: {
      layout: 'frozen_trays_or_robotic',
      modules: ['temperature_control', 'frozen_inventory', 'image_reference', 'cashless_payment'],
      warnings: ['No asumir estructura de espirales. Requiere control de temperatura bajo cero.']
    }
  };
  const match = byCategory[category] ?? {
    layout: model.layout_type ?? 'unknown',
    modules: ['image_reference', 'manual_review'],
    warnings: ['Validar mecanismo fisico antes de asociar modulos operativos.']
  };
  return {
    catalog_model_id: model.id,
    category_code: category,
    recommended_layout_type: match.layout,
    compatible_modules: match.modules,
    not_recommended_modules: category === 'ice_cream' ? ['spiral_slot_planogram'] : [],
    warnings: match.warnings
  };
}
