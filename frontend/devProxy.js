// The vite dev server's proxy table (#542).
//
// With DISPATCHARR_ENV=dev there is no nginx: vite serves the SPA on :9191 and
// forwards what nginx would have routed elsewhere. /api/ and /ws/ go to
// Django and Daphne as before. The live surface -- the TS tune, the XC live
// roots and the HLS session resources -- goes to relay-go, which is where
// nginx sends it in production (docker/nginx.conf: ^~ /proxy/ts/stream/,
// ^~ /hls/, ^~ /live/ and the XC three-segment regex). With no nginx there is
// no auth_request hop, and the relay asks Django itself
// (relay/httpapi/authorize.go, the dev fallback), so nothing here authorizes
// anything.
//
// ORDER IS LOAD-BEARING. vite tries the keys in insertion order and takes the
// first that matches; a key starting with ^ is a RegExp tested against the
// request URL WITH its query string. The XC regex also matches three-segment
// /api/ and /ws/ paths ending in a number, which nginx settles by preferring
// ^~ prefixes over regexes, so here it is listed last. The two prefixes keep
// nginx's trailing slash (^~ /api/, ^~ /ws/): without it an XC username
// starting with "api" or "ws" (/wsmith/pass/123.ts) would match them first.

// A missing or non-integer DISPATCHARR_RELAY_GO_PORT means 5658, as
// docker/init/03-init-dispatcharr.sh does for nginx's upstream. relay-go
// itself refuses to start on a non-integer value (relay/config/config.go).
export const relayGoPort = (env) => {
  const raw = env.DISPATCHARR_RELAY_GO_PORT;
  return raw && /^\d+$/.test(raw) ? raw : '5658';
};

// docker/nginx.conf's XC live root, plus an optional query string.
export const XC_LIVE_ROOT = '^/[^/]+/[^/]+/\\d+(?:\\.[A-Za-z0-9]+)?(?:\\?.*)?$';

export const devProxy = (env) => {
  const relay = () => ({
    target: `http://127.0.0.1:${relayGoPort(env)}`,
    changeOrigin: true,
    secure: false,
  });
  return {
    '/api/': {
      target: 'http://127.0.0.1:5656',
      changeOrigin: true,
      secure: false,
    },
    '/ws/': {
      target: 'http://127.0.0.1:8001',
      changeOrigin: true,
      secure: false,
      ws: true,
    },
    '/proxy/ts/stream/': relay(),
    '/live/': relay(),
    '/hls/': relay(),
    [XC_LIVE_ROOT]: relay(),
  };
};
