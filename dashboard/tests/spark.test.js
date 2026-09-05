import { describe, expect, it } from 'vitest';
import { paths } from '../lib/spark.js';

describe('spark paths', () => {
  it('draws a line and a closed area', () => {
    const { line, area } = paths([0, 5, 10], 200, 60);
    expect(line).toMatch(/^M0,60/);
    expect(line).toMatch(/L200,0$/);
    expect(area).toMatch(/Z$/);
    expect(area).toContain('L200,60');
  });
  it('breaks at nulls and handles flat series', () => {
    const { line } = paths([1, null, 1], 100, 10);
    expect(line.match(/M/g)).toHaveLength(2);
    const flat = paths([3, 3, 3], 100, 10);
    expect(flat.line).toContain('M0,5');
  });
  it('is empty for no data', () => {
    expect(paths([], 100, 10)).toEqual({ line: '', area: '' });
    expect(paths([null, null], 100, 10)).toEqual({ line: '', area: '' });
  });
});
