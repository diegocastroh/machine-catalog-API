import { MachineCatalogNormalizer } from './normalizer.js';

type ExtractionInput = {
  manufacturer_name?: string | null;
  brand_name?: string | null;
  model_name?: string | null;
  category_code?: string | null;
  description?: string | null;
  specs?: Record<string, unknown>;
  images?: Array<Record<string, unknown>>;
  documents?: Array<Record<string, unknown>>;
  confidence_score?: number;
};

export type ApprovalInput = {
  rawExtractionId: string;
  sourcePageId: string;
  reviewedBy?: string;
  extraction: ExtractionInput;
  edits?: Partial<ExtractionInput>;
};

export class MachineCatalogReviewService {
  private readonly normalizer = new MachineCatalogNormalizer();

  buildApproval(input: ApprovalInput): Record<string, any> {
    const extraction = { ...input.extraction, ...input.edits };
    const modelName = extraction.model_name?.trim();
    if (!modelName) {
      throw new Error('model_name is required to approve an extraction');
    }

    const description = extraction.description ?? '';
    const dimensions = this.normalizer.extractDimensions(`${description} ${JSON.stringify(extraction.specs ?? {})}`);
    const text = `${modelName} ${description} ${JSON.stringify(extraction.specs ?? {})}`;

    return {
      manufacturer: {
        name: extraction.manufacturer_name?.trim() || 'Unknown manufacturer',
        slug: this.normalizer.slugify(extraction.manufacturer_name?.trim() || 'unknown-manufacturer'),
        status: 'pending_review',
        source_confidence: extraction.confidence_score ?? 0
      },
      model: {
        model_name: this.normalizer.cleanModelName(modelName),
        model_slug: this.normalizer.slugify(modelName),
        normalized_model_name: this.normalizer.slugify(modelName),
        category_code: extraction.category_code ?? this.normalizer.detectCategory(text),
        short_description: description || null,
        source_url: null,
        confidence_score: extraction.confidence_score ?? 0,
        status: 'pending_review',
        lifecycle_status: 'unknown'
      },
      specs: {
        ...dimensions,
        refrigerated: /refrigerated|cold/i.test(text),
        freezer: /freezer|frozen/i.test(text),
        heated: /heated|hot/i.test(text),
        touchscreen: /touchscreen|touch screen/i.test(text),
        payment_protocols: this.normalizer.detectPaymentProtocols(text),
        connectivity: this.normalizer.detectConnectivity(text),
        raw_specs: extraction.specs ?? {}
      },
      images: extraction.images ?? [],
      documents: extraction.documents ?? [],
      review: {
        entity_type: 'extraction',
        entity_id: input.rawExtractionId,
        review_action: 'approved',
        reviewed_by: input.reviewedBy ?? null,
        notes: null
      },
      history: {
        entity_type: 'extraction',
        entity_id: input.rawExtractionId,
        change_type: 'approved',
        before: { raw_extraction_id: input.rawExtractionId, source_page_id: input.sourcePageId },
        after: extraction,
        changed_by: input.reviewedBy ?? null
      }
    };
  }

  buildRejection(input: {
    entityType: 'manufacturer' | 'model' | 'image' | 'document' | 'extraction';
    entityId: string;
    reviewedBy?: string;
    notes?: string;
  }): Record<string, unknown> {
    return {
      entity_type: input.entityType,
      entity_id: input.entityId,
      review_action: 'rejected',
      notes: input.notes ?? null,
      reviewed_by: input.reviewedBy ?? null
    };
  }
}
