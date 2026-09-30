import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  getLivePlayerErrorMessage,
  getVODPlayerErrorMessage,
  getClientCoordinates,
  calculateNewDimensions,
  applyConstraints,
  PLAYER_PREFS_KEY,
  getPlayerPrefs,
  savePlayerPrefs,
  buildLiveStreamUrl,
  buildChannelHlsUrl,
  isChannelHlsUrl,
  hlsSessionUrlOf,
  withAccessTokenParam,
  buildLiveHlsConfig,
  getHlsLivePlayerErrorMessage,
  HLS_RELAY_WAIT_MS,
  HLS_RELAY_READY_WAIT_MS,
  HLS_RELAY_TUNE_BUDGET_MS,
} from '../FloatingVideoUtils';

describe('FloatingVideoUtils', () => {
  describe('getLivePlayerErrorMessage', () => {
    it('should return formatted error for non-MediaError types', () => {
      expect(
        getLivePlayerErrorMessage('NetworkError', 'Connection failed')
      ).toBe('Error: NetworkError - Connection failed');
    });

    it('should return error type only when no detail provided', () => {
      expect(getLivePlayerErrorMessage('NetworkError')).toBe(
        'Error: NetworkError'
      );
    });

    it('should return audio codec message for audio-related errors', () => {
      const result = getLivePlayerErrorMessage(
        'MediaError',
        'audio codec not supported'
      );
      expect(result).toBe(
        'Audio codec not supported by your browser. Try Chrome or Edge for better audio codec support.'
      );
    });

    it('should return audio codec message for AC3 errors', () => {
      const result = getLivePlayerErrorMessage('MediaError', 'AC3 codec issue');
      expect(result).toContain('Audio codec not supported');
    });

    it('should return video codec message for video-related errors', () => {
      const result = getLivePlayerErrorMessage(
        'MediaError',
        'video codec h264 failed'
      );
      expect(result).toBe(
        'Video codec not supported by your browser. Try Chrome or Edge for better video codec support.'
      );
    });

    it('should return MSE message for MSE-related errors', () => {
      const result = getLivePlayerErrorMessage(
        'MediaError',
        'MSE not supported'
      );
      expect(result).toBe(
        "Your browser doesn't support the codecs used in this stream. Try Chrome or Edge for better compatibility."
      );
    });

    it('should return generic codec message for other MediaError cases', () => {
      const result = getLivePlayerErrorMessage(
        'MediaError',
        'unknown codec issue'
      );
      expect(result).toBe(
        'Media codec not supported by your browser. This may be due to unsupported audio (AC3) or video codecs. Try Chrome or Edge.'
      );
    });

    it('should handle null errorDetail for MediaError', () => {
      const result = getLivePlayerErrorMessage('MediaError', null);
      expect(result).toBe(
        'Media codec not supported by your browser. This may be due to unsupported audio (AC3) or video codecs. Try Chrome or Edge.'
      );
    });
  });

  describe('getVODPlayerErrorMessage', () => {
    it('should return default message when error is null', () => {
      expect(getVODPlayerErrorMessage(null)).toBe('Video playback error');
    });

    it('should return aborted message for MEDIA_ERR_ABORTED', () => {
      const error = { code: 1, MEDIA_ERR_ABORTED: 1 };
      expect(getVODPlayerErrorMessage(error)).toBe(
        'Video playback was aborted'
      );
    });

    it('should return network message for MEDIA_ERR_NETWORK', () => {
      const error = { code: 2, MEDIA_ERR_NETWORK: 2 };
      expect(getVODPlayerErrorMessage(error)).toBe(
        'Network error while loading video'
      );
    });

    it('should return codec message for MEDIA_ERR_DECODE', () => {
      const error = { code: 3, MEDIA_ERR_DECODE: 3 };
      expect(getVODPlayerErrorMessage(error)).toBe(
        'Video codec not supported by your browser'
      );
    });

    it('should return format message for MEDIA_ERR_SRC_NOT_SUPPORTED', () => {
      const error = { code: 4, MEDIA_ERR_SRC_NOT_SUPPORTED: 4 };
      expect(getVODPlayerErrorMessage(error)).toBe(
        'Video format not supported by your browser'
      );
    });

    it('should return error message for unknown error codes', () => {
      const error = { code: 99, message: 'Custom error message' };
      expect(getVODPlayerErrorMessage(error)).toBe('Custom error message');
    });

    it('should return default message for unknown error without message', () => {
      const error = { code: 99 };
      expect(getVODPlayerErrorMessage(error)).toBe('Unknown video error');
    });
  });

  describe('getClientCoordinates', () => {
    it('should extract coordinates from mouse event', () => {
      const event = { clientX: 100, clientY: 200 };
      expect(getClientCoordinates(event)).toEqual({
        clientX: 100,
        clientY: 200,
      });
    });

    it('should extract coordinates from touch event', () => {
      const event = { touches: [{ clientX: 150, clientY: 250 }] };
      expect(getClientCoordinates(event)).toEqual({
        clientX: 150,
        clientY: 250,
      });
    });

    it('should prioritize touch coordinates over mouse coordinates', () => {
      const event = {
        touches: [{ clientX: 150, clientY: 250 }],
        clientX: 100,
        clientY: 200,
      };
      expect(getClientCoordinates(event)).toEqual({
        clientX: 150,
        clientY: 250,
      });
    });

    it('should handle undefined coordinates', () => {
      const event = {};
      expect(getClientCoordinates(event)).toEqual({
        clientX: undefined,
        clientY: undefined,
      });
    });
  });

  describe('calculateNewDimensions', () => {
    const ratio = 16 / 9;

    it('should calculate dimensions based on horizontal drag', () => {
      const handle = { xDir: 1, yDir: 0, isLeft: false, isTop: false };
      const result = calculateNewDimensions(100, 10, 400, 225, handle, ratio);

      expect(result.width).toBe(500);
      expect(result.height).toBeCloseTo(281.25, 1);
    });

    it('should calculate dimensions based on vertical drag', () => {
      const handle = { xDir: 0, yDir: 1, isLeft: false, isTop: false };
      const result = calculateNewDimensions(10, 100, 400, 225, handle, ratio);

      expect(result.height).toBe(325);
      expect(result.width).toBeCloseTo(577.78, 1);
    });

    it('should use vertical-driven resize when vertical delta is larger', () => {
      const handle = { xDir: 1, yDir: 1, isLeft: false, isTop: false };
      const result = calculateNewDimensions(20, 100, 400, 225, handle, ratio);

      expect(result.height).toBe(325);
      expect(result.width).toBeCloseTo(577.78, 1);
    });

    it('should handle negative deltas', () => {
      const handle = { xDir: -1, yDir: 0, isLeft: true, isTop: false };
      const result = calculateNewDimensions(-50, 0, 400, 225, handle, ratio);

      expect(result.width).toBe(450);
      expect(result.height).toBeCloseTo(253.13, 1);
    });
  });

  describe('applyConstraints', () => {
    const ratio = 16 / 9;
    const minWidth = 200;
    const minHeight = 112.5;
    const visibleMargin = 50;

    beforeEach(() => {
      Object.defineProperty(window, 'innerWidth', {
        writable: true,
        value: 1920,
      });
      Object.defineProperty(window, 'innerHeight', {
        writable: true,
        value: 1080,
      });
    });

    it('should apply minimum width constraint', () => {
      const handle = { isLeft: false, isTop: false };
      const result = applyConstraints(
        100,
        50,
        ratio,
        { x: 0, y: 0 },
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.width).toBe(minWidth);
      expect(result.height).toBeCloseTo(minWidth / ratio, 1);
    });

    it('should apply minimum height constraint', () => {
      const handle = { isLeft: false, isTop: false };
      const result = applyConstraints(
        300,
        100,
        ratio,
        { x: 0, y: 0 },
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.height).toBe(minHeight);
      expect(result.width).toBeCloseTo(minHeight * ratio, 1);
    });

    it('should apply maximum width constraint based on viewport', () => {
      const handle = { isLeft: false, isTop: false };
      const startPos = { x: 1200, y: 100 };
      const result = applyConstraints(
        800,
        450,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      const maxWidth = 1920 - 1200 - 50; // 670
      expect(result.width).toBe(maxWidth);
      expect(result.height).toBeCloseTo(maxWidth / ratio, 1);
    });

    it('should apply maximum height constraint based on viewport', () => {
      const handle = { isLeft: false, isTop: false };
      const startPos = { x: 100, y: 700 };
      const result = applyConstraints(
        500,
        400,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      const maxHeight = 1080 - 700 - 50; // 330
      expect(result.height).toBe(maxHeight);
      expect(result.width).toBeCloseTo(maxHeight * ratio, 1);
    });

    it('should cap maximum width at viewport width when position is negative', () => {
      // Use a tall viewport so only the width constraint is the binding factor
      window.innerHeight = 3000;
      const handle = { isLeft: false, isTop: false };
      const startPos = { x: -200, y: 0 };
      const result = applyConstraints(
        2000,
        1125,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );
      // Without the fix: maxWidth would be 1920 - (-200) - 50 = 2070 (exceeds viewport)
      // With the fix: capped at window.innerWidth - visibleMargin = 1870
      const expectedWidth = 1920 - 50;
      expect(result.width).toBe(expectedWidth);
      expect(result.height).toBeCloseTo(expectedWidth / ratio, 1);
    });

    it('should cap maximum height at viewport height when position is negative', () => {
      // Use a wide viewport so only the height constraint is the binding factor.
      // Input height (1100) is above the absolute cap (1080-50=1030) but below the
      // uncapped formula (1080-(-100)-50=1130), proving the absolute cap is enforced.
      window.innerWidth = 4000;
      const handle = { isLeft: false, isTop: false };
      const startPos = { x: 0, y: -100 };
      const inputHeight = 1100;
      const result = applyConstraints(
        inputHeight * ratio,
        inputHeight,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );
      // Without the fix: maxHeight would be 1080 - (-100) - 50 = 1130, so 1100 < 1130 → no cap
      // With the fix: capped at window.innerHeight - visibleMargin = 1030
      const expectedHeight = 1080 - 50;
      expect(result.height).toBe(expectedHeight);
      expect(result.width).toBeCloseTo(expectedHeight * ratio, 1);
    });

    it('should not apply max width constraint for left handle', () => {
      const handle = { isLeft: true, isTop: false };
      const startPos = { x: 1800, y: 100 };
      const result = applyConstraints(
        500,
        281.25,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.width).toBe(500);
      expect(result.height).toBeCloseTo(281.25, 1);
    });

    it('should not apply max height constraint for top handle', () => {
      const handle = { isLeft: false, isTop: true };
      const startPos = { x: 100, y: 1000 };
      const result = applyConstraints(
        500,
        400,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.width).toBe(500);
      expect(result.height).toBe(400);
    });

    it('should handle null startPos', () => {
      const handle = { isLeft: false, isTop: false };
      const result = applyConstraints(
        300,
        168.75,
        ratio,
        null,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.width).toBe(300);
      expect(result.height).toBeCloseTo(168.75, 1);
    });
  });

  describe('getPlayerPrefs / savePlayerPrefs', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('should return an empty object when nothing is stored', () => {
      expect(getPlayerPrefs()).toEqual({});
    });

    it('should return an empty object when stored value is invalid JSON', () => {
      localStorage.setItem(PLAYER_PREFS_KEY, 'not-json');
      expect(getPlayerPrefs()).toEqual({});
    });

    it('should save and retrieve a volume value', () => {
      savePlayerPrefs({ volume: 0.5 });
      expect(getPlayerPrefs().volume).toBe(0.5);
    });

    it('should save and retrieve a muted value', () => {
      savePlayerPrefs({ muted: true });
      expect(getPlayerPrefs().muted).toBe(true);
    });

    it('should save and retrieve size', () => {
      savePlayerPrefs({ size: { width: 640, height: 360 } });
      expect(getPlayerPrefs().size).toEqual({ width: 640, height: 360 });
    });

    it('should save and retrieve position', () => {
      savePlayerPrefs({ position: { x: 100, y: 200 } });
      expect(getPlayerPrefs().position).toEqual({ x: 100, y: 200 });
    });

    it('should merge updates without losing existing keys', () => {
      savePlayerPrefs({ volume: 0.8, muted: false });
      savePlayerPrefs({ size: { width: 320, height: 180 } });
      const prefs = getPlayerPrefs();
      expect(prefs.volume).toBe(0.8);
      expect(prefs.muted).toBe(false);
      expect(prefs.size).toEqual({ width: 320, height: 180 });
    });

    it('should overwrite an existing key on update', () => {
      savePlayerPrefs({ volume: 0.5 });
      savePlayerPrefs({ volume: 1.0 });
      expect(getPlayerPrefs().volume).toBe(1.0);
    });

    it('should use PLAYER_PREFS_KEY as the storage key', () => {
      savePlayerPrefs({ volume: 0.7 });
      expect(localStorage.getItem(PLAYER_PREFS_KEY)).not.toBeNull();
    });
  });
});

describe('FloatingVideoUtils: live channels over HLS', () => {
  const T = 'v1.' + 'A'.repeat(22) + '.' + 'B'.repeat(43);

  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  describe('buildLiveStreamUrl', () => {
    it('forces mpegts output', () => {
      expect(buildLiveStreamUrl('/proxy/ts/stream/h')).toBe(
        '/proxy/ts/stream/h?output_format=mpegts'
      );
    });

    it('appends the web-player Output Profile preference', () => {
      localStorage.setItem(
        'dispatcharr-player-prefs',
        '{"webPlayerOutputProfileId":5}'
      );
      expect(buildLiveStreamUrl('/proxy/ts/stream/channel-123')).toBe(
        '/proxy/ts/stream/channel-123?output_format=mpegts&output_profile=5'
      );
    });
  });

  describe('buildChannelHlsUrl', () => {
    it('requests the hls output format', () => {
      expect(buildChannelHlsUrl('/proxy/ts/stream/u')).toBe(
        '/proxy/ts/stream/u?output_format=hls'
      );
    });

    it('ignores the web-player Output Profile preference (R18)', () => {
      localStorage.setItem(
        'dispatcharr-player-prefs',
        '{"webPlayerOutputProfileId":5}'
      );
      const url = buildChannelHlsUrl('/proxy/ts/stream/u');
      expect(url).toBe('/proxy/ts/stream/u?output_format=hls');
      expect(url).not.toContain('output_profile');
    });
  });

  describe('isChannelHlsUrl', () => {
    it.each([
      '/proxy/ts/stream/u?output_format=hls',
      'http://h:5656/proxy/ts/stream/u?output_format=hls',
    ])('is true for %s', (url) => {
      expect(isChannelHlsUrl(url)).toBe(true);
    });

    it.each([
      '/proxy/ts/stream/u?output_format=mpegts',
      '/api/channels/recordings/7/hls/index.m3u8',
      'http://example.com/stream.ts',
      null,
      '',
    ])('is false for %s', (url) => {
      expect(isChannelHlsUrl(url)).toBe(false);
    });
  });

  describe('hlsSessionUrlOf', () => {
    it('keeps the origin of an absolute playlist URL', () => {
      expect(
        hlsSessionUrlOf('http://localhost:3000/hls/' + T + '/video.m3u8')
      ).toBe('http://localhost:3000/hls/' + T);
    });

    it("uses the playlist's own origin, not the page's", () => {
      expect(hlsSessionUrlOf('http://h:5656/hls/' + T + '/video.m3u8')).toBe(
        'http://h:5656/hls/' + T
      );
    });

    it('resolves a path against the page origin', () => {
      expect(hlsSessionUrlOf('/hls/' + T + '/aac/12.m4s')).toBe(
        window.location.origin + '/hls/' + T
      );
    });

    it('rejects a malformed token and other paths', () => {
      const short = 'v1.' + 'A'.repeat(22) + '.' + 'B'.repeat(42);
      expect(hlsSessionUrlOf('/hls/' + short + '/video.m3u8')).toBeNull();
      expect(
        hlsSessionUrlOf('/api/channels/recordings/7/hls/index.m3u8')
      ).toBeNull();
      expect(hlsSessionUrlOf('/proxy/ts/stream/u')).toBeNull();
    });
  });

  describe('withAccessTokenParam', () => {
    it('sets token and keeps other parameters', () => {
      expect(
        withAccessTokenParam(
          'http://h/proxy/ts/stream/u?output_format=hls',
          'tok'
        )
      ).toBe('http://h/proxy/ts/stream/u?output_format=hls&token=tok');
    });

    it('returns the URL unchanged without a token', () => {
      expect(withAccessTokenParam('http://h/x?a=1', null)).toBe(
        'http://h/x?a=1'
      );
    });
  });

  describe('buildLiveHlsConfig', () => {
    const config = buildLiveHlsConfig(() => null);

    it('sets the live playback options', () => {
      expect(config.backBufferLength).toBe(120);
      expect(config.lowLatencyMode).toBe(false);
      expect(config.liveSyncDurationCount).toBe(3);
    });

    it('bounds the entry timeout by the relay and by nginx', () => {
      const entry = config.manifestLoadPolicy.default;
      expect(entry.maxLoadTimeMs).toBeGreaterThan(
        HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_READY_WAIT_MS
      );
      expect(entry.maxLoadTimeMs).toBeLessThan(300_000);
      expect(entry.timeoutRetry).toBeNull();
    });

    it('bounds the playlist timeouts by the relay and by nginx', () => {
      const playlist = config.playlistLoadPolicy.default;
      for (const ms of [
        playlist.maxTimeToFirstByteMs,
        playlist.maxLoadTimeMs,
      ]) {
        expect(ms).toBeGreaterThan(HLS_RELAY_WAIT_MS);
        expect(ms).toBeLessThan(60_000);
      }
    });

    it('mirrors the relay bounds as literals', () => {
      expect(HLS_RELAY_WAIT_MS).toBe(43000);
      expect(HLS_RELAY_READY_WAIT_MS).toBe(58000);
      expect(HLS_RELAY_TUNE_BUDGET_MS).toBe(14100);
    });

    it('xhrSetup reads the access token on every request', () => {
      const getter = vi.fn().mockReturnValueOnce('a').mockReturnValueOnce('b');
      const { xhrSetup } = buildLiveHlsConfig(getter);
      const x1 = { setRequestHeader: vi.fn() };
      const x2 = { setRequestHeader: vi.fn() };
      xhrSetup(x1);
      xhrSetup(x2);
      expect(x1.setRequestHeader).toHaveBeenCalledWith(
        'Authorization',
        'Bearer a'
      );
      expect(x2.setRequestHeader).toHaveBeenCalledWith(
        'Authorization',
        'Bearer b'
      );

      const none = { setRequestHeader: vi.fn() };
      buildLiveHlsConfig(() => null).xhrSetup(none);
      expect(none.setRequestHeader).not.toHaveBeenCalled();
    });
  });

  describe('getHlsLivePlayerErrorMessage', () => {
    const rows = [
      [
        { channelStopped: true },
        'The channel stopped, or this idle session was ended.',
      ],
      [{ sessionEnded: true }, 'The playback session ended.'],
      [{ status: 401 }, 'You are not allowed to watch this channel.'],
      [{ status: 403 }, 'You are not allowed to watch this channel.'],
      [{ status: 404 }, 'Channel not found.'],
      [
        { status: 429 },
        'Stream limit reached. Close another stream and try again.',
      ],
      [{ status: 502 }, "The channel's source is unavailable."],
      [{ status: 503 }, 'The channel is not ready yet. Try again in a moment.'],
      [
        { details: 'manifestIncompatibleCodecsError' },
        "This channel's video or audio format can't be played in this browser.",
      ],
      [
        { details: 'bufferIncompatibleCodecsError' },
        "This channel's video or audio format can't be played in this browser.",
      ],
      [{ details: 'fragParsingError' }, 'Playback error: fragParsingError'],
      [{}, 'Playback error: unknown'],
    ];

    it.each(rows)('maps %j', (input, message) => {
      expect(getHlsLivePlayerErrorMessage(input)).toBe(message);
    });

    it('never names a browser', () => {
      for (const [input] of rows) {
        const message = getHlsLivePlayerErrorMessage(input);
        expect(message).not.toMatch(/chrome/i);
        expect(message).not.toMatch(/edge/i);
      }
    });
  });
});
