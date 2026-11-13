/**
 * No uWSGI ini under `docker/` sets both `harakiri` and `post-buffering`, and
 * the two API inis read request bodies in Python instead.
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
 * into a connection reset, so the API inis set
 * `env = DISPATCHARR_WSGI_SPOOL_REQUEST_BODY=1`, which turns on
 * `dispatcharr/request_body_spool.py`. This guard asserts that line too, so
 * the variable cannot be dropped while the comment above it survives.
 *
 * No container and no browser: this reads files.
 *
 * Verified by mutation: re-adding `post-buffering = 4096` to
 * `docker/uwsgi.ini` failed the first test naming the file and both line
 * numbers; deleting the `env =` line from `docker/uwsgi.modular.ini` failed
 * the second.
 */
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { test, expect } from "@playwright/test";

const DOCKER = path.resolve(process.cwd(), "..", "docker");
const API_INIS = ["uwsgi.ini", "uwsgi.modular.ini"];
const SPOOL_ENV = "env = DISPATCHARR_WSGI_SPOOL_REQUEST_BODY=1";

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

function uwsgiInis(): string[] {
  return readdirSync(DOCKER)
    .filter((name) => /^uwsgi.*\.ini$/.test(name))
    .sort();
}

test(
  "no uWSGI ini combines harakiri with post-buffering",
  { tag: "@contract" },
  () => {
    const inis = uwsgiInis();
    expect(inis, "found no docker/uwsgi*.ini to check").toEqual(
      expect.arrayContaining(API_INIS),
    );
    const offenders: string[] = [];
    for (const name of inis) {
      const found = directives(readFileSync(path.join(DOCKER, name), "utf8"));
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
        "(dispatcharr/request_body_spool.py)",
    ).toEqual([]);
  },
);

test(
  "the API inis turn on the Python request-body spool",
  { tag: "@contract" },
  () => {
    const missing = API_INIS.filter((name) => {
      const found = directives(readFileSync(path.join(DOCKER, name), "utf8"));
      return !found.some(
        (d) => `${d.key} = ${d.value.replace(/\s+#.*$/, "")}` === SPOOL_ENV,
      );
    });
    expect(
      missing,
      `each API ini must carry \`${SPOOL_ENV}\`: without post-buffering, a view ` +
        "that answers before reading a large body leaves it on the socket and " +
        "the client gets a reset instead of the 4xx",
    ).toEqual([]);
  },
);
