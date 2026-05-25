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
- `src/catalog/schemas.ts`: validacion Zod de payloads.

Base de datos:

- `supabase/migrations/202605240001_machine_catalog.sql`: crea tablas, indices, vista `machine_catalog_model_details`, triggers `updated_at`, RLS y seeds.
- Migracion aplicada en Supabase como `machine_catalog_base`.

Pruebas:

- `tests/normalizer.test.ts`: categorias, dimensiones, confidence score y URL validation.
- `tests/routes.test.ts`: admin key y regla de no publicar modelos pendientes en endpoints publicos.

## Seguridad

- Los endpoints admin requieren `x-admin-api-key`.
- La service role key de Supabase se lee desde entorno y no se versiona.
- RLS esta activado en las tablas del schema `public`.
- No se crean politicas permisivas para `anon` ni `authenticated`.
- La API bloquea URLs `localhost`, rangos privados, `169.254.*`, metadata services y esquemas no HTTP/HTTPS.
- Los endpoints publicos de modelos consultan solo `status=approved`.

## Validaciones ejecutadas

- `npm run typecheck`
- `npm run lint`
- `npm test`
- `npm run build`
- Supabase MCP: `list_tables`, `list_migrations`, conteo de seeds.

Resultado Supabase:

- 15 tablas creadas con RLS habilitado.
- 10 categorias semilla.
- 29 fabricantes semilla.
- 0 modelos iniciales.

## Riesgos y pendientes

- El crawler aun no ejecuta scraping real; esta fase solo crea fuentes y jobs en estado `queued`.
- Falta UI administrativa.
- Falta RBAC real con usuarios/roles; por ahora se usa API key local para admin.
- La integracion con maquinas operativas es un link externo por `operational_machine_id`, porque este repo no contiene el backend Bocadia original.
- Para ejecutar localmente contra Supabase se requiere completar `.env` con una `SUPABASE_SERVICE_ROLE_KEY`.
