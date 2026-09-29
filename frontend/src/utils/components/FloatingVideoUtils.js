export const PLAYER_PREFS_KEY = 'dispatcharr-player-prefs';

/**
 * Build a live-stream preview URL that always forces mpegts output (required
 * for mpegts.js) and optionally appends the browser-local web player output
 * profile preference.
 */
export const buildLiveStreamUrl = (path) => {
  const prefs = getPlayerPrefs();
  const params = new URLSearchParams({ output_format: 'mpegts' });
  const profileId = prefs.webPlayerOutputProfileId;
  if (profileId) params.set('output_profile', String(profileId));
  return `${path}?${params.toString()}`;
};

// The relay's entry and first-playlist waits (relay/httpapi/hls.go:47-48,
// defaultReadyWait = defaultPlaylistWait = QuickProbe 3 s + FullProbe 8 s +
// 3 x StallTimeout 10 s + 2 s, ruling R57).
export const HLS_RELAY_WAIT_MS = 43_000;
// The next-source budget the relay spends before the entry's ready wait starts
// (relay/httpapi/stream.go:193, tuneBudget = 2 x (2 s + 5 s) + 100 ms).
export const HLS_RELAY_TUNE_BUDGET_MS = 14_100;
// The entry (manifest) timeout: the tune budget plus the ready wait plus a margin,
// under nginx's 300 s proxy_read_timeout on ^~ /proxy/ts/stream/
// (docker/nginx.conf:350).
export const HLS_ENTRY_TIMEOUT_MS =
  HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS + 7_900; // 65 000
// The media-playlist timeout: above the relay's 43 s first-segment wait, under
// nginx's 60 s proxy_read_timeout on ^~ /hls/ (docker/nginx.conf:488).
export const HLS_PLAYLIST_TIMEOUT_MS = 50_000;
// How long a switch waits for the previous session's leave.
export const HLS_LEAVE_WAIT_MS = 2_000;
// v1.<22-char sid>.<43-char MAC>, relay/control/mediasession.go.
export const MEDIA_SESSION_TOKEN_RE =
  /^v1\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$/;

/**
 * The channel HLS entry URL. Never reads the player preferences: an HLS tune
 * carries no Output Profile (ruling R18).
 */
export const buildChannelHlsUrl = (path) => `${path}?output_format=hls`;

export const isChannelHlsUrl = (url) => {
  if (!url || typeof url !== 'string') return false;
  try {
    const u = new URL(url, window.location.origin);
    return (
      u.pathname.startsWith('/proxy/ts/stream/') &&
      u.searchParams.get('output_format') === 'hls'
    );
  } catch {
    return false;
  }
};

/**
 * `<origin>/hls/<token>` for a playlist URL naming a media session, using the
 * playlist's own origin; null when the URL is not a session resource.
 */
export const hlsSessionUrlOf = (playlistUrl) => {
  try {
    const u = new URL(playlistUrl, window.location.origin);
    const [, first, token] = u.pathname.split('/');
    if (first !== 'hls' || !MEDIA_SESSION_TOKEN_RE.test(token || '')) {
      return null;
    }
    return `${u.origin}/hls/${token}`;
  } catch {
    return null;
  }
};

export const withAccessTokenParam = (url, token) => {
  if (!token) return url;
  const u = new URL(url, window.location.origin);
  u.searchParams.set('token', token);
  // Keep a relative input relative.
  return /^[a-z][a-z0-9+.-]*:/i.test(url)
    ? u.href
    : `${u.pathname}${u.search}${u.hash}`;
};

/**
 * hls.js config for a live channel. The timeouts are derived from the relay's
 * worst legitimate answers (see the constants above), so its own 503 always
 * arrives before hls.js abandons the request.
 */
export const buildLiveHlsConfig = (getAccessToken) => ({
  enableWorker: true,
  lowLatencyMode: false,
  liveSyncDurationCount: 3,
  backBufferLength: 120,
  manifestLoadPolicy: {
    default: {
      maxTimeToFirstByteMs: Infinity,
      maxLoadTimeMs: HLS_ENTRY_TIMEOUT_MS,
      timeoutRetry: null,
      errorRetry: { maxNumRetry: 1, retryDelayMs: 1000, maxRetryDelayMs: 1000 },
    },
  },
  playlistLoadPolicy: {
    default: {
      maxTimeToFirstByteMs: HLS_PLAYLIST_TIMEOUT_MS,
      maxLoadTimeMs: HLS_PLAYLIST_TIMEOUT_MS,
      timeoutRetry: { maxNumRetry: 2, retryDelayMs: 0, maxRetryDelayMs: 0 },
      errorRetry: { maxNumRetry: 2, retryDelayMs: 1000, maxRetryDelayMs: 8000 },
    },
  },
  xhrSetup: (xhr) => {
    const token = getAccessToken();
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
  },
});

export const getHlsLivePlayerErrorMessage = ({
  status,
  details,
  sessionEnded,
  channelStopped,
} = {}) => {
  if (channelStopped) {
    return 'The channel stopped, or this idle session was ended.';
  }
  if (sessionEnded) return 'The playback session ended.';
  if (status === 401 || status === 403) {
    return 'You are not allowed to watch this channel.';
  }
  if (status === 404) return 'Channel not found.';
  if (status === 429) {
    return 'Stream limit reached. Close another stream and try again.';
  }
  if (status === 502) return "The channel's source is unavailable.";
  if (status === 503) {
    return 'The channel is not ready yet. Try again in a moment.';
  }
  if (
    details === 'manifestIncompatibleCodecsError' ||
    details === 'bufferIncompatibleCodecsError'
  ) {
    return "This channel's video or audio format can't be played in this browser.";
  }
  return `Playback error: ${details || 'unknown'}`;
};

export const getPlayerPrefs = () => {
  try {
    return JSON.parse(localStorage.getItem(PLAYER_PREFS_KEY) || '{}');
  } catch {
    return {};
  }
};

export const savePlayerPrefs = (updates) => {
  try {
    localStorage.setItem(
      PLAYER_PREFS_KEY,
      JSON.stringify({ ...getPlayerPrefs(), ...updates })
    );
  } catch {}
};

export const getLivePlayerErrorMessage = (errorType, errorDetail) => {
  if (errorType !== 'MediaError') {
    return errorDetail
      ? `Error: ${errorType} - ${errorDetail}`
      : `Error: ${errorType}`;
  }

  const errorString = errorDetail?.toLowerCase() || '';

  if (
    errorString.includes('audio') ||
    errorString.includes('ac3') ||
    errorString.includes('ac-3')
  ) {
    return 'Audio codec not supported by your browser. Try Chrome or Edge for better audio codec support.';
  }

  if (
    errorString.includes('video') ||
    errorString.includes('h264') ||
    errorString.includes('h.264')
  ) {
    return 'Video codec not supported by your browser. Try Chrome or Edge for better video codec support.';
  }

  if (errorString.includes('mse')) {
    return "Your browser doesn't support the codecs used in this stream. Try Chrome or Edge for better compatibility.";
  }

  return 'Media codec not supported by your browser. This may be due to unsupported audio (AC3) or video codecs. Try Chrome or Edge.';
};

export const getVODPlayerErrorMessage = (error) => {
  if (!error) return 'Video playback error';

  switch (error.code) {
    case error.MEDIA_ERR_ABORTED:
      return 'Video playback was aborted';
    case error.MEDIA_ERR_NETWORK:
      return 'Network error while loading video';
    case error.MEDIA_ERR_DECODE:
      return 'Video codec not supported by your browser';
    case error.MEDIA_ERR_SRC_NOT_SUPPORTED:
      return 'Video format not supported by your browser';
    default:
      return error.message || 'Unknown video error';
  }
};

export const getClientCoordinates = (event) => ({
  clientX: event.touches?.[0]?.clientX ?? event.clientX,
  clientY: event.touches?.[0]?.clientY ?? event.clientY,
});

export const calculateNewDimensions = (
  deltaX,
  deltaY,
  startWidth,
  startHeight,
  handle,
  ratio
) => {
  const widthDelta = deltaX * handle.xDir;
  const heightDelta = deltaY * handle.yDir;

  let width = startWidth + widthDelta;
  let height = width / ratio;

  // Use vertical-driven resize if user drags mostly vertically
  if (Math.abs(deltaY) > Math.abs(deltaX)) {
    height = startHeight + heightDelta;
    width = height * ratio;
  }

  return { width, height };
};

export const applyConstraints = (
  width,
  height,
  ratio,
  startPos,
  handle,
  minWidth,
  minHeight,
  visibleMargin
) => {
  // Apply minimum constraints
  if (width < minWidth) {
    width = minWidth;
    height = width / ratio;
  }
  if (height < minHeight) {
    height = minHeight;
    width = height * ratio;
  }

  // Apply viewport constraints
  const posX = startPos?.x ?? 0;
  const posY = startPos?.y ?? 0;
  // Absolute caps ensure the player can never exceed the viewport even when
  // its position is negative (partially off-screen on the opposite edge).
  const maxWidth = !handle.isLeft
    ? Math.min(
        window.innerWidth - visibleMargin,
        Math.max(minWidth, window.innerWidth - posX - visibleMargin)
      )
    : null;
  const maxHeight = !handle.isTop
    ? Math.min(
        window.innerHeight - visibleMargin,
        Math.max(minHeight, window.innerHeight - posY - visibleMargin)
      )
    : null;

  if (maxWidth && width > maxWidth) {
    width = maxWidth;
    height = width / ratio;
  }
  if (maxHeight && height > maxHeight) {
    height = maxHeight;
    width = height * ratio;
  }

  // Final adjustment to maintain aspect ratio
  if (maxWidth && width > maxWidth) {
    width = maxWidth;
    height = width / ratio;
  }

  return { width, height };
};
