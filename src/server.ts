import { buildApp } from './app.js';
import { LocalCrawlerRunner } from './catalog/crawler-runner.js';
import { SupabaseCatalogStore } from './catalog/supabase-store.js';
import { loadConfig } from './config.js';

const config = loadConfig();
const store = SupabaseCatalogStore.fromCredentials(config.supabaseUrl, config.supabaseServiceRoleKey);
const crawlerRunner = new LocalCrawlerRunner({
  pythonExecutable: config.pythonExecutable,
  outputDir: config.scraperOutputDir,
  store
});
const app = await buildApp({ store, adminApiKey: config.adminApiKey, crawlerRunner });

await app.listen({ port: config.port, host: config.host });
