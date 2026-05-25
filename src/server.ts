import { buildApp } from './app.js';
import { SupabaseCatalogStore } from './catalog/supabase-store.js';
import { loadConfig } from './config.js';

const config = loadConfig();
const store = SupabaseCatalogStore.fromCredentials(config.supabaseUrl, config.supabaseServiceRoleKey);
const app = await buildApp({ store, adminApiKey: config.adminApiKey });

await app.listen({ port: config.port, host: config.host });
