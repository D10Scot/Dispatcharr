import { describe, it, expect } from 'vitest';
import {
  hlsOutputProfiles,
  isHlsOutputProfile,
  selectableOutputProfiles,
} from '../outputProfiles';

const PROFILES = [
  { id: 1, name: 'AC3', is_active: true, hls_mode: '' },
  { id: 2, name: 'Old', is_active: false, hls_mode: '' },
  { id: 3, name: 'HLS (Re-encode)', is_active: true, hls_mode: 'transcode' },
  { id: 4, name: 'HLS (Automatic)', is_active: false, hls_mode: 'automatic' },
];

describe('outputProfiles', () => {
  it('recognises an HLS profile by a non-blank hls_mode', () => {
    expect(isHlsOutputProfile(PROFILES[0])).toBe(false);
    expect(isHlsOutputProfile({ id: 9 })).toBe(false);
    expect(isHlsOutputProfile(undefined)).toBe(false);
    expect(isHlsOutputProfile(PROFILES[2])).toBe(true);
    expect(isHlsOutputProfile(PROFILES[3])).toBe(true);
  });

  it('selectableOutputProfiles drops every HLS row and keeps the rest', () => {
    expect(selectableOutputProfiles(PROFILES).map((p) => p.id)).toEqual([1, 2]);
    expect(selectableOutputProfiles(undefined)).toEqual([]);
  });

  it('hlsOutputProfiles keeps only the active HLS rows', () => {
    expect(hlsOutputProfiles(PROFILES).map((p) => p.id)).toEqual([3]);
    expect(hlsOutputProfiles(null)).toEqual([]);
  });
});
