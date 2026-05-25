import { describe, expect, it } from 'vitest';
import { MachineCatalogNormalizer } from '../src/catalog/normalizer.js';

describe('MachineCatalogNormalizer', () => {
  const normalizer = new MachineCatalogNormalizer();

  it('detects categories from vending keywords', () => {
    expect(normalizer.detectCategory('Bean-to-cup espresso coffee machine')).toBe('coffee');
    expect(normalizer.detectCategory('Frozen ice cream vending freezer')).toBe('ice_cream');
    expect(normalizer.detectCategory('PPE industrial inventory control locker')).toBe('smart_locker');
  });

  it('extracts dimensions and converts units to millimeters', () => {
    expect(normalizer.extractDimensions('Dimensions 183 x 90 x 79 cm')).toEqual({
      height_mm: 1830,
      width_mm: 900,
      depth_mm: 790
    });
    expect(normalizer.extractDimensions('Size 72 x 35 x 31 in')).toEqual({
      height_mm: 1829,
      width_mm: 889,
      depth_mm: 787
    });
  });

  it('calculates confidence with positive and negative evidence', () => {
    expect(
      normalizer.calculateConfidence({
        officialSource: true,
        structuredProductPage: true,
        modelDetected: true,
        manufacturerMatchesSource: true,
        categoryDetected: true,
        officialImageDetected: true,
        documentDetected: true,
        technicalSpecsDetected: true
      })
    ).toBe(1);

    expect(normalizer.calculateConfidence({ officialSource: true, contradictoryData: true, modelDetected: false })).toBe(0);
  });

  it('blocks SSRF-prone URLs', () => {
    expect(() => normalizer.validateExternalHttpUrl('http://localhost/admin')).toThrow();
    expect(() => normalizer.validateExternalHttpUrl('http://169.254.169.254/latest/meta-data')).toThrow();
    expect(() => normalizer.validateExternalHttpUrl('https://example.com/product')).not.toThrow();
    expect(() => normalizer.validateExternalHttpUrl('file:///etc/passwd')).toThrow();
  });
});
