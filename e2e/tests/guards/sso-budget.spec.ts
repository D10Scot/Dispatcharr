/**
 * The SSO projects' `oidc` throttle budget is declared, stated, counted and checked
 * (`tests/sso/budget.ts`; e2e/README.md, "The sso project").
 *
 * The run-time half lives in `tests/sso/fixtures.ts`: every browser request to a
 * throttled route goes into the project's ledger, and a test fails once the run has
 * spent more than its project declares. This file holds what makes that sound:
 *
 * - the declared budgets stay inside Mino's own rate (read from the product's settings module, `SETTINGS_MODULE`)
 *   less `OIDC_HEADROOM`, and the README and every spec header state the same numbers;
 * - every spec under `tests/sso/` takes `test` from `tests/sso/fixtures.ts`, so its
 *   browser is counted, and that file wires the ledger into `context`;
 * - no throttled route is written as a string under `tests/sso/`, so no request reaches
 *   one except through the browser the ledger watches;
 * - the path classifier counts exactly the four throttled routes.
 *
 * What it cannot see: a route assembled from fragments that are not themselves a route
 * (`'sta' + 'rt/'`), and a request made through a module outside `tests/sso/`.
 *
 * `@characterization`: the harness's own accounting, which no client observes
 * (`docs/adr/0002`).
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';
import * as ts from 'typescript';
import { E2E_ROOT, REPO_ROOT, listTsFiles, readSpec } from './ast';
import { readFile } from 'node:fs/promises';
import {
  OIDC_BUDGET,
  OIDC_HEADROOM,
  OIDC_THROTTLE_PER_MINUTE,
  isThrottledOidcPath,
} from '../sso/budget';

const SSO_DIR = 'tests/sso';
/** The product's settings module: a live path, which keeps the old product name until the rename reaches it. */
const SETTINGS_MODULE = 'dispatcharr/settings.py';
const FIXTURES_MODULE = path.join(E2E_ROOT, SSO_DIR, 'fixtures');

function parse(rel: string, src: string): ts.SourceFile {
  return ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true);
}

function lineOf(sf: ts.SourceFile, node: ts.Node): number {
  return sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
}

/** The project a spec under `tests/sso/` belongs to (`playwright.config.ts`'s testDir/testIgnore). */
function projectOf(rel: string): keyof typeof OIDC_BUDGET {
  return rel.startsWith(`${SSO_DIR}/faults/`) ? 'sso-faults' : 'sso';
}

async function specFiles(): Promise<string[]> {
  return (await listTsFiles(path.join(E2E_ROOT, SSO_DIR), SSO_DIR)).filter((rel) => rel.endsWith('.spec.ts'));
}

test.describe('the SSO oidc budget', () => {
  test('stays inside Mino’s own rate, less the headroom', { tag: '@characterization' }, async () => {
    const settings = await readFile(path.join(REPO_ROOT, SETTINGS_MODULE), 'utf8');
    const rate = /["']oidc["']\s*:\s*["'](\d+)\/minute["']/.exec(settings);
    expect(rate?.[1], `${SETTINGS_MODULE} names the oidc rate per minute`).toBe(String(OIDC_THROTTLE_PER_MINUTE));
    expect(Object.keys(OIDC_BUDGET).sort()).toEqual(['sso', 'sso-faults']);
    for (const [project, budget] of Object.entries(OIDC_BUDGET)) {
      expect(
        budget,
        `${project}'s budget must leave ${OIDC_HEADROOM} of the ${OIDC_THROTTLE_PER_MINUTE} a minute unspent`
      ).toBeLessThanOrEqual(OIDC_THROTTLE_PER_MINUTE - OIDC_HEADROOM);
    }
  });

  test('is stated in the README and in every spec header', { tag: '@characterization' }, async () => {
    const readme = await readFile(path.join(E2E_ROOT, 'README.md'), 'utf8');
    const problems: string[] = [];
    for (const [project, budget] of Object.entries(OIDC_BUDGET)) {
      const line = `**The \`${project}\` project's SSO request budget: ${budget} of ${OIDC_THROTTLE_PER_MINUTE} a run.**`;
      if (!readme.includes(line)) problems.push(`e2e/README.md does not say ${line}`);
    }
    for (const rel of await specFiles()) {
      const expected = `The project spends ${OIDC_BUDGET[projectOf(rel)]} a run`;
      if (!(await readSpec(rel)).includes(expected)) problems.push(`${rel}: its header does not say "${expected}"`);
    }
    expect(problems, 'OIDC_BUDGET in tests/sso/budget.ts, the README and the spec headers disagree').toEqual([]);
  });

  test('counts every throttled request: browser only, through the counting fixture', { tag: '@characterization' }, async () => {
    const problems: string[] = [];
    for (const rel of await listTsFiles(path.join(E2E_ROOT, SSO_DIR), SSO_DIR)) {
      const sf = parse(rel, await readSpec(rel));

      if (rel.endsWith('.spec.ts')) {
        const fromFixtures = sf.statements.some(
          (s) =>
            ts.isImportDeclaration(s) &&
            ts.isStringLiteral(s.moduleSpecifier) &&
            path.resolve(E2E_ROOT, path.dirname(rel), s.moduleSpecifier.text) === FIXTURES_MODULE &&
            !!s.importClause?.namedBindings &&
            ts.isNamedImports(s.importClause.namedBindings) &&
            s.importClause.namedBindings.elements.some((el) => !el.propertyName && el.name.text === 'test')
        );
        if (!fromFixtures) problems.push(`${rel}: does not import test from tests/sso/fixtures.ts, so its browser is not counted`);
      }

      (function visit(node: ts.Node): void {
        let text: string | undefined;
        if (ts.isStringLiteralLike(node)) text = node.text;
        else if (ts.isTemplateExpression(node)) {
          text = node.head.text + node.templateSpans.map((s) => `x${s.literal.text}`).join('');
        }
        if (text !== undefined) {
          const at = text.indexOf('/api/accounts/oidc/');
          const route = at >= 0 ? text.slice(at).split(/[?#]/)[0] : undefined;
          if (route && isThrottledOidcPath(route)) {
            problems.push(`${rel}: names the throttled route ${route} (line ${lineOf(sf, node)}), outside the browser the ledger counts`);
          }
          if (ts.isTemplateExpression(node)) return;
        }
        ts.forEachChild(node, visit);
      })(sf);
    }

    const fixtures = await readSpec(`${SSO_DIR}/fixtures.ts`);
    if (!/context:\s*async[\s\S]*new OidcLedger\([\s\S]*\.assertWithinBudget\(\)/.test(fixtures)) {
      problems.push('tests/sso/fixtures.ts: its context fixture does not record into an OidcLedger and assert the budget');
    }
    expect(problems, 'an oidc request the budget ledger would not count').toEqual([]);
  });

  test('classifies exactly the four throttled routes', { tag: '@characterization' }, () => {
    for (const p of [
      '/api/accounts/oidc/e2e-x-1/start/',
      '/api/accounts/oidc/e2e-x-1/link/start/',
      '/api/accounts/oidc/e2e-x-1/callback/',
      '/api/accounts/oidc/exchange/',
    ]) {
      expect(isThrottledOidcPath(p), p).toBe(true);
    }
    for (const p of [
      '/api/accounts/oidc/providers/',
      '/api/accounts/oidc/settings/',
      '/api/accounts/oidc/providers-admin/',
      '/api/accounts/oidc/providers-admin/3/',
      '/api/accounts/oidc/identities/',
      '/api/accounts/token/',
      '/login/sso',
      '/oidc/authorize',
    ]) {
      expect(isThrottledOidcPath(p), p).toBe(false);
    }
  });
});
