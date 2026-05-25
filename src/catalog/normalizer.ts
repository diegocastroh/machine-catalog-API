import { categoryKeywords } from './taxonomy.js';

export type ConfidenceInput = {
  officialSource?: boolean;
  structuredProductPage?: boolean;
  modelDetected?: boolean;
  manufacturerMatchesSource?: boolean;
  categoryDetected?: boolean;
  officialImageDetected?: boolean;
  documentDetected?: boolean;
  technicalSpecsDetected?: boolean;
  unofficialUnconfirmedSource?: boolean;
  contradictoryData?: boolean;
};

export class MachineCatalogNormalizer {
  cleanModelName(value: string): string {
    return value.replace(/\s+/g, ' ').replace(/[™®]/g, '').trim();
  }

  slugify(value: string): string {
    return this.cleanModelName(value)
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  detectCategory(text: string): string {
    const normalized = text.toLowerCase();
    for (const [category, keywords] of Object.entries(categoryKeywords)) {
      if (keywords.some((keyword) => normalized.includes(keyword))) {
        return category;
      }
    }
    return 'other';
  }

  extractDimensions(text: string): { height_mm?: number; width_mm?: number; depth_mm?: number } {
    const normalized = text.toLowerCase().replace(/,/g, '.');
    const match = normalized.match(/(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(mm|cm|in|inch|inches)?/);
    if (!match) {
      return {};
    }

    const unit = match[4] ?? 'mm';
    const values = [Number(match[1]), Number(match[2]), Number(match[3])].map((value) => this.toMillimeters(value, unit));
    return {
      height_mm: values[0],
      width_mm: values[1],
      depth_mm: values[2]
    };
  }

  toMillimeters(value: number, unit: string): number {
    if (unit === 'cm') {
      return Math.round(value * 10);
    }
    if (unit === 'in' || unit === 'inch' || unit === 'inches') {
      return Math.round(value * 25.4);
    }
    return Math.round(value);
  }

  toKilograms(value: number, unit: string): number {
    if (unit.toLowerCase() === 'lb' || unit.toLowerCase() === 'lbs' || unit.toLowerCase() === 'pound') {
      return Math.round(value * 0.453592 * 100) / 100;
    }
    return value;
  }

  detectPaymentProtocols(text: string): string[] {
    return this.detectTerms(text, ['MDB', 'EVA-DTS', 'cashless', 'Nayax', 'telemetry']);
  }

  detectConnectivity(text: string): string[] {
    return this.detectTerms(text, ['WiFi', 'Ethernet', '4G', 'Bluetooth']);
  }

  calculateConfidence(input: ConfidenceInput): number {
    let score = 0;
    if (input.officialSource) score += 30;
    if (input.structuredProductPage) score += 15;
    if (input.modelDetected) score += 15;
    if (input.manufacturerMatchesSource) score += 10;
    if (input.categoryDetected) score += 10;
    if (input.officialImageDetected) score += 10;
    if (input.documentDetected) score += 10;
    if (input.technicalSpecsDetected) score += 10;
    if (input.unofficialUnconfirmedSource) score -= 20;
    if (input.contradictoryData) score -= 20;
    if (!input.modelDetected) score -= 30;
    return Math.max(0, Math.min(1, score / 100));
  }

  validateExternalHttpUrl(value: string): URL {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) {
      throw new Error('Only HTTP/HTTPS URLs are allowed');
    }
    const host = url.hostname.toLowerCase();
    if (
      host === 'localhost' ||
      host === 'metadata.google.internal' ||
      host.startsWith('127.') ||
      host.startsWith('169.254.') ||
      host.startsWith('10.') ||
      host.startsWith('192.168.') ||
      /^172\.(1[6-9]|2\d|3[0-1])\./.test(host) ||
      host === '::1'
    ) {
      throw new Error('Private, localhost and metadata URLs are blocked');
    }
    return url;
  }

  private detectTerms(text: string, terms: string[]): string[] {
    const normalized = text.toLowerCase();
    return terms.filter((term) => normalized.includes(term.toLowerCase()));
  }
}
