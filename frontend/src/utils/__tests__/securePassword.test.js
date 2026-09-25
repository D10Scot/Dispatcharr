import { describe, it, expect, vi, afterEach } from 'vitest';
import { generateSecurePassword } from '../securePassword';

describe('generateSecurePassword', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('used Math.random', () => {
    vi.spyOn(Math, 'random').mockImplementation(() => {
      throw new Error('Math.random called');
    });
    const cryptoSpy = vi.spyOn(globalThis.crypto, 'getRandomValues');

    expect(() => generateSecurePassword()).not.toThrow();
    expect(cryptoSpy).toHaveBeenCalled();
  });

  it('returns the requested length from the alphanumeric alphabet', () => {
    for (const length of [1, 20, 64]) {
      const password = generateSecurePassword(length);
      expect(password).toHaveLength(length);
      expect(password).toMatch(/^[A-Za-z0-9]+$/);
    }
  });

  it('rejects bytes that would bias the alphabet', () => {
    let call = 0;
    vi.spyOn(globalThis.crypto, 'getRandomValues').mockImplementation((buf) => {
      buf.fill(call === 0 ? 255 : 0);
      call += 1;
      return buf;
    });

    const password = generateSecurePassword(20);

    expect(password).toBe('A'.repeat(20));
  });
});
