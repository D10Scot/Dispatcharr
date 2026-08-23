import { test, expect } from '../../fixtures';

// Exemplar: polling is the default way to wait for backend state. Prefer it
// over the WebSocket unless the state is only observable there.
test('waitFor.resource polls until a created channel appears', async ({
  api,
  seed,
  waitFor,
}) => {
  const channel = await seed.channel();

  const found = await waitFor.resource(
    `/api/channels/channels/${channel.id}/`,
    (body) => body.name === channel.name
  );

  expect(found.id).toBe(channel.id);
});

// Exemplar: the WebSocket fixture, for state the REST API does not expose.
// Every socket receives connection_established on connect.
test('ws fixture receives the connection handshake', async ({ ws }) => {
  const message = await ws.waitForMessage('connection_established');
  expect(message.data.success).toBe(true);
});
