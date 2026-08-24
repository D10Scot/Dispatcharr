/**
 * `playwright/.auth/` — where the harness keeps live credentials — and the
 * file modes it keeps them at.
 *
 * ---------------------------------------------------------------------------
 * Why 0700/0600
 * ---------------------------------------------------------------------------
 * This directory holds **live admin JWTs**: `tokens.json` and `admin.json`
 * carry the bootstrap superuser's access and refresh pair, and
 * `principals.json` carries one pair per non-admin principal. An access token
 * is good for 30 minutes and a refresh token for a day, so a reader of these
 * files is an administrator of the container for as long as that lasts —
 * without needing the password, and without spending anything from the
 * 3/minute login budget that would otherwise make credential stuffing visible.
 *
 * The threat model narrowed to exactly this. The container is published on
 * 127.0.0.1 only (see `e2e/README.md`), which removed the network reader; what
 * that leaves is a **local** reader — another account on the same machine, or
 * a process running as one. Default `0755`/`0644` under a default umask is
 * world-readable, so every local account could read them. File modes are the
 * control that addresses a local reader, and this module is where the harness
 * applies it.
 *
 * The gitignore entry (`e2e/playwright/.auth/`) is a different control for a
 * different reader and does not overlap: it stops the files being *committed*,
 * and says nothing about who can read them on disk.
 *
 * ---------------------------------------------------------------------------
 * Why an explicit chmod, and not just the `mode` option
 * ---------------------------------------------------------------------------
 * Both `fs.mkdirSync`'s and `fs.writeFileSync`'s `mode` apply **only when the
 * entry is actually created**, and are masked by the process umask when they
 * do. Neither touches a directory or file that already exists — so a checkout
 * that ran this harness before this change would keep its `0755` directory and
 * `0644` files indefinitely, which is the case that matters most: those are
 * the tokens that have already been sitting there. The chmod is unconditional
 * for that reason, and is also what makes the result independent of umask.
 */
import fs from 'node:fs';
import path from 'node:path';

/** Relative to the Playwright rootDir, like the paths in `api.ts` and `principals.ts`. */
export const AUTH_DIR = 'playwright/.auth';

/** rwx------ */
const DIR_MODE = 0o700;

/** rw------- */
const FILE_MODE = 0o600;

/**
 * Create the auth directory if it is missing, and tighten it to 0700 whether
 * it was missing or not. Idempotent; safe to call on every write.
 */
export function ensureAuthDir(): void {
  fs.mkdirSync(AUTH_DIR, { recursive: true, mode: DIR_MODE });
  fs.chmodSync(AUTH_DIR, DIR_MODE);
}

/**
 * Write `contents` to `file` at 0600, tightening an existing file too.
 *
 * `file` is expected to sit inside {@link AUTH_DIR}; the directory is ensured
 * first so a caller never has to remember to.
 */
export function writeAuthFile(file: string, contents: string): void {
  ensureAuthDir();
  fs.writeFileSync(file, contents, { mode: FILE_MODE });
  fs.chmodSync(file, FILE_MODE);
}

/**
 * As {@link writeAuthFile}, but through a temp file and a rename, so a
 * concurrent reader never catches a half-written file.
 *
 * Parallel workers refresh their access tokens at the same time, so the temp
 * name carries the pid (and a timestamp) to keep two of them off one another's
 * scratch file. `rename` preserves the temp file's mode, so the 0600 set on it
 * is the mode the destination ends up with.
 */
export function writeAuthFileAtomically(file: string, contents: string): void {
  const temp = path.join(
    path.dirname(file),
    `.${path.basename(file)}.${process.pid}.${Date.now()}.tmp`
  );
  writeAuthFile(temp, contents);
  fs.renameSync(temp, file);
}
