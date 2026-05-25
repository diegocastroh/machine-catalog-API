import { describe, expect, it } from 'vitest';
import { MachineCatalogDeduplicator } from '../src/catalog/deduplicator.js';

describe('MachineCatalogDeduplicator', () => {
  const deduplicator = new MachineCatalogDeduplicator();

  it('detects exact manufacturer and normalized model matches', () => {
    const result = deduplicator.compare(
      { manufacturer_id: 'm1', normalized_model_name: 'opera-touch', source_url: 'https://maker.example/opera' },
      { manufacturer_id: 'm1', normalized_model_name: 'opera-touch', source_url: 'https://maker.example/opera' }
    );

    expect(result.is_duplicate).toBe(true);
    expect(result.match_type).toBe('exact_model');
    expect(result.score).toBeGreaterThanOrEqual(0.95);
  });

  it('detects fuzzy model matches for the same manufacturer', () => {
    const result = deduplicator.compare(
      { manufacturer_id: 'm1', normalized_model_name: 'opera-touch' },
      { manufacturer_id: 'm1', normalized_model_name: 'opera-touch-600' }
    );

    expect(result.is_duplicate).toBe(true);
    expect(result.match_type).toBe('fuzzy_model');
    expect(result.score).toBeGreaterThanOrEqual(0.7);
  });

  it('does not match different manufacturers with unrelated models', () => {
    const result = deduplicator.compare(
      { manufacturer_id: 'm1', normalized_model_name: 'coffee-master' },
      { manufacturer_id: 'm2', normalized_model_name: 'ice-locker' }
    );

    expect(result.is_duplicate).toBe(false);
    expect(result.score).toBeLessThan(0.7);
  });
});
