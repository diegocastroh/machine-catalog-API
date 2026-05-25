export type DuplicateComparable = {
  manufacturer_id?: string | null;
  normalized_model_name?: string | null;
  model_name?: string | null;
  source_url?: string | null;
  official_product_url?: string | null;
  hash_sha256?: string | null;
};

export type DuplicateResult = {
  is_duplicate: boolean;
  score: number;
  match_type: 'exact_model' | 'same_source' | 'same_hash' | 'fuzzy_model' | 'none';
  reasons: string[];
};

export class MachineCatalogDeduplicator {
  compare(left: DuplicateComparable, right: DuplicateComparable): DuplicateResult {
    const reasons: string[] = [];
    const leftModel = this.normalizedName(left);
    const rightModel = this.normalizedName(right);
    const sameManufacturer = Boolean(left.manufacturer_id && left.manufacturer_id === right.manufacturer_id);

    if (sameManufacturer && leftModel && leftModel === rightModel) {
      return { is_duplicate: true, score: 0.95, match_type: 'exact_model', reasons: ['same_manufacturer', 'same_normalized_model'] };
    }

    if (left.hash_sha256 && left.hash_sha256 === right.hash_sha256) {
      return { is_duplicate: true, score: 0.98, match_type: 'same_hash', reasons: ['same_hash'] };
    }

    if (this.sameUrl(left.source_url, right.source_url) || this.sameUrl(left.official_product_url, right.official_product_url)) {
      return { is_duplicate: true, score: 0.96, match_type: 'same_source', reasons: ['same_source_url'] };
    }

    const similarity = this.similarity(leftModel, rightModel);
    if (sameManufacturer) reasons.push('same_manufacturer');
    if (similarity >= 0.72) reasons.push('similar_model_name');

    const score = Math.round(((sameManufacturer ? 0.35 : 0) + similarity * 0.65) * 100) / 100;
    return {
      is_duplicate: sameManufacturer && score >= 0.7,
      score,
      match_type: sameManufacturer && score >= 0.7 ? 'fuzzy_model' : 'none',
      reasons
    };
  }

  private normalizedName(value: DuplicateComparable): string {
    return (value.normalized_model_name ?? value.model_name ?? '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  private sameUrl(left?: string | null, right?: string | null): boolean {
    return Boolean(left && right && left.replace(/\/$/, '') === right.replace(/\/$/, ''));
  }

  private similarity(left: string, right: string): number {
    if (!left || !right) return 0;
    if (left === right) return 1;
    const leftTokens = new Set(left.split('-').filter(Boolean));
    const rightTokens = new Set(right.split('-').filter(Boolean));
    const intersection = [...leftTokens].filter((token) => rightTokens.has(token)).length;
    const union = new Set([...leftTokens, ...rightTokens]).size || 1;
    return intersection / union;
  }
}
