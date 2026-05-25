import cors from '@fastify/cors';
import rateLimit from '@fastify/rate-limit';
import swagger from '@fastify/swagger';
import swaggerUi from '@fastify/swagger-ui';
import Fastify from 'fastify';
import { ZodError } from 'zod';
import { registerCatalogRoutes } from './catalog/routes.js';
import type { CrawlerRunner } from './catalog/crawler-runner.js';
import type { CatalogStore } from './catalog/store.js';

export type BuildAppOptions = {
  store: CatalogStore;
  adminApiKey: string;
  crawlerRunner?: CrawlerRunner;
};

export async function buildApp(options: BuildAppOptions) {
  const app = Fastify({ logger: true });

  await app.register(cors, { origin: true });
  await app.register(rateLimit, { max: 120, timeWindow: '1 minute' });
  await app.register(swagger, {
    openapi: {
      info: {
        title: 'Machine Catalog API',
        description: 'Catalogo global de fabricantes y modelos de maquinas dispensadoras.',
        version: '0.1.0'
      }
    }
  });
  await app.register(swaggerUi, { routePrefix: '/docs' });

  app.get('/health', async () => ({ success: true, status: 'ok' }));
  await registerCatalogRoutes(app, options);

  app.setErrorHandler((error: Error & { statusCode?: number }, _request, reply) => {
    if (error instanceof ZodError) {
      return reply.code(422).send({ success: false, error: 'Validation error', details: error.flatten() });
    }
    const statusCode = error.statusCode && error.statusCode >= 400 ? error.statusCode : 500;
    const message = statusCode >= 500 ? 'Internal server error' : error.message;
    return reply.code(statusCode).send({ success: false, error: message });
  });

  return app;
}
