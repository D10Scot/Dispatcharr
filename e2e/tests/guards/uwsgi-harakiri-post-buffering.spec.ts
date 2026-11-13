/**
 * No uWSGI ini under `docker/` sets both `harakiri` and `post-buffering`, no
 * supervisord program passes `--post-buffering` to uWSGI, and every ini that
 * sets `harakiri` reads request bodies in Python instead.
 *
 * uWSGI 2.0.31 keeps ONE harakiri deadline per worker, shared by every gevent
 * core on it: accept writes `now + harakiri` (`plugins/gevent/gevent.c:242-245`)
 * and every request close writes `0` (`core/utils.c:1119-1122`). Reading a
 * request body under `post-buffering` calls `inc_harakiri()`, which ADDS the
 * interval to whatever is there (`core/utils.c:45-52`, from
 * `core/reader.c:485-487` and `:558-561`). When a neighbouring request on the
 * same worker closed while the body-bearing request waited, the deadline is 0
 * and becomes `0 + harakiri`, a 1970 timestamp, and the master SIGKILLs the
 * whole worker and every request on it within a second. The two directives
 * together are the defect, whatever either value is.
 *
 * Dropping `post-buffering` alone turns an early 4xx on a large unread body
 * into a connection reset, so every ini with `harakiri` sets
 * `env = MINO_WSGI_SPOOL_REQUEST_BODY=1`, which turns on
 * `core/request_body_spool.py`. This guard asserts that line too, so the
 * variable cannot be dropped while the comment above it survives.
 *
 * Not seen: the Debian installer's generated ini (a heredoc in a shell
 * script) and anything passed at run time through the extra-arguments
 * variable the supervisord programs append.
 *
 * No container and no browser: this reads files.
 *
 * Verified by mutation: re-adding `post-buffering = 4096` to
 * `docker/uwsgi.ini` failed the first test naming the file and both line
 * numbers; deleting the `env =` line from `docker/uwsgi.modular.ini` failed
 * the second; appending `--post-buffering 4096` to the API program's command
 * failed the third.
 */
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

const DOCKER = path.resolve(process.cwd(), "..", "docker");
const SUPERVISORD = path.join(DOCKER, "supervisord.d");
/** The inis known to set harakiri; the guard refuses to pass if it finds none of them. */
const HARAKIRI_INIS = ["uwsgi.debug.ini", "uwsgi.ini", "uwsgi.modular.ini"];
const SPOOL_ENV = "env = MINO_WSGI_SPOOL_REQUEST_BODY=1";

interface Directive {
  key: string;
  value: string;
  line: number;
}

/** Every `key = value` line of an ini, skipping comments and section heads.
 * uWSGI treats `#` and `;` as comment leaders. */
function directives(text: string): Directive[] {
  const out: Directive[] = [];
  text.split("\n").forEach((raw, index) => {
    const line = raw.trim();
    if (!line || line.startsWith("#") || line.startsWith(";")) return;
    const match = line.match(/^([A-Za-z0-9_-]+)\s*=\s*(.*)$/);
    if (match) out.push({ key: match[1], value: match[2], line: index + 1 });
  });
  return out;
}

function uwsgiInis(): Map<string, Directive[]> {
  const inis = new Map<string, Directive[]>();
  for (const name of readdirSync(DOCKER).sort()) {
    if (/^uwsgi.*\.ini$/.test(name)) {
      inis.set(name, directives(readFileSync(path.join(DOCKER, name), "utf8")));
    }
  }
  return inis;
}

test(
  "no uWSGI ini combines harakiri with post-buffering",
  { tag: "@contract" },
  () => {
    const inis = uwsgiInis();
    expect([...inis.keys()], "found no docker/uwsgi*.ini to check").toEqual(
      expect.arrayContaining(HARAKIRI_INIS),
    );
    const offenders: string[] = [];
    for (const [name, found] of inis) {
      const harakiri = found.filter((d) => d.key === "harakiri");
      const buffering = found.filter((d) => d.key === "post-buffering");
      if (harakiri.length && buffering.length) {
        offenders.push(
          `docker/${name}: harakiri (line ${harakiri.map((d) => d.line).join(", ")}) ` +
            `with post-buffering (line ${buffering.map((d) => d.line).join(", ")})`,
        );
      }
    }
    expect(
      offenders,
      "post-buffering's inc_harakiri() adds to a per-worker deadline a " +
        "neighbouring request's close has zeroed, so uWSGI 2.0.31 SIGKILLs the " +
        "whole worker within a second; spool bodies in Python instead " +
        "(core/request_body_spool.py)",
    ).toEqual([]);
  },
);

test(
  "every uWSGI ini that sets harakiri turns on the Python request-body spool",
  { tag: "@contract" },
  () => {
    const withHarakiri = [...uwsgiInis()].filter(([, found]) =>
      found.some((d) => d.key === "harakiri"),
    );
    expect(
      withHarakiri.map(([name]) => name),
      "the inis that set harakiri changed; update HARAKIRI_INIS deliberately",
    ).toEqual(HARAKIRI_INIS);
    const missing = withHarakiri
      .filter(
        ([, found]) =>
          !found.some(
            (d) => `${d.key} = ${d.value.replace(/\s+[#;].*$/, "")}` === SPOOL_ENV,
          ),
      )
      .map(([name]) => `docker/${name}`);
    expect(
      missing,
      `each ini with harakiri must carry \`${SPOOL_ENV}\`: without post-buffering, ` +
        "a view that answers before reading a large body leaves it on the " +
        "socket and the client gets a reset instead of the 4xx",
    ).toEqual([]);
  },
);

test(
  "no supervisord program passes --post-buffering to uWSGI",
  { tag: "@contract" },
  () => {
    const confs = readdirSync(SUPERVISORD)
      .filter((name) => name.endsWith(".conf"))
      .sort();
    const uwsgiCommands = confs.flatMap((name) =>
      readFileSync(path.join(SUPERVISORD, name), "utf8")
        .split("\n")
        .map((line, index) => ({ name, line, number: index + 1 }))
        .filter(({ line }) => /^command\s*=.*\/uwsgi\s/.test(line)),
    );
    expect(
      uwsgiCommands.length,
      "found no supervisord program that runs uWSGI; the guard would pass vacuously",
    ).toBeGreaterThanOrEqual(2);
    const offenders = uwsgiCommands
      .filter(({ line }) => /--post[-_]buffering\b/.test(line))
      .map(({ name, number }) => `docker/supervisord.d/${name}:${number}`);
    expect(
      offenders,
      "--post-buffering on the command line brings back inc_harakiri() beside " +
        "the ini's harakiri; uWSGI 2.0.31 then SIGKILLs whole workers",
    ).toEqual([]);
  },
);
