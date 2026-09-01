import { test, expect } from '../../fixtures';

test('api fixture authenticates against a protected endpoint', { tag: '@contract' }, async ({ api }) => {
  const res = await api.get('/api/channels/channels/');
  expect(res.status()).toBe(200);
});

test('api fixture recovers from an expired access token', { tag: '@contract' }, async ({ api }) => {
  // Simulate the 30-minute expiry without waiting for it.
  api.expireAccessTokenForTest();

  const res = await api.get('/api/channels/channels/');
  expect(res.status()).toBe(200);
});
