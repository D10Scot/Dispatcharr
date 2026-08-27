/**
 * Thrown by request-parsing and validation code on bad client input. Caught
 * in `server.ts`'s `requestListener` and mapped to 400, distinct from the
 * generic 500 for everything else — every route added from here on (Tasks
 * 3-7's `POST /s/<id>/fault` and `/rate`) should validate through this
 * rather than re-deriving it.
 *
 * Lives in its own leaf module rather than `server.ts` or `scenario.ts`:
 * `scenario.ts`'s field validator needs it, `server.ts` already imports from
 * `scenario.ts`, and `scenario.ts` importing back from `server.ts` would be
 * a cycle.
 */
export class BadRequestError extends Error {}
