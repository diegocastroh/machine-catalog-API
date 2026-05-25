import { randomUUID } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { MachineCatalogReviewService } from '../src/catalog/review-service.js';

describe('MachineCatalogReviewService', () => {
  it('converts an approved normalized extraction into a curated catalog payload', () => {
    const service = new MachineCatalogReviewService();
    const rawExtractionId = randomUUID();
    const sourcePageId = randomUUID();
    const reviewedBy = randomUUID();

    const result = service.buildApproval({
      rawExtractionId,
      sourcePageId,
      reviewedBy,
      extraction: {
        manufacturer_name: 'Evoca Group / Necta',
        model_name: 'Opera Touch',
        category_code: 'snack_drink',
        description: 'Snack and cold drink vending machine with MDB cashless support.',
        specs: { dimensions: '183 x 90 x 79 cm', refrigerated: true },
        images: [{ source_image_url: 'https://example.com/opera.jpg', is_official: true }],
        documents: [{ source_url: 'https://example.com/opera.pdf', document_type: 'brochure' }],
        confidence_score: 0.88
      }
    });

    expect(result.manufacturer.name).toBe('Evoca Group / Necta');
    expect(result.model.model_name).toBe('Opera Touch');
    expect(result.model.status).toBe('pending_review');
    expect(result.model.category_code).toBe('snack_drink');
    expect(result.specs.height_mm).toBe(1830);
    expect(result.review.review_action).toBe('approved');
    expect(result.history.change_type).toBe('approved');
  });

  it('records rejection with notes and reviewer', () => {
    const service = new MachineCatalogReviewService();
    const reviewedBy = randomUUID();
    const rejected = service.buildRejection({
      entityId: randomUUID(),
      entityType: 'extraction',
      reviewedBy,
      notes: 'Model name is ambiguous'
    });

    expect(rejected.review_action).toBe('rejected');
    expect(rejected.notes).toBe('Model name is ambiguous');
    expect(rejected.reviewed_by).toBe(reviewedBy);
  });
});
