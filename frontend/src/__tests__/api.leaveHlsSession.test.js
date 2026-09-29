import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { notifications } from '@mantine/notifications';
import API from '../api';

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}));

const T = 'v1.' + 'A'.repeat(22) + '.' + 'B'.repeat(43);
const SESSION = 'http://localhost:3000/hls/' + T;

describe('API.leaveHlsSession', () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn(() =>
      Promise.resolve(new Response(null, { status: 204 }))
    );
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    notifications.show.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('sends DELETE to the session URL with no Authorization header', async () => {
    const ok = await API.leaveHlsSession(SESSION);

    expect(ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(SESSION);
    expect(options.method).toBe('DELETE');
    expect(options.headers?.Authorization).toBeUndefined();
  });

  it('passes keepalive through', async () => {
    await API.leaveHlsSession(SESSION, { keepalive: true });

    expect(fetchMock.mock.calls[0][1].keepalive).toBe(true);
  });

  it('never throws on a refusal or a network failure', async () => {
    fetchMock.mockResolvedValueOnce(new Response('nope', { status: 403 }));
    await expect(API.leaveHlsSession(SESSION)).resolves.toBe(false);

    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await expect(API.leaveHlsSession(SESSION)).resolves.toBe(false);
  });

  it('shows no notification', async () => {
    fetchMock.mockResolvedValueOnce(new Response('nope', { status: 403 }));
    await API.leaveHlsSession(SESSION);
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await API.leaveHlsSession(SESSION);
    await API.leaveHlsSession(SESSION, { keepalive: true });

    expect(notifications.show).not.toHaveBeenCalled();
  });

  it('logs only the status, never the session URL', async () => {
    fetchMock.mockResolvedValueOnce(new Response('nope', { status: 403 }));
    await API.leaveHlsSession(SESSION);

    const logged = JSON.stringify(console.warn.mock.calls);
    expect(logged).toContain('403');
    expect(logged).not.toContain(T);
  });
});
