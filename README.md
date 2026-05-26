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
- Worker Python/Scrapy local para fuentes configuradas, robots.txt, AutoThrottle, JSON-LD, OpenGraph, HTML, imagenes y PDFs enlazados.
- Cola de revision para extractions normalizadas, merge/deduplicacion y logs de crawl.
- OpenAPI/Swagger en `/docs`.

## Requisitos

- Node.js 22+
- Python 3.11+
- Una key backend de Supabase. Usa `SUPABASE_SERVICE_ROLE_KEY` solo en servidor local/backend. No la expongas en frontend.

## Configuracion local

```bash
npm install
python -m pip install -r workers/scraper/requirements.txt
python -m playwright install chromium
copy .env.example .env
```

Edita `.env`:

```bash
PORT=3000
HOST=0.0.0.0
SUPABASE_URL=https://yptzopnarugsoighqnph.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
ADMIN_API_KEY=...
PYTHON_EXECUTABLE=python
SCRAPER_OUTPUT_DIR=.scraper-output
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
- `GET /api/v1/admin/catalog/machine-models`
- `GET /api/v1/admin/catalog/machine-models/:id`
- `PATCH /api/v1/admin/catalog/machine-models/:id`
- `POST /api/v1/admin/catalog/machine-models/:id/approve`
- `POST /api/v1/admin/catalog/machine-models/:id/reject`
- `POST /api/v1/admin/catalog/machine-models/:id/images`
- `POST /api/v1/admin/catalog/machine-models/:id/documents`
- `POST /api/v1/admin/catalog/sources`
- `GET /api/v1/admin/catalog/sources`
- `GET /api/v1/admin/catalog/sources/:id`
- `PATCH /api/v1/admin/catalog/sources/:id`
- `POST /api/v1/admin/catalog/source-configs`
- `PATCH /api/v1/admin/catalog/source-configs/:id`
- `POST /api/v1/admin/catalog/crawl-jobs`
- `GET /api/v1/admin/catalog/crawl-jobs`
- `GET /api/v1/admin/catalog/crawl-jobs/:id`
- `POST /api/v1/admin/catalog/crawl-jobs/:id/run`
- `GET /api/v1/admin/catalog/crawl-jobs/:id/logs`
- `GET /api/v1/admin/catalog/review-queue`
- `GET /api/v1/admin/catalog/review-queue/:id`
- `POST /api/v1/admin/catalog/review-queue/:id/approve`
- `POST /api/v1/admin/catalog/review-queue/:id/reject`
- `POST /api/v1/admin/catalog/review-queue/:id/edit`
- `GET /api/v1/admin/catalog/duplicates`
- `POST /api/v1/admin/catalog/machine-models/:id/merge`

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

## Ejemplo de fuente y crawl local

1. Crear source config:

```bash
curl -X POST http://localhost:3000/api/v1/admin/catalog/source-configs \
  -H "content-type: application/json" \
  -H "x-admin-api-key: $ADMIN_API_KEY" \
  -d "{\"manufacturer_id\":\"MANUFACTURER_UUID\",\"base_url\":\"https://example.com/products/opera-touch\",\"allowed_domains\":[\"example.com\"],\"crawl_strategy\":\"single_page\",\"max_pages_per_run\":10,\"delay_seconds\":2}"
```

2. Crear crawl job:

```bash
curl -X POST http://localhost:3000/api/v1/admin/catalog/crawl-jobs \
  -H "content-type: application/json" \
  -H "x-admin-api-key: $ADMIN_API_KEY" \
  -d "{\"manufacturer_id\":\"MANUFACTURER_UUID\",\"source_config_id\":\"SOURCE_CONFIG_UUID\",\"job_type\":\"product_page\",\"max_pages\":10}"
```

3. Ejecutar job local:

```bash
curl -X POST http://localhost:3000/api/v1/admin/catalog/crawl-jobs/CRAWL_JOB_UUID/run \
  -H "x-admin-api-key: $ADMIN_API_KEY"
```

El worker respeta robots.txt mediante Scrapy, usa AutoThrottle, limita concurrencia por dominio y deja todo resultado automatico en `normalized_extractions` para revision. Playwright solo se usa cuando `dynamic_rendering=true` en la source config.

## Importar SQLite de Colab

El importador toma `catalogo_vending` desde SQLite, crea fabricantes faltantes, publica modelos aprobados, guarda imagen principal y conserva el JSON tecnico original en `machine_model_specs.raw_specs`.

```bash
python scripts/import-vending-sqlite.py --db C:\Users\diego\Downloads\vending_api_data.db --base-url http://localhost:3000
```

Opciones utiles:

```bash
python scripts/import-vending-sqlite.py --from-id 86 --to-id 113
python scripts/import-vending-sqlite.py --dry-run
```

## Scraping directo CSV -> Supabase

Instalar dependencias del pipeline local:

```bash
python -m pip install -r scripts/requirements-supabase-pipeline.txt
python -m playwright install chromium
```

Ejecutar con Crawl4AI local:

```bash
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --extractor crawl4ai --start-row 1
```

Probar sin guardar:

```bash
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --extractor crawl4ai --start-row 1 --limit 5 --dry-run
```

Ver URL usada, imagen detectada, categoria y muestra del contenido:

```bash
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --extractor crawl4ai --start-row 1 --limit 5 --dry-run --verbose
```

Ejecutar por bloques con control de calidad:

```bash
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --extractor crawl4ai --start-row 1 --limit 50 --verbose --min-quality 0.45 --review-below-quality 0.70
```

`--min-quality` evita guardar extracciones demasiado debiles. `--review-below-quality` guarda modelos con baja confianza como `pending_review`; las extracciones sobre el umbral quedan `approved`.

Ejecutar con IA local mediante Ollama en todas las filas:

```bash
ollama pull qwen2.5:7b-instruct
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --extractor crawl4ai --ai-mode always --ai-model qwen2.5:7b-instruct --start-row 1 --limit 20 --verbose --review-below-quality 0.85
```

La IA rellena campos faltantes y marca conflictos como `ai_conflict:*`; esos conflictos bajan la confianza para que el registro quede en revision.

Para reducir uso de RAM/VRAM con Ollama:

```bash
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --extractor crawl4ai --ai-mode always --ai-model qwen2.5:7b-instruct --ai-num-ctx 4096 --ai-max-chars 4000 --ai-timeout 240 --start-row 1 --limit 20 --verbose
```

## Consultas rapidas

Local:

```bash
python scripts/check-machine.py "W-USI" --base-url http://localhost:3000 --detail
```

Cloud Run:

```bash
python scripts/check-machine.py "JL500" --base-url https://machine-catalog-api-6eyaoobeya-uc.a.run.app --limit 5
```

URL de produccion actual:

- `https://machine-catalog-api-6eyaoobeya-uc.a.run.app`

## Validacion

```bash
npm run typecheck
npm run lint
npm test
npm run test:worker
npm run build
```

## Alcance pendiente

- Panel administrativo visual.
- RBAC integrado con un proveedor de identidad real.
- Migrar variables sensibles de Cloud Run a Secret Manager si se requiere rotacion/auditoria formal.
