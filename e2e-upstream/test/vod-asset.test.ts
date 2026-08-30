import { describe, it, expect } from 'vitest';
import { parseRange } from '../src/vod-asset.js';

describe('parseRange', () => {
  it('treats an absent or unparseable header as a full-body request', () => {
    // RFC 9110: a Range header a server does not understand is ignored, not
    // rejected. Dispatcharr never sends a multi-range request, and answering
    // 416 to one would be a fault this provider is not modelling.
    expect(parseRange(undefined, 100)).toEqual({ kind: 'full' });
    expect(parseRange('items=0-1', 100)).toEqual({ kind: 'full' });
    expect(parseRange('bytes=0-1,5-6', 100)).toEqual({ kind: 'full' });
    expect(parseRange('bytes=-', 100)).toEqual({ kind: 'full' });
  });

  it('parses a closed range', () => {
    expect(parseRange('bytes=10-19', 100)).toEqual({ kind: 'partial', start: 10, end: 19 });
  });

  it('parses an open-ended range', () => {
    expect(parseRange('bytes=90-', 100)).toEqual({ kind: 'partial', start: 90, end: 99 });
  });

  it('clamps an end past the last byte', () => {
    expect(parseRange('bytes=90-500', 100)).toEqual({ kind: 'partial', start: 90, end: 99 });
  });

  it('parses a suffix range', () => {
    expect(parseRange('bytes=-10', 100)).toEqual({ kind: 'partial', start: 90, end: 99 });
    expect(parseRange('bytes=-500', 100)).toEqual({ kind: 'partial', start: 0, end: 99 });
  });

  it('reports a start past the end, an inverted range and a zero suffix as unsatisfiable', () => {
    expect(parseRange('bytes=100-', 100)).toEqual({ kind: 'unsatisfiable' });
    expect(parseRange('bytes=50-10', 100)).toEqual({ kind: 'unsatisfiable' });
    expect(parseRange('bytes=-0', 100)).toEqual({ kind: 'unsatisfiable' });
  });
});
