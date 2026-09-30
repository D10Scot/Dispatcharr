// @vitest-environment node
/* global process */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import viteConfig from '../../vite.config.js';
import { devProxy, relayGoPort, XC_LIVE_ROOT } from '../../devProxy.js';

// vite's own rule (vite 7, doesProxyContextMatchUrl): the keys are tried in
// insertion order, a key starting with ^ is a RegExp tested against the URL
// with its query string, any other key is a prefix. First match wins.
const routeOf = (table, url) =>
  Object.keys(table).find((key) =>
    key.startsWith('^') ? new RegExp(key).test(url) : url.startsWith(key)
  );

const RELAY = 'http://127.0.0.1:5658';
const table = devProxy({});

describe('the dev proxy table (#542)', () => {
  it('is the table vite.config.js serves', () => {
    expect(
      viteConfig.server.proxy,
      'vite.config.js does not take its proxy table from devProxy()'
    ).toEqual(devProxy(process.env));
  });

  it.each([
    [
      '/proxy/ts/stream/0b6f2c1e-7c55-4f53-9a55-2b5f3f5b8a10?output_format=mpegts',
      '/proxy/ts/stream/',
    ],
    [
      '/proxy/ts/stream/0b6f2c1e-7c55-4f53-9a55-2b5f3f5b8a10?output_format=hls',
      '/proxy/ts/stream/',
    ],
    ['/hls/v1.abc.def/video.m3u8', '/hls/'],
    ['/hls/v1.abc.def/video/12.m4s', '/hls/'],
    ['/live/user/pass/123.ts', '/live/'],
    ['/user/pass/123', XC_LIVE_ROOT],
    ['/user/pass/123.ts', XC_LIVE_ROOT],
    ['/user/pass/123.m3u8?token=x', XC_LIVE_ROOT],
    ['/wsmith/pass/123.ts', XC_LIVE_ROOT],
    ['/apiuser/pass/123.ts', XC_LIVE_ROOT],
  ])('sends %s to relay-go', (url, key) => {
    expect(routeOf(table, url), `${url} matched the wrong key`).toBe(key);
    expect(table[key].target, `${key} does not point at relay-go`).toBe(RELAY);
  });

  it.each([
    ['/api/channels/5', '/api/'],
    ['/api/channels/recordings/4/hls/index.m3u8', '/api/'],
    ['/ws/x/5', '/ws/'],
  ])('keeps %s on its own backend, not the XC root', (url, key) => {
    expect(
      routeOf(table, url),
      `${url} left its own backend: the XC regex must come after /api/ and /ws/`
    ).toBe(key);
  });

  it.each([
    '/',
    '/channels',
    '/guide',
    '/plugins/browse',
    '/src/pages/Guide.jsx',
    '/node_modules/.vite/deps/react.js?v=1234',
    '/@vite/client',
    '/@fs/app/frontend/src/main.jsx',
    '/proxy/ts/status',
    '/proxy/vod/movie/1',
  ])('leaves %s to vite', (url) => {
    expect(routeOf(table, url), `${url} is proxied`).toBeUndefined();
  });

  it("is nginx's XC live root plus an optional query string", () => {
    const nginx = readFileSync(
      new URL('../../../docker/nginx.conf', import.meta.url),
      'utf8'
    );
    const regex = nginx.match(/location ~ (\^\/\[\^\/\]\+\/\S+\$) \{/)[1];
    expect(XC_LIVE_ROOT, 'devProxy.js has drifted from docker/nginx.conf').toBe(
      regex.replace(/\$$/, '(?:\\?.*)?$')
    );
  });

  it('lists the XC regex last', () => {
    expect(Object.keys(table).at(-1)).toBe(XC_LIVE_ROOT);
  });

  it.each([
    [{}, '5658'],
    [{ DISPATCHARR_RELAY_GO_PORT: '' }, '5658'],
    [{ DISPATCHARR_RELAY_GO_PORT: 'abc' }, '5658'],
    [{ DISPATCHARR_RELAY_GO_PORT: '6000' }, '6000'],
  ])('reads the relay port from %j', (env, port) => {
    expect(relayGoPort(env)).toBe(port);
    expect(devProxy(env)['/hls/'].target).toBe(`http://127.0.0.1:${port}`);
  });
});
