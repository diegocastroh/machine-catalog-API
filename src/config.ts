export type AppConfig = {
  port: number;
  host: string;
  supabaseUrl: string;
  supabaseServiceRoleKey: string;
  adminApiKey: string;
};

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const port = Number(env.PORT ?? 3000);

  return {
    port: Number.isFinite(port) ? port : 3000,
    host: env.HOST ?? '0.0.0.0',
    supabaseUrl: requireEnv(env, 'SUPABASE_URL'),
    supabaseServiceRoleKey: requireEnv(env, 'SUPABASE_SERVICE_ROLE_KEY'),
    adminApiKey: requireEnv(env, 'ADMIN_API_KEY')
  };
}

function requireEnv(env: NodeJS.ProcessEnv, name: string): string {
  const value = env[name];
  if (!value?.trim()) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}
