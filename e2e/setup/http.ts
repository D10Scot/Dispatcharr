/**
 * Small shared shapes for talking to the REST API from the setup phase.
 *
 * `fixtures/api.ts` is the harness's HTTP client for *tests*; this is for the
 * serial setup code, which runs before any fixture exists and holds a bare
 * `APIRequestContext`.
 */

/**
 * The rows of a DRF list response, whether or not pagination is switched on.
 *
 * Every list endpoint this harness reads (`/api/accounts/users/`,
 * `/api/m3u/accounts/`) returns a **bare array** today. The `results` branch is
 * insurance against `DEFAULT_PAGINATION_CLASS` being set later, not something
 * observed — and the only reason it exists is that switching it on would
 * otherwise turn every list read in the harness into a silent empty array
 * (`Array.isArray(body)` false, so `.find()` on nothing) rather than a failure.
 * One implementation means one place to change when that day comes.
 */
export function listRows<T>(body: unknown): T[] {
  if (Array.isArray(body)) return body as T[];
  const results = (body as { results?: unknown } | null | undefined)?.results;
  return Array.isArray(results) ? (results as T[]) : [];
}
