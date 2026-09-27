import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { ASSET_NAMES } from '../src/asset.js';

/**
 * The door (`parseScenarioRequest`) accepts exactly `ASSET_NAMES`, and a
 * stream request loads `<name>.ts` from the image. Nothing at runtime can tell
 * whether the image actually has every one: a name missing from the
 * Dockerfile's build loop, or a variant `make-asset.sh` does not know, would
 * pass the door and 500 on the first stream. This reads both build files and
 * holds them to the list, in both directions.
 */
const root = new URL('..', import.meta.url);
const makeAsset = readFileSync(fileURLToPath(new URL('scripts/make-asset.sh', root)), 'utf8');
const dockerfile = readFileSync(fileURLToPath(new URL('Dockerfile', root)), 'utf8');

/** The case labels of make-asset.sh's `case "${VARIANT}" in`, `*` excluded. */
function makeAssetVariants(script: string): string[] {
  return [...script.matchAll(/^ {2}([a-z0-9][a-z0-9-]*)\)$/gm)].map((match) => match[1]);
}

/** The names the Dockerfile's `for name in … ; do` loop builds. */
function dockerfileBuilds(file: string): string[] {
  const match = /for name in ([^;]+); do/.exec(file);
  if (!match) throw new Error("e2e-upstream/Dockerfile has no 'for name in …; do' asset build loop");
  return match[1].trim().split(/\s+/);
}

const sorted = (names: readonly string[]) => [...names].sort();

/** The loop body, `./make-asset.sh "/build/assets/${name}.ts" "${name}" || exit 1; \`, then `done`. */
const GUARDED_LOOP_BODY =
  /do \\\n\s*\.\/make-asset\.sh "\/build\/assets\/\$\{name\}\.ts" "\$\{name\}" \|\| exit 1; \\\n\s*done/;

describe('asset names (Phase 4a-0)', () => {
  it('make-asset.sh builds a variant for every name in ASSET_NAMES, and no other', () => {
    expect(
      sorted(makeAssetVariants(makeAsset)),
      'scripts/make-asset.sh case labels vs src/asset.ts ASSET_NAMES',
    ).toEqual(sorted(ASSET_NAMES));
  });

  it('the Dockerfile fails the build when make-asset.sh fails for any name', () => {
    // `RUN` is `sh -c` with no `-e`, and a `for` loop's status is its last
    // command's: without `|| exit 1` a fixture that fails its shape check
    // prints the failure and the image builds anyway (measured), so the
    // CONTRACT.md guarantee that an image which exists has these shapes
    // rests on this one guard.
    expect(
      dockerfile,
      "the Dockerfile's asset loop must run make-asset.sh with '|| exit 1', or a failed shape check does not fail docker build",
    ).toMatch(GUARDED_LOOP_BODY);
  });

  it('the Dockerfile builds every name in ASSET_NAMES, and no other', () => {
    expect(
      sorted(dockerfileBuilds(dockerfile)),
      "Dockerfile's asset build loop vs src/asset.ts ASSET_NAMES",
    ).toEqual(sorted(ASSET_NAMES));
  });
});
