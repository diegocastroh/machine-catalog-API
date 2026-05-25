import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import type { CatalogStore } from './store.js';

export type CrawlerRunner = {
  run(jobId: string): Promise<Record<string, unknown>>;
};

export class LocalCrawlerRunner implements CrawlerRunner {
  constructor(
    private readonly options: {
      pythonExecutable: string;
      outputDir: string;
      store: CatalogStore;
    }
  ) {}

  async run(jobId: string): Promise<Record<string, unknown>> {
    const job = await this.options.store.getCrawlJob(jobId);
    if (!job) throw new Error('Crawl job not found');
    if (!job.source_config_id) throw new Error('Crawl job requires source_config_id');
    const sourceConfig = await this.options.store.getSourceConfig(job.source_config_id);
    if (!sourceConfig) throw new Error('Source config not found');

    await mkdir(this.options.outputDir, { recursive: true });
    const inputPath = path.join(this.options.outputDir, `${jobId}.input.json`);
    const outputPath = path.join(this.options.outputDir, `${jobId}.output.jsonl`);
    const config = {
      job_id: jobId,
      output_path: outputPath,
      manufacturer_id: sourceConfig.manufacturer_id,
      manufacturer: sourceConfig.manufacturer_name,
      base_url: sourceConfig.base_url,
      allowed_domains: sourceConfig.allowed_domains,
      crawl_strategy: sourceConfig.crawl_strategy,
      product_url_patterns: sourceConfig.product_url_patterns,
      exclude_patterns: sourceConfig.exclude_patterns,
      data_sources: sourceConfig.data_sources,
      image_selectors: sourceConfig.image_selectors,
      max_pages_per_run: job.max_pages ?? sourceConfig.max_pages_per_run,
      delay_seconds: sourceConfig.delay_seconds,
      dynamic_rendering: sourceConfig.dynamic_rendering
    };
    await writeFile(inputPath, JSON.stringify(config, null, 2), 'utf-8');
    await this.options.store.updateCrawlJob(jobId, { status: 'running', started_at: new Date().toISOString() });
    await this.options.store.addCrawlJobLog(jobId, 'info', 'crawler_started', { inputPath, outputPath });

    const result = await this.spawnWorker(inputPath);
    const output = await readFile(outputPath, 'utf-8').catch(() => '');
    let pagesProcessed = 0;
    let modelsDetected = 0;
    for (const line of output.split(/\r?\n/).filter(Boolean)) {
      const parsed = JSON.parse(line) as Record<string, any>;
      pagesProcessed += 1;
      if (parsed.normalized?.model_name) modelsDetected += 1;
      await this.options.store.persistCrawlerResult(jobId, parsed);
    }

    const status = result.exitCode === 0 ? (modelsDetected > 0 ? 'success' : 'partial_success') : 'failed';
    const updated = await this.options.store.updateCrawlJob(jobId, {
      status,
      finished_at: new Date().toISOString(),
      pages_processed: pagesProcessed,
      models_detected: modelsDetected,
      stats: { pages_processed: pagesProcessed, models_detected: modelsDetected, worker: result }
    });
    await this.options.store.addCrawlJobLog(jobId, status === 'failed' ? 'error' : 'info', 'crawler_finished', { status, ...result });
    return updated;
  }

  private async spawnWorker(inputPath: string): Promise<{ exitCode: number; stdout: string; stderr: string }> {
    return new Promise((resolve) => {
      const child = spawn(this.options.pythonExecutable, ['-m', 'machine_catalog_scraper.cli', inputPath], {
        cwd: path.resolve('workers/scraper'),
        env: { ...process.env, PYTHONPATH: path.resolve('workers/scraper') }
      });
      let stdout = '';
      let stderr = '';
      child.stdout.on('data', (chunk) => (stdout += chunk.toString()));
      child.stderr.on('data', (chunk) => (stderr += chunk.toString()));
      child.on('close', (code) => resolve({ exitCode: code ?? 1, stdout, stderr }));
    });
  }
}
