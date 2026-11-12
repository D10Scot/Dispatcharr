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
 * Every fence on the page is `bash` (commands) or `text` (output and the form
 * template); any other fence, a bare one included, fails, so a command cannot
 * hide in an `sh` block. A line starting `docker exec` in any fence, and an
 * inline code span starting `docker exec `, must be the login-shell form.
 *
 * No container and no browser: this reads a file.
 *
 * Verified by mutation: rewriting the page's first command as
 * `docker exec <container> python manage.py password_login --enable` failed,
 * quoting the line (`not run through the login shell (su - dispatch -c '…')`);
 * so did moving a bare command into a fenced `sh` block, and into an inline
 * code span.
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
/** The form template the page shows once, in a `text` fence. */
const LOGIN_SHELL_TEMPLATE = new RegExp(
  `^docker exec \\[-it\\] <container> su - ${APP_USER} -c '(.+)'$`,
);
const FENCE_LANGUAGES = ["bash", "text"];
const INNER_PREFIX = "cd /app && python manage.py ";

interface Fenced {
  language: string;
  line: string;
}

/** The page split into fenced lines (with their fence's language), the
 * languages of every opening fence, and the prose outside the fences. */
function parse(markdown: string): {
  fenced: Fenced[];
  languages: string[];
  prose: string[];
} {
  const fenced: Fenced[] = [];
  const languages: string[] = [];
  const prose: string[] = [];
  let language: string | null = null;
  for (const raw of markdown.split("\n")) {
    const fence = raw.trim().match(/^```(.*)$/);
    if (fence) {
      if (language === null) {
        language = fence[1].trim();
        languages.push(language);
      } else {
        language = null;
      }
      continue;
    }
    if (language === null) prose.push(raw);
    else fenced.push({ language, line: raw.trim() });
  }
  return { fenced, languages, prose };
}

/** The inline code spans in prose. */
function inlineSpans(prose: string[]): string[] {
  return prose.flatMap((line) =>
    [...line.matchAll(/`([^`]+)`/g)].map((m) => m[1].trim()),
  );
}

function bashLines(markdown: string): string[] {
  return parse(markdown)
    .fenced.filter((f) => f.language === "bash")
    .map((f) => f.line);
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

// @characterization: as above, a fact about a file in this repository.
test(
  "no command hides outside a bash fence or in another fence language",
  { tag: "@characterization" },
  async () => {
    const { fenced, languages, prose } = parse(readFileSync(DOC, "utf8"));
    for (const language of languages) {
      expect(
        FENCE_LANGUAGES,
        `a fence that is neither bash nor text: \`\`\`${language}`,
      ).toContain(language);
    }
    for (const { language, line } of fenced) {
      if (!line.startsWith(DOCKER_EXEC)) continue;
      const ok =
        LOGIN_SHELL.test(line) ||
        (language === "text" && LOGIN_SHELL_TEMPLATE.test(line));
      expect(
        ok,
        `not run through the login shell (su - ${APP_USER} -c '…'), in a ${language} fence: ${line}`,
      ).toBe(true);
    }
    for (const span of inlineSpans(prose)) {
      if (!span.startsWith(`${DOCKER_EXEC} `)) continue;
      expect(
        LOGIN_SHELL.test(span),
        `not run through the login shell (su - ${APP_USER} -c '…'), in an inline code span: ${span}`,
      ).toBe(true);
    }
  },
);
