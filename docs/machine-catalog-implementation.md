# Machine Catalog Implementation

## Infraestructura actual

El repositorio remoto `diegocastroh/machine-catalog-API` tenia solo un `README.md` inicial. No habia stack, rutas, migraciones ni convenciones previas. Por eso se creo una API independiente en Fastify + TypeScript para ejecucion local en `http://localhost:3000/`.

Supabase se valido via MCP contra el proyecto `yptzopnarugsoighqnph`. Antes de aplicar cambios no habia tablas ni migraciones en `public`.

## Cambios por area

Backend:

- `src/app.ts`: construye Fastify con CORS, rate limit, Swagger, health check y handler centralizado de errores.
- `src/server.ts`: carga variables de entorno y conecta Supabase.
- `src/catalog/routes.ts`: define endpoints publicos internos, admin y link operativo.
- `src/catalog/supabase-store.ts`: encapsula acceso a Supabase.
- `src/catalog/normalizer.ts`: normalizacion inicial, conversiones, deteccion de categoria, validacion anti-SSRF y score.
- `src/catalog/deduplicator.ts`: comparacion exacta, por fuente/hash y fuzzy para candidatos duplicados.
- `src/catalog/review-service.ts`: construccion de aprobaciones/rechazos de extractions.
- `src/catalog/crawler-runner.ts`: orquestacion local del worker Python.
- `src/catalog/schemas.ts`: validacion Zod de payloads.
- `workers/scraper`: paquete Python/Scrapy para robots, crawling controlado y extraccion.

Base de datos:

- `supabase/migrations/202605240001_machine_catalog.sql`: crea tablas, indices, vista `machine_catalog_model_details`, triggers `updated_at`, RLS y seeds.
- `supabase/migrations/202605240002_scraping_review_pipeline.sql`: agrega source configs, logs de crawl, duplicados y campos de progreso de jobs.
- Migracion aplicada en Supabase como `machine_catalog_base`.

Pruebas:

- `tests/normalizer.test.ts`: categorias, dimensiones, confidence score y URL validation.
- `tests/deduplicator.test.ts`: exact, fuzzy y no-match.
- `tests/review-flow.test.ts`: approve/reject de extraction.
- `tests/routes.test.ts`: admin key y regla de no publicar modelos pendientes en endpoints publicos.
- `workers/scraper/tests/test_extractors.py`: robots y extraccion de JSON-LD/OpenGraph/HTML/assets con fixtures locales.

## Seguridad

- Los endpoints admin requieren `x-admin-api-key`.
- La service role key de Supabase se lee desde entorno y no se versiona.
- RLS esta activado en las tablas del schema `public`.
- No se crean politicas permisivas para `anon` ni `authenticated`.
- La API bloquea URLs `localhost`, rangos privados, `169.254.*`, metadata services y esquemas no HTTP/HTTPS.
- Los endpoints publicos de modelos consultan solo `status=approved`.
- Scrapy se configura con `ROBOTSTXT_OBEY`, delay minimo, concurrencia baja por dominio, AutoThrottle y retries.

## Matriz de cobertura del MD

| Requisito | Estado |
| --- | --- |
| Migraciones y entidades de catalogo | Implementado |
| CRUD manual fabricantes/modelos | Implementado |
| Imagenes/documentos con fuente | Implementado |
| Source configs y crawl jobs | Implementado |
| Worker Scrapy controlado | Implementado para fuentes configuradas |
| robots.txt, delays, AutoThrottle | Implementado en worker |
| Raw y normalized extractions | Implementado |
| Review approve/reject/edit | Implementado por API |
| Merge/deduplicacion | Implementado backend/API |
| OpenAPI | Implementado en `/docs` |
| Panel admin visual | Pendiente fuera del alcance acordado |
| Discovery externo Brave Search | Pendiente fuera del alcance acordado |
| Cloud Run | Pendiente fuera del alcance acordado |

## Validaciones ejecutadas

- `npm run typecheck`
- `npm run lint`
- `npm test`
- `python -m pytest workers/scraper/tests`
- `npm run build`
- Supabase MCP: `list_tables`, `list_migrations`, conteo de seeds.

Resultado Supabase:

- 15 tablas creadas con RLS habilitado.
- 10 categorias semilla.
- 29 fabricantes semilla.
- 0 modelos iniciales.

## Riesgos y pendientes

- Falta UI administrativa.
- Falta RBAC real con usuarios/roles; por ahora se usa API key local para admin.
- La integracion con maquinas operativas es un link externo por `operational_machine_id`, porque este repo no contiene el backend Bocadia original.
- Para ejecutar localmente contra Supabase se requiere completar `.env` con una `SUPABASE_SERVICE_ROLE_KEY`.
