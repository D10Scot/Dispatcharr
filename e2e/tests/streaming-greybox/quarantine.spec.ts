import { test, expect } from '@playwright/test';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { GREYBOX_ALLOWLIST } from '../../fixtures/greybox/redis';

// This file's own path relative to `e2e/`, plus the fixture it wraps. Both
// are excluded from the scan below: the fixture legitimately doesn't import
// itself, and this file's own source text necessarily contains the string
// "greybox/redis" (its import of GREYBOX_ALLOWLIST, and the string literals
// in the walk logic itself) without being an unauthorized *consumer* of the
// helper — it never imports `greyboxRedis`, only the allowlist it enforces.
const FIXTURE_PATH = 'fixtures/greybox/redis.ts';
const SELF_PATH = 'tests/streaming-greybox/quarantine.spec.ts';

test('only allowlisted specs import the grey-box Redis helper', async () => {
  const root = path.resolve(__dirname, '../..');
  const importers: string[] = [];

  async function walk(dir: string, rel: string): Promise<void> {
    for (const entry of await readdir(path.join(root, dir), { withFileTypes: true })) {
      if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
      const childRel = rel ? `${rel}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        await walk(path.join(dir, entry.name), childRel);
      } else if (
        entry.name.endsWith('.ts') &&
        childRel !== FIXTURE_PATH &&
        childRel !== SELF_PATH
      ) {
        const src = await readFile(path.join(root, dir, entry.name), 'utf8');
        if (src.includes('greybox/redis')) importers.push(childRel);
      }
    }
  }
  await walk('', '');

  // A convention plus a README decays silently. This does not.
  expect(importers.sort()).toEqual([...GREYBOX_ALLOWLIST].sort());
});
