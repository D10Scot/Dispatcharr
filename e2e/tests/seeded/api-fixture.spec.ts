import { test, expect } from '../../fixtures';
import type { Channel } from '../../fixtures';

test('api fixture authenticates against a protected endpoint', { tag: '@contract' }, async ({ api }) => {
  const res = await api.get('/api/channels/channels/');
  expect(res.status()).toBe(200);

  // A bare 200 also passes if the SPA catch-all shadows this route: it
  // answers 200 with `index.html`, not JSON. `dispatcharr/urls.py` mounts
  // `path("api/", include(...))` first and the catch-all
  // `path("<path:unused_path>", ...)` last, on purpose, but a routing
  // regression that broke that ordering would still return 200. `api.json`
  // throws on a non-JSON body, which an HTML response is, and the array
  // shape confirms this really is the channels list rather than some other
  // JSON document. `ChannelPagination.paginate_queryset`
  // (`apps/channels/api_views.py`) disables pagination — returns the bare
  // queryset, not the `{results: [...]}` envelope — unless a `page` or
  // `page_size` query param is present, and this call passes neither.
  const body = await api.json<Channel[]>(res, 'protected endpoint read-back');
  expect(Array.isArray(body)).toBe(true);
});

test('api fixture recovers from an expired access token', { tag: '@contract' }, async ({
  api,
  request,
}) => {
  // Simulate the 30-minute expiry without waiting for it.
  api.expireAccessTokenForTest();

  const res = await api.get('/api/channels/channels/');
  expect(res.status()).toBe(200);

  // Same routing-regression guard as the test above: a non-JSON body throws
  // here rather than letting a shadowed route read as a successful refresh.
  const body = await api.json<Channel[]>(res, 'recovered read-back');
  expect(Array.isArray(body)).toBe(true);

  // The 200 above is only evidence of a *recovered* token if the endpoint
  // still refuses an unauthenticated caller — otherwise the same 200 would
  // appear just as well with the view turned `AllowAny`, proving nothing
  // about the refresh path. `request` is Playwright's built-in,
  // unauthenticated fixture; it carries no bearer token at all.
  const unauth = await request.get('/api/channels/channels/');
  expect(unauth.status()).toBe(401);
});
