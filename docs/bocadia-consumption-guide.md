# Bocadia Consumption Guide

Guia para consumir Machine Catalog API desde Bocadia.

## Objetivo

Machine Catalog API actua como catalogo tecnico global de fabricantes y modelos de maquinas vending. Bocadia debe usarlo como fuente de referencia para:

- buscar fabricantes y modelos oficiales;
- obtener imagenes/documentos/specs tecnicas;
- sugerir compatibilidad operativa por categoria;
- vincular una maquina operativa de Bocadia con un modelo global de catalogo;
- mantener datos curados separados de datos operativos del tenant.

La integracion recomendada es **server-to-server desde `D:\Proyectos\Bocadia\api`**. No exponer `ADMIN_API_KEY` ni llamadas admin desde el frontend tenant.

## Entornos

Local:

```text
MACHINE_CATALOG_API_URL=http://localhost:3000
MACHINE_CATALOG_ADMIN_API_KEY=<mismo valor que ADMIN_API_KEY del catalogo>
```

Produccion actual:

```text
MACHINE_CATALOG_API_URL=https://machine-catalog-api-6eyaoobeya-uc.a.run.app
MACHINE_CATALOG_ADMIN_API_KEY=<admin key server-side>
```

En Bocadia:

- Backend: consumir directamente Machine Catalog API.
- Frontend tenant: consumir endpoints propios de Bocadia; nunca llamar directo a endpoints admin del catalogo.
- Admin console: puede llamar a endpoints Bocadia que a su vez proxyean/adminstran el catalogo.

## Seguridad

Endpoints publicos internos no requieren header admin, pero se recomienda consumirlos desde backend Bocadia para controlar caching, auditoria y tenant boundaries.

Endpoints admin requieren:

```http
x-admin-api-key: <MACHINE_CATALOG_ADMIN_API_KEY>
```

Opcional para auditoria:

```http
x-user-id: <uuid-del-operador-admin>
```

No usar `SUPABASE_SERVICE_ROLE_KEY` fuera de Machine Catalog API.

## Formato de Respuesta

Respuesta exitosa:

```json
{
  "success": true,
  "data": {}
}
```

Listados:

```json
{
  "success": true,
  "data": []
}
```

Errores esperados:

```json
{
  "error": "Admin API key required"
}
```

Codigos relevantes:

- `200`: operacion exitosa.
- `204`: delete/unlink exitoso sin cuerpo.
- `403`: falta o no coincide `x-admin-api-key`.
- `404`: recurso no encontrado o modelo no aprobado en endpoints publicos.
- `503`: crawler runner no configurado para ejecutar jobs.

## Modelo Mental para Bocadia

Separar dos conceptos:

- `catalog_model_id`: UUID global del modelo tecnico en Machine Catalog API.
- `operational_machine_id`: ID de la maquina real dentro de Bocadia.

Bocadia no debe copiar todo el catalogo como datos operativos. Debe guardar la referencia `catalog_model_id` y cachear datos derivados si necesita rendimiento.

Flujo recomendado:

1. Usuario/admin busca modelo en catalogo.
2. Bocadia muestra resultados aprobados.
3. Usuario selecciona modelo.
4. Bocadia guarda relacion maquina operativa -> modelo de catalogo.
5. Bocadia usa `compatibility` para sugerir layout/modulos.
6. Bocadia mantiene planograma, inventario, precios y operaciones como datos tenant propios.

## Endpoints Publicos Internos

### Health

```http
GET /health
```

Uso:

```bash
curl http://localhost:3000/health
```

### Categorias

```http
GET /api/v1/catalog/categories
```

Uso en Bocadia:

- Poblar filtros de busqueda.
- Mapear modelos a flujos de negocio.

### Fabricantes

```http
GET /api/v1/catalog/manufacturers
GET /api/v1/catalog/manufacturers/:id
GET /api/v1/catalog/manufacturers/:id/models
```

Query soportada en listado:

```text
q=<texto>
category=<codigo_categoria>
manufacturer=<texto_o_slug>
has_images=true
```

Ejemplo:

```bash
curl "http://localhost:3000/api/v1/catalog/manufacturers?q=azkoyen"
```

### Modelos

```http
GET /api/v1/catalog/machine-models
GET /api/v1/catalog/machine-models/:id
GET /api/v1/catalog/search
```

Los endpoints publicos solo devuelven modelos `approved`.

Query:

```text
q=<texto>
category=<codigo_categoria>
manufacturer=<texto_o_slug>
has_images=true
```

Ejemplos:

```bash
curl "http://localhost:3000/api/v1/catalog/search?q=Vitro%20X5&has_images=true"
curl "http://localhost:3000/api/v1/catalog/machine-models?category=coffee"
```

Campos importantes esperados:

```json
{
  "id": "catalog-model-uuid",
  "manufacturer_id": "manufacturer-uuid",
  "manufacturer_name": "Azkoyen",
  "model_name": "Vitro X5 Touch",
  "primary_category_code": "coffee",
  "status": "approved",
  "source_url": "https://azkoyenvending.com/vitro/vitro-x5/",
  "official_product_url": "https://azkoyenvending.com/vitro/vitro-x5/",
  "confidence_score": 1,
  "height_mm": 865,
  "width_mm": 480,
  "depth_mm": 610,
  "weight_kg": 63,
  "voltage": null,
  "power_requirements": null,
  "capacity_description": null,
  "primary_image_url": "https://..."
}
```

La forma exacta puede incluir mas campos segun la vista Supabase `machine_catalog_model_details`.

### Imagenes

```http
GET /api/v1/catalog/machine-models/:id/images
```

Uso en Bocadia:

- Mostrar referencia visual en ficha de maquina.
- No asumir licencia de redistribucion publica. El campo `license_status` indica restricciones.

### Documentos

```http
GET /api/v1/catalog/machine-models/:id/documents
```

Tipos:

- `brochure`
- `datasheet`
- `manual`
- `catalog`
- `unknown`

### Compatibilidad Operativa

```http
GET /api/v1/catalog/machine-models/:id/compatibility
```

Ejemplo de respuesta:

```json
{
  "success": true,
  "data": {
    "catalog_model_id": "catalog-model-uuid",
    "category_code": "snack_drink",
    "recommended_layout_type": "spiral_slots",
    "compatible_modules": [
      "planogram",
      "slot_replenishment",
      "stock",
      "temperature"
    ],
    "not_recommended_modules": [],
    "warnings": [
      "Validar bandejas, espirales y capacidad fisica antes de crear planograma operativo."
    ]
  }
}
```

Uso en Bocadia:

- Preseleccionar tipo de layout.
- Mostrar advertencias antes de crear planograma.
- Evitar asumir estructuras de slots para maquinas de cafe, lockers o frozen.

## Endpoints de Integracion Operativa

Estos endpoints requieren `x-admin-api-key`.

### Crear o Vincular Maquina desde Catalogo

```http
POST /api/v1/machines/from-catalog/:id
```

Donde `:id` es `catalog_model_id`.

Body opcional:

```json
{
  "operational_machine_id": "bocadia-machine-id"
}
```

Ejemplo:

```bash
curl -X POST "http://localhost:3000/api/v1/machines/from-catalog/CATALOG_MODEL_UUID" \
  -H "content-type: application/json" \
  -H "x-admin-api-key: $MACHINE_CATALOG_ADMIN_API_KEY" \
  -d "{\"operational_machine_id\":\"BOCADIA_MACHINE_ID\"}"
```

### Vincular una Maquina Existente

```http
PATCH /api/v1/machines/:id/catalog-link
```

Donde `:id` es `operational_machine_id`.

Body:

```json
{
  "catalog_model_id": "catalog-model-uuid"
}
```

Ejemplo:

```bash
curl -X PATCH "http://localhost:3000/api/v1/machines/BOCADIA_MACHINE_ID/catalog-link" \
  -H "content-type: application/json" \
  -H "x-admin-api-key: $MACHINE_CATALOG_ADMIN_API_KEY" \
  -d "{\"catalog_model_id\":\"CATALOG_MODEL_UUID\"}"
```

### Desvincular

```http
DELETE /api/v1/machines/:id/catalog-link
```

Ejemplo:

```bash
curl -X DELETE "http://localhost:3000/api/v1/machines/BOCADIA_MACHINE_ID/catalog-link" \
  -H "x-admin-api-key: $MACHINE_CATALOG_ADMIN_API_KEY"
```

## Endpoints Admin para Backoffice de Bocadia

Usar solo desde admin console o backend admin de Bocadia.

### Modelos Admin

```http
GET /api/v1/admin/catalog/machine-models
GET /api/v1/admin/catalog/machine-models/:id
POST /api/v1/admin/catalog/machine-models
PATCH /api/v1/admin/catalog/machine-models/:id
POST /api/v1/admin/catalog/machine-models/:id/approve
POST /api/v1/admin/catalog/machine-models/:id/reject
POST /api/v1/admin/catalog/machine-models/:id/images
POST /api/v1/admin/catalog/machine-models/:id/documents
POST /api/v1/admin/catalog/machine-models/:id/merge
```

Query admin:

```text
q=<texto>
category=<codigo_categoria>
manufacturer=<texto_o_slug>
status=draft|pending_review|approved|rejected|archived
has_images=true
```

### Cola de Revision

```http
GET /api/v1/admin/catalog/review-queue
GET /api/v1/admin/catalog/review-queue/:id
POST /api/v1/admin/catalog/review-queue/:id/approve
POST /api/v1/admin/catalog/review-queue/:id/reject
POST /api/v1/admin/catalog/review-queue/:id/edit
```

Approve con ediciones:

```json
{
  "reviewed_by": "admin-user-uuid",
  "edits": {
    "model_name": "Vitro X5 Touch",
    "status": "approved"
  }
}
```

Reject:

```json
{
  "reviewed_by": "admin-user-uuid",
  "notes": "La pagina no corresponde al modelo."
}
```

### Duplicados

```http
GET /api/v1/admin/catalog/duplicates
POST /api/v1/admin/catalog/machine-models/:id/merge
```

Merge:

```json
{
  "target_model_id": "canonical-model-uuid",
  "reviewed_by": "admin-user-uuid"
}
```

### Fuentes y Crawling

```http
POST /api/v1/admin/catalog/sources
GET /api/v1/admin/catalog/sources
GET /api/v1/admin/catalog/sources/:id
PATCH /api/v1/admin/catalog/sources/:id
POST /api/v1/admin/catalog/source-configs
PATCH /api/v1/admin/catalog/source-configs/:id
POST /api/v1/admin/catalog/crawl-jobs
GET /api/v1/admin/catalog/crawl-jobs
GET /api/v1/admin/catalog/crawl-jobs/:id
POST /api/v1/admin/catalog/crawl-jobs/:id/run
GET /api/v1/admin/catalog/crawl-jobs/:id/logs
```

Crear source config:

```json
{
  "manufacturer_id": "manufacturer-uuid",
  "base_url": "https://azkoyenvending.com/vitro/",
  "allowed_domains": ["azkoyenvending.com"],
  "crawl_strategy": "single_page",
  "product_url_patterns": ["/vitro/"],
  "exclude_patterns": ["/blog/", "/news/"],
  "data_sources": ["html", "jsonld", "opengraph", "pdf"],
  "image_selectors": ["meta[property='og:image']", "img"],
  "refresh_frequency_days": 30,
  "max_pages_per_run": 50,
  "delay_seconds": 2,
  "dynamic_rendering": true,
  "status": "active"
}
```

Crear crawl job:

```json
{
  "manufacturer_id": "manufacturer-uuid",
  "source_config_id": "source-config-uuid",
  "job_type": "product_page",
  "max_pages": 20,
  "created_by": "admin-user-uuid"
}
```

## Cliente TypeScript Recomendado para Bocadia API

Crear algo equivalente en `D:\Proyectos\Bocadia\api`, no en el frontend.

```ts
type CatalogApiResponse<T> = {
  success: boolean;
  data: T;
};

type CatalogSearchParams = {
  q?: string;
  category?: string;
  manufacturer?: string;
  hasImages?: boolean;
};

export class MachineCatalogClient {
  constructor(
    private readonly baseUrl: string,
    private readonly adminApiKey?: string
  ) {}

  async searchModels(params: CatalogSearchParams = {}) {
    const url = new URL('/api/v1/catalog/search', this.baseUrl);
    if (params.q) url.searchParams.set('q', params.q);
    if (params.category) url.searchParams.set('category', params.category);
    if (params.manufacturer) url.searchParams.set('manufacturer', params.manufacturer);
    if (params.hasImages) url.searchParams.set('has_images', 'true');
    return this.get<any[]>(url);
  }

  async getModel(id: string) {
    return this.get<any>(new URL(`/api/v1/catalog/machine-models/${id}`, this.baseUrl));
  }

  async getCompatibility(id: string) {
    return this.get<any>(new URL(`/api/v1/catalog/machine-models/${id}/compatibility`, this.baseUrl));
  }

  async linkOperationalMachine(operationalMachineId: string, catalogModelId: string) {
    return this.request<any>(`/api/v1/machines/${operationalMachineId}/catalog-link`, {
      method: 'PATCH',
      admin: true,
      body: {
        catalog_model_id: catalogModelId
      }
    });
  }

  async unlinkOperationalMachine(operationalMachineId: string) {
    await this.request<void>(`/api/v1/machines/${operationalMachineId}/catalog-link`, {
      method: 'DELETE',
      admin: true
    });
  }

  private async get<T>(url: URL): Promise<T> {
    return this.requestUrl<T>(url, { method: 'GET' });
  }

  private async request<T>(
    path: string,
    options: {
      method: string;
      admin?: boolean;
      body?: unknown;
    }
  ): Promise<T> {
    return this.requestUrl<T>(new URL(path, this.baseUrl), options);
  }

  private async requestUrl<T>(
    url: URL,
    options: {
      method: string;
      admin?: boolean;
      body?: unknown;
    }
  ): Promise<T> {
    const headers: Record<string, string> = {
      accept: 'application/json'
    };
    if (options.body !== undefined) headers['content-type'] = 'application/json';
    if (options.admin) {
      if (!this.adminApiKey) throw new Error('Machine Catalog admin API key is not configured');
      headers['x-admin-api-key'] = this.adminApiKey;
    }
    const response = await fetch(url, {
      method: options.method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body)
    });
    if (response.status === 204) return undefined as T;
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(payload?.error ?? `Machine Catalog request failed: ${response.status}`);
    }
    return (payload as CatalogApiResponse<T>).data;
  }
}
```

Uso:

```ts
const catalogClient = new MachineCatalogClient(
  process.env.MACHINE_CATALOG_API_URL!,
  process.env.MACHINE_CATALOG_ADMIN_API_KEY
);

const results = await catalogClient.searchModels({
  q: 'Vitro X5',
  hasImages: true
});
```

## Endpoints Bocadia Sugeridos

En lugar de llamar Machine Catalog desde el frontend, crear endpoints propios en Bocadia:

```http
GET /api/v1/catalog/search
GET /api/v1/catalog/machine-models/:id
GET /api/v1/catalog/machine-models/:id/compatibility
PATCH /api/v1/machines/:id/catalog-link
DELETE /api/v1/machines/:id/catalog-link
```

Estos endpoints Bocadia deben:

- validar tenant/auth del usuario;
- llamar Machine Catalog server-to-server;
- guardar `catalog_model_id` en la maquina operativa;
- registrar auditoria interna si aplica;
- devolver solo lo necesario al frontend.

## Flujo UX Recomendado en Bocadia

### Alta o Edicion de Maquina

1. Usuario escribe fabricante/modelo.
2. Bocadia llama `GET /api/v1/catalog/search?q=...`.
3. Mostrar candidatos con imagen, fabricante, categoria y confidence.
4. Usuario selecciona modelo.
5. Bocadia llama `PATCH /api/v1/machines/:id/catalog-link`.
6. Bocadia llama `GET /compatibility`.
7. UI sugiere layout/modulos y muestra advertencias.

### Planograma

Si `compatibility.recommended_layout_type` es:

- `spiral_slots`: habilitar planograma por slots/bandejas.
- `ingredient_modules`: usar flujo de ingredientes/recetas/cafe.
- `frozen_trays_or_robotic`: requerir temperatura/frozen inventory.
- `unknown`: bloquear automatizacion completa y pedir revision manual.

## Caching

Recomendado en Bocadia:

- Cachear busquedas por `q/category/manufacturer/has_images` durante 5-30 minutos.
- Cachear detalle de modelo por `catalog_model_id` durante 24 horas.
- Invalidar manualmente si admin cambia el link de maquina.

No cachear:

- review queue;
- datos admin;
- resultados de crawl jobs.

## Manejo de Calidad

Campos importantes:

- `status`: solo usar `approved` para frontend tenant.
- `confidence_score`: mostrar advertencia si es menor a `0.85`.
- `license_status`: no asumir que imagen puede redistribuirse publicamente.
- `compatibility.warnings`: mostrar antes de crear planograma.

Regla sugerida:

```text
confidence_score >= 0.85: mostrar como candidato normal
0.65 <= confidence_score < 0.85: mostrar con advertencia
confidence_score < 0.65: solo admin/revision
```

## Checklist de Integracion

- [ ] Configurar `MACHINE_CATALOG_API_URL` en Bocadia API.
- [ ] Configurar `MACHINE_CATALOG_ADMIN_API_KEY` solo en backend/admin.
- [ ] Crear cliente server-to-server.
- [ ] Crear endpoints proxy en Bocadia API.
- [ ] Agregar columna/campo `catalog_model_id` en maquinas operativas si no existe.
- [ ] Validar que frontend tenant no recibe claves admin.
- [ ] Agregar busqueda en alta/edicion de maquina.
- [ ] Agregar vista de compatibilidad antes de planograma.
- [ ] Agregar logs/auditoria al vincular/desvincular.
- [ ] Probar contra `http://localhost:3000`.
- [ ] Probar contra Cloud Run.

## Smoke Tests

Buscar modelo:

```bash
curl "http://localhost:3000/api/v1/catalog/search?q=Vitro%20X5&has_images=true"
```

Detalle:

```bash
curl "http://localhost:3000/api/v1/catalog/machine-models/CATALOG_MODEL_UUID"
```

Compatibilidad:

```bash
curl "http://localhost:3000/api/v1/catalog/machine-models/CATALOG_MODEL_UUID/compatibility"
```

Vincular maquina Bocadia:

```bash
curl -X PATCH "http://localhost:3000/api/v1/machines/BOCADIA_MACHINE_ID/catalog-link" \
  -H "content-type: application/json" \
  -H "x-admin-api-key: $MACHINE_CATALOG_ADMIN_API_KEY" \
  -d "{\"catalog_model_id\":\"CATALOG_MODEL_UUID\"}"
```

Desvincular:

```bash
curl -X DELETE "http://localhost:3000/api/v1/machines/BOCADIA_MACHINE_ID/catalog-link" \
  -H "x-admin-api-key: $MACHINE_CATALOG_ADMIN_API_KEY"
```

## Consideraciones para Produccion

- Mantener Machine Catalog API como servicio separado.
- No mezclar catalogo global con datos tenant.
- No exponer admin key en Expo, web frontend ni admin console client-side.
- Usar backend Bocadia como boundary de permisos.
- Tratar imagenes oficiales como referencias, no como assets libres.
- Usar review queue para datos con baja confianza.
- Usar Cloud Run URL solo desde backend o variables server-side.
