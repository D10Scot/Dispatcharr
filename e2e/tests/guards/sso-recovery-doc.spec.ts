/**
 * `docs/sso-recovery.md` documents only commands that run (SSO spec 5.6).
 *
 * Every documented command must go through a login shell:
 * `docker exec [-it ]<container> su - dispatch -c 'cd /app && python manage.py …'`.
 * A plain `docker exec <container> python manage.py …` cannot read the
 * server's secret key (PID 1's exports do not reach a `docker exec` process),
 * so a page that shows one fails the operator at the worst moment.
 *
 * For the token-only commands the page must say exactly what
 * `fixtures/manage-command.ts` builds, which is the line `instance.manage()`
 * runs, so the page and the fixture cannot drift apart. The interactive and
 * quoted commands (`changepassword`, the deactivation one-liner) cannot run
 * through `instance.manage()`; for them the shape is the whole check.
 *
 * No container and no browser: this reads a file.
 *
 * Verified by mutation: rewriting the page's first command as
 * `docker exec <container> python manage.py password_login --enable` failed,
 * quoting the line (`not run through the login shell (su - dispatch -c '…')`).
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

import { APP_USER, manageInner } from "../../fixtures/manage-command";

const DOC = path.resolve(process.cwd(), "..", "docs", "sso-recovery.md");

/** The token-only commands the page must carry, as `instance.manage()` argv. */
const TOKEN_ONLY: readonly (readonly string[])[] = [
  ["password_login", "--enable"],
  ["password_login", "--status"],
  ["createsuperuser"],
];

const LOGIN_SHELL = new RegExp(
  `^docker exec (?:-it )?<container> su - ${APP_USER} -c '(.+)'$`,
);
const INNER_PREFIX = "cd /app && python manage.py ";

/** Every line of a fenced `bash` block. */
function bashLines(markdown: string): string[] {
  const lines: string[] = [];
  let inBash = false;
  for (const line of markdown.split("\n")) {
    const fence = line.trim().match(/^```(\w*)/);
    if (fence) {
      inBash = !inBash && fence[1] === "bash";
      continue;
    }
    if (inBash) lines.push(line.trim());
  }
  return lines;
}

const DOCKER_EXEC = "docker exec";

// @characterization: this asserts a fact about a file in this repository (an
// operator page), in the idiom of the other guards; nothing here reaches a
// running instance.
test(
  "every documented command runs through the login shell",
  { tag: "@characterization" },
  async () => {
    const lines = bashLines(readFileSync(DOC, "utf8")).filter(
      (l) => l.length > 0,
    );
    expect(lines.length, "the page has no bash block").toBeGreaterThan(0);

    const inners: string[] = [];
    for (const line of lines) {
      expect(
        line.startsWith(DOCKER_EXEC),
        `a bash line that is not a docker exec command: ${line}`,
      ).toBe(true);
      const match = line.match(LOGIN_SHELL);
      expect(
        match,
        `not run through the login shell (su - ${APP_USER} -c '…'): ${line}`,
      ).not.toBeNull();
      const inner = match![1];
      expect(
        inner.startsWith(INNER_PREFIX),
        `the login shell does not run "${INNER_PREFIX}…": ${line}`,
      ).toBe(true);
      inners.push(inner);
    }

    for (const argv of TOKEN_ONLY) {
      expect(
        inners,
        `the page must carry \`${argv.join(" ")}\` exactly as instance.manage() runs it`,
      ).toContain(manageInner([...argv]));
    }
  },
);
