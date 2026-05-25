# Machine Catalog API

API local para consultar y administrar un catalogo global de fabricantes y modelos de maquinas vending/dispensadoras. La persistencia esta preparada para Supabase en el proyecto `yptzopnarugsoighqnph`.

## Estado implementado

- API Fastify + TypeScript.
- Persistencia en Supabase mediante `@supabase/supabase-js`.
- Migracion SQL versionada en `supabase/migrations/202605240001_machine_catalog.sql`.
- RLS activado para todas las tablas publicas creadas.
- Seed inicial de 10 categorias y 29 fabricantes.
- Endpoints publicos internos para fabricantes, categorias, modelos, imagenes, documentos, busqueda y compatibilidad.
- Endpoints admin para fabricantes, modelos, aprobar/rechazar, imagenes, documentos, fuentes, crawl jobs y cola de revision.
- Endpoints de link con maquina operativa por `operational_machine_id`.
- Normalizador inicial para categorias, dimensiones, unidades, protocolos, conectividad, URLs y confidence score.
- OpenAPI/Swagger en `/docs`.

## Requisitos

- Node.js 22+
- Una key backend de Supabase. Usa `SUPABASE_SERVICE_ROLE_KEY` solo en servidor local/backend. No la expongas en frontend.

## Configuracion local

```bash
npm install
copy .env.example .env
```

Edita `.env`:

```bash
PORT=3000
HOST=0.0.0.0
SUPABASE_URL=https://yptzopnarugsoighqnph.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
ADMIN_API_KEY=...
```

Ejecutar en local:

```bash
npm run dev
```

URLs locales:

- API: `http://localhost:3000`
- Health: `http://localhost:3000/health`
- Swagger UI: `http://localhost:3000/docs`

## Endpoints principales

Publicos internos:

- `GET /api/v1/catalog/manufacturers`
- `GET /api/v1/catalog/manufacturers/:id`
- `GET /api/v1/catalog/manufacturers/:id/models`
- `GET /api/v1/catalog/categories`
- `GET /api/v1/catalog/machine-models`
- `GET /api/v1/catalog/machine-models/:id`
- `GET /api/v1/catalog/machine-models/:id/images`
- `GET /api/v1/catalog/machine-models/:id/documents`
- `GET /api/v1/catalog/machine-models/:id/compatibility`
- `GET /api/v1/catalog/search?q=&category=&manufacturer=&has_images=`

Admin, requieren header `x-admin-api-key`:

- `POST /api/v1/admin/catalog/manufacturers`
- `PATCH /api/v1/admin/catalog/manufacturers/:id`
- `DELETE /api/v1/admin/catalog/manufacturers/:id`
- `POST /api/v1/admin/catalog/machine-models`
- `PATCH /api/v1/admin/catalog/machine-models/:id`
- `POST /api/v1/admin/catalog/machine-models/:id/approve`
- `POST /api/v1/admin/catalog/machine-models/:id/reject`
- `POST /api/v1/admin/catalog/machine-models/:id/images`
- `POST /api/v1/admin/catalog/machine-models/:id/documents`
- `POST /api/v1/admin/catalog/sources`
- `PATCH /api/v1/admin/catalog/sources/:id`
- `POST /api/v1/admin/catalog/crawl-jobs`
- `GET /api/v1/admin/catalog/crawl-jobs`
- `GET /api/v1/admin/catalog/crawl-jobs/:id`
- `GET /api/v1/admin/catalog/review-queue`

Integracion operativa:

- `POST /api/v1/machines/from-catalog/:catalogModelId`
- `PATCH /api/v1/machines/:id/catalog-link`
- `DELETE /api/v1/machines/:id/catalog-link`

## Ejemplo de alta manual

```bash
curl -X POST http://localhost:3000/api/v1/admin/catalog/manufacturers \
  -H "content-type: application/json" \
  -H "x-admin-api-key: $ADMIN_API_KEY" \
  -d "{\"name\":\"Necta\",\"country\":\"Italy\",\"website_url\":\"https://www.evocagroup.com\"}"
```

## Validacion

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

## Alcance pendiente

- Worker real de scraping con Scrapy/Playwright.
- Robots.txt checker ejecutable por job.
- Extraccion real de HTML, JSON-LD, Open Graph y PDF.
- Panel administrativo visual.
- RBAC integrado con un proveedor de identidad real.
- Despliegue Cloud Run. Para esta fase se dejo solo ejecucion local.
