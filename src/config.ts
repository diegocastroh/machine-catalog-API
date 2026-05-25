export type AppConfig = {
  port: number;
  host: string;
  supabaseUrl: string;
  supabaseServiceRoleKey: string;
  adminApiKey: string;
  pythonExecutable: string;
  scraperOutputDir: string;
};

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const port = Number(env.PORT ?? 3000);
  const supabaseUrl = requireEnv(env, 'SUPABASE_URL');
  if (!supabaseUrl.startsWith('https://') || !supabaseUrl.includes('.supabase.co')) {
    throw new Error('SUPABASE_URL must be the project URL, for example https://yptzopnarugsoighqnph.supabase.co');
  }

  return {
    port: Number.isFinite(port) ? port : 3000,
    host: env.HOST ?? '0.0.0.0',
    supabaseUrl,
    supabaseServiceRoleKey: requireEnv(env, 'SUPABASE_SERVICE_ROLE_KEY'),
    adminApiKey: requireEnv(env, 'ADMIN_API_KEY'),
    pythonExecutable: env.PYTHON_EXECUTABLE ?? 'python',
    scraperOutputDir: env.SCRAPER_OUTPUT_DIR ?? '.scraper-output'
  };
}

function requireEnv(env: NodeJS.ProcessEnv, name: string): string {
  const value = env[name];
  if (!value?.trim()) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}
