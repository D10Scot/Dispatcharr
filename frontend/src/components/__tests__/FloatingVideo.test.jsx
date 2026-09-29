import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import FloatingVideo from '../FloatingVideo';
import {
  HLS_LEAVE_WAIT_MS,
  HLS_RELAY_TUNE_BUDGET_MS,
  HLS_RELAY_WAIT_MS,
} from '../../utils/components/FloatingVideoUtils.js';
import useVideoStore from '../../store/useVideoStore';

// Mock the video store
vi.mock('../../store/useVideoStore');

// Mock mpegts.js
vi.mock('mpegts.js', () => ({
  default: {
    createPlayer: vi.fn(),
    getFeatureList: vi.fn(),
    Events: {
      LOADING_COMPLETE: 'loading_complete',
      METADATA_ARRIVED: 'metadata_arrived',
      ERROR: 'error',
      MEDIA_INFO: 'media_info',
    },
  },
}));

// Every hls.js instance the component constructs, each with its own spies and
// the handlers it registered; fireHls calls those handlers.
let hlsInstances = [];
const fireHls = (instance, event, data) => {
  for (const handler of instance.handlers[event] ?? []) {
    handler(event, data);
  }
};

let capturedHlsConfig = null;
let forceHlsInitError = false;

vi.mock('hls.js', () => ({
  default: class MockHls {
    static isSupported = vi.fn(() => true);

    static Events = {
      ERROR: 'error',
      MEDIA_ATTACHED: 'media_attached',
      MANIFEST_LOADED: 'manifestLoaded',
      MANIFEST_PARSED: 'manifestParsed',
    };

    static ErrorTypes = {
      NETWORK_ERROR: 'networkError',
      MEDIA_ERROR: 'mediaError',
    };

    constructor(config) {
      if (forceHlsInitError) {
        throw new Error('Illegal hls.js config');
      }
      capturedHlsConfig = config;
      this.attachMedia = vi.fn();
      this.loadSource = vi.fn();
      this.destroy = vi.fn();
      this.startLoad = vi.fn();
      this.recoverMediaError = vi.fn();
      this.handlers = {};
      this.on = vi.fn((event, handler) => {
        (this.handlers[event] ??= []).push(handler);
      });
      hlsInstances.push(this);
    }
  },
}));

vi.mock('../../api', () => ({
  default: {
    leaveHlsSession: vi.fn(() => Promise.resolve(true)),
    getAuthToken: vi.fn(() => Promise.resolve('fresh-token')),
  },
}));

vi.mock('../../store/auth', () => ({
  default: {
    getState: vi.fn(() => ({ accessToken: 'test-token' })),
  },
}));

// Import the mocked module after mocking
const mpegts = (await import('mpegts.js')).default;
const Hls = (await import('hls.js')).default;
const API = (await import('../../api')).default;

// Mock react-draggable
vi.mock('react-draggable', () => ({
  default: ({ children, nodeRef }) => <div ref={nodeRef}>{children}</div>,
}));

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    CloseButton: ({ onClick, onTouchEnd }) => (
      <button
        data-testid="close-button"
        onClick={onClick}
        onTouchEnd={onTouchEnd}
      >
        Close
      </button>
    ),
    Flex: ({ children, ...props }) => <div {...props}>{children}</div>,
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Loader: () => <div data-testid="loader">Loading...</div>,
    Text: ({ children, ...props }) => <div {...props}>{children}</div>,
  };
});

describe('FloatingVideo', () => {
  const mockHideVideo = vi.fn();
  let mockPlayer;

  beforeEach(async () => {
    vi.clearAllMocks();
    capturedHlsConfig = null;
    hlsInstances = [];
    forceHlsInitError = false;
    Hls.isSupported.mockReturnValue(true);

    // Mock HTMLVideoElement methods
    HTMLVideoElement.prototype.load = vi.fn();
    HTMLVideoElement.prototype.play = vi.fn(() => Promise.resolve());
    HTMLVideoElement.prototype.pause = vi.fn();

    mockPlayer = {
      attachMediaElement: vi.fn(),
      load: vi.fn(),
      play: vi.fn(() => Promise.resolve()),
      pause: vi.fn(),
      destroy: vi.fn(),
      on: vi.fn(),
    };

    mpegts.createPlayer.mockReturnValue(mockPlayer);
    mpegts.getFeatureList.mockReturnValue({ mseLivePlayback: true });

    useVideoStore.mockImplementation((selector) => {
      const state = {
        isVisible: false,
        streamUrl: null,
        contentType: 'live',
        metadata: null,
        hideVideo: mockHideVideo,
      };
      return selector ? selector(state) : state;
    });
  });

  describe('Visibility', () => {
    it('should not render when isVisible is false', () => {
      const { container } = render(<FloatingVideo />);
      expect(container.firstChild).toBeNull();
    });

    it('should not render when streamUrl is null', () => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: null,
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      const { container } = render(<FloatingVideo />);
      expect(container.firstChild).toBeNull();
    });

    it('should render when isVisible is true and streamUrl is provided', () => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      render(<FloatingVideo />);
      expect(screen.getByTestId('close-button')).toBeInTheDocument();
    });
  });

  describe('Live Stream Player', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should initialize mpegts player for live streams', () => {
      render(<FloatingVideo />);

      expect(mpegts.createPlayer).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'mpegts',
          url: 'http://example.com/stream.ts',
          isLive: true,
        }),
        expect.objectContaining({
          enableWorker: true,
          enableStashBuffer: false,
        })
      );
    });

    it('should show loading state initially', () => {
      render(<FloatingVideo />);
      expect(screen.getByTestId('loader')).toBeInTheDocument();
      expect(screen.getByText('Loading stream...')).toBeInTheDocument();
    });

    it('should attach player to video element', () => {
      render(<FloatingVideo />);
      expect(mockPlayer.attachMediaElement).toHaveBeenCalled();
    });

    it('should handle player errors', async () => {
      render(<FloatingVideo />);

      const errorCallback = mockPlayer.on.mock.calls.find(
        (call) => call[0] === mpegts.Events.ERROR
      )?.[1];

      errorCallback('MediaError', 'AC3 codec not supported');

      await screen.findByText(/Audio codec not supported/i);
    });

    it('should handle unsupported browser', () => {
      mpegts.getFeatureList.mockReturnValue({
        mseLivePlayback: false,
      });

      render(<FloatingVideo />);

      expect(
        screen.getByText(/browser doesn't support live video streaming/i)
      ).toBeInTheDocument();
    });

    it('should play video on MEDIA_INFO event', async () => {
      render(<FloatingVideo />);

      const mediaInfoCallback = mockPlayer.on.mock.calls.find(
        (call) => call[0] === mpegts.Events.MEDIA_INFO
      )?.[1];

      await mediaInfoCallback();

      expect(mockPlayer.play).toHaveBeenCalled();
    });
  });

  describe('VOD Player', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/video.mp4',
            contentType: 'vod',
            metadata: {
              name: 'Test Movie',
              year: '2024',
              logo: { url: 'http://example.com/poster.jpg' },
            },
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should use native video player for VOD', () => {
      render(<FloatingVideo />);
      expect(mpegts.createPlayer).not.toHaveBeenCalled();
    });

    it('should set video source for VOD', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');
      expect(video).toBeInTheDocument();
      expect(video.src).toBe('http://example.com/video.mp4');
      expect(video.poster).toBe('http://example.com/poster.jpg');
    });

    it('should disable live-edge sync for in-progress recording HLS', () => {
      useVideoStore.mockImplementation((selector) => {
        const state = {
          isVisible: true,
          streamUrl:
            'http://example.com/api/channels/recordings/1/hls/index.m3u8',
          contentType: 'vod',
          metadata: { name: 'News Recording' },
          hideVideo: mockHideVideo,
        };
        return selector ? selector(state) : state;
      });

      Hls.isSupported.mockReturnValue(true);

      render(<FloatingVideo />);

      expect(capturedHlsConfig).toEqual(
        expect.objectContaining({
          startPosition: 0,
        })
      );
      expect(capturedHlsConfig).not.toHaveProperty(
        'liveMaxLatencyDurationCount'
      );
      expect(capturedHlsConfig).not.toHaveProperty('liveSyncDurationCount');
    });

    it('shows an in-player error when hls.js config is invalid', () => {
      useVideoStore.mockImplementation((selector) => {
        const state = {
          isVisible: true,
          streamUrl:
            'http://example.com/api/channels/recordings/1/hls/index.m3u8',
          contentType: 'vod',
          metadata: { name: 'News Recording' },
          hideVideo: mockHideVideo,
        };
        return selector ? selector(state) : state;
      });

      Hls.isSupported.mockReturnValue(true);
      forceHlsInitError = true;

      render(<FloatingVideo />);

      expect(
        screen.getByText(/HLS initialization error: Illegal hls.js config/i)
      ).toBeInTheDocument();
    });

    it('should show metadata overlay', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      // Simulate video loaded and canplay events to clear loading state and show overlay
      fireEvent.loadedData(video);
      fireEvent.canPlay(video);

      expect(screen.getAllByText('Test Movie').length).toBeGreaterThanOrEqual(
        1
      );
      expect(screen.getByText('2024')).toBeInTheDocument();
    });

    it('should hide overlay after 4 seconds', () => {
      vi.useFakeTimers();

      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      fireEvent.loadedData(video);
      fireEvent.canPlay(video);

      expect(screen.getAllByText('Test Movie').length).toBeGreaterThanOrEqual(
        1
      );

      vi.advanceTimersByTime(4000);

      waitFor(() => {
        // After overlay hides, only the header title remains
        expect(screen.getAllByText('Test Movie').length).toBe(1);
      });

      vi.useRealTimers();
    });

    it('should show overlay on mouse enter', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      fireEvent.loadedData(video);
      fireEvent.canPlay(video);

      const videoContainer = video.parentElement;

      fireEvent.mouseEnter(videoContainer);

      expect(screen.getAllByText('Test Movie').length).toBeGreaterThanOrEqual(
        1
      );
    });

    it('should hide overlay on mouse leave', () => {
      vi.useFakeTimers();

      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      fireEvent.loadedData(video);
      fireEvent.canPlay(video);

      const videoContainer = video.parentElement;

      fireEvent.mouseEnter(videoContainer);
      fireEvent.mouseLeave(videoContainer);

      vi.advanceTimersByTime(4000);

      waitFor(() => {
        // After overlay hides, only the header title remains
        expect(screen.getAllByText('Test Movie').length).toBe(1);
      });

      vi.useRealTimers();
    });
  });

  describe('Close functionality', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should call hideVideo when close button is clicked', () => {
      vi.useFakeTimers();

      render(<FloatingVideo />);

      fireEvent.click(screen.getByTestId('close-button'));

      vi.advanceTimersByTime(50);

      waitFor(() => {
        expect(mockHideVideo).toHaveBeenCalled();
        expect(mockPlayer.destroy).toHaveBeenCalled();
      });

      vi.useRealTimers();
    });
  });

  describe('Error handling', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/video.mp4',
            contentType: 'vod',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should display video error messages', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      Object.defineProperty(video, 'error', {
        value: { code: 3, message: 'MEDIA_ERR_DECODE' },
        writable: true,
      });

      fireEvent.error(video);

      expect(screen.getByText(/MEDIA_ERR_DECODE/i)).toBeInTheDocument();
    });

    it('should handle network errors', () => {
      const { container } = render(<FloatingVideo />);
      const video = container.querySelector('video');

      Object.defineProperty(video, 'error', {
        value: { code: 2, message: 'MEDIA_ERR_NETWORK' },
        writable: true,
      });

      fireEvent.error(video);

      expect(screen.getByText(/MEDIA_ERR_NETWORK/i)).toBeInTheDocument();
    });
  });

  describe('Player cleanup', () => {
    it('should cleanup player on unmount', () => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      const { unmount } = render(<FloatingVideo />);

      unmount();

      expect(mockPlayer.destroy).toHaveBeenCalled();
    });

    it('should cleanup player when streamUrl changes', () => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream1.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      const { rerender } = render(<FloatingVideo />);

      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream2.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });

      rerender(<FloatingVideo />);

      expect(mockPlayer.destroy).toHaveBeenCalled();
    });
  });

  describe('Resize functionality', () => {
    beforeEach(() => {
      useVideoStore.mockImplementation((selector) => {
        {
          const state = {
            isVisible: true,
            streamUrl: 'http://example.com/stream.ts',
            contentType: 'live',
            metadata: null,
            hideVideo: mockHideVideo,
          };
          return selector ? selector(state) : state;
        }
      });
    });

    it('should render resize handles', () => {
      const { container } = render(<FloatingVideo />);
      const handles = container.querySelectorAll(
        '[class*="floating-video-no-drag"]'
      );

      // Should have 4 resize handles plus video element
      expect(handles.length).toBeGreaterThanOrEqual(4);
    });
  });

  describe('Live channel over HLS', () => {
    const T = 'v1.' + 'A'.repeat(22) + '.' + 'B'.repeat(43);
    const T2 = 'v1.' + 'C'.repeat(22) + '.' + 'D'.repeat(43);
    const CH1 = '/proxy/ts/stream/ch-1?output_format=hls';
    const CH1_ABS = 'http://localhost:3000' + CH1;
    const ABS = (token, rest) => `http://localhost:3000/hls/${token}${rest}`;
    const manifest = (token = T) => ({
      levels: [{ url: ABS(token, '/video.m3u8') }],
      audioTracks: [],
    });
    const sessionEnded = 'The playback session ended.';

    const setStream = (streamUrl) =>
      useVideoStore.mockImplementation((selector) => {
        const state = {
          isVisible: true,
          streamUrl,
          contentType: 'live',
          metadata: null,
          hideVideo: mockHideVideo,
        };
        return selector ? selector(state) : state;
      });
    const flush = () => act(async () => {});
    const fire = (instance, event, data) =>
      act(async () => fireHls(instance, event, data));
    const renderHls = async (streamUrl = CH1) => {
      setStream(streamUrl);
      const utils = render(<FloatingVideo />);
      await flush();
      return utils;
    };
    const closePlayer = () =>
      fireEvent.click(screen.getByTestId('close-button'));
    let originalCanPlayType;

    beforeEach(() => {
      originalCanPlayType = HTMLVideoElement.prototype.canPlayType;
      API.leaveHlsSession.mockReset();
      API.leaveHlsSession.mockResolvedValue(true);
      API.getAuthToken.mockClear();
    });

    afterEach(() => {
      HTMLVideoElement.prototype.canPlayType = originalCanPlayType;
      vi.useRealTimers();
      vi.restoreAllMocks();
    });

    it('plays a channel HLS URL through hls.js, not mpegts.js', async () => {
      await renderHls();

      expect(hlsInstances).toHaveLength(1);
      expect(mpegts.createPlayer).not.toHaveBeenCalled();
      await fire(hlsInstances[0], 'media_attached');
      expect(hlsInstances[0].loadSource).toHaveBeenCalledWith(CH1_ABS);
    });

    it('uses the live HLS config', async () => {
      await renderHls();

      expect(capturedHlsConfig.backBufferLength).toBe(120);
      expect(
        capturedHlsConfig.manifestLoadPolicy?.default?.maxLoadTimeMs ?? 0,
        'the entry timeout must cover the relay tune budget plus its ready wait'
      ).toBeGreaterThan(HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS);
    });

    it('closing the player destroys hls.js, then leaves the session', async () => {
      await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest());

      closePlayer();

      expect(API.leaveHlsSession).toHaveBeenCalledTimes(1);
      expect(API.leaveHlsSession.mock.calls[0]).toEqual([ABS(T, '')]);
      expect(hlsInstances[0].destroy.mock.invocationCallOrder[0]).toBeLessThan(
        API.leaveHlsSession.mock.invocationCallOrder[0]
      );
    });

    it('sends no leave before the manifest names a session', async () => {
      await renderHls();

      closePlayer();

      expect(API.leaveHlsSession).not.toHaveBeenCalled();
    });

    it('a switch waits for the previous leave before the next entry', async () => {
      const { rerender } = await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest());
      let resolveLeave;
      API.leaveHlsSession.mockReturnValueOnce(
        new Promise((resolve) => {
          resolveLeave = resolve;
        })
      );

      setStream('/proxy/ts/stream/ch-2?output_format=hls');
      rerender(<FloatingVideo />);
      await flush();
      expect(hlsInstances).toHaveLength(1);

      resolveLeave(true);
      await flush();
      expect(hlsInstances).toHaveLength(2);
      await fire(hlsInstances[1], 'media_attached');
      expect(hlsInstances[1].loadSource).toHaveBeenCalledWith(
        'http://localhost:3000/proxy/ts/stream/ch-2?output_format=hls'
      );
    });

    it('a leave that never answers delays the next entry by at most HLS_LEAVE_WAIT_MS', async () => {
      const { rerender } = await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest());
      API.leaveHlsSession.mockReturnValueOnce(new Promise(() => {}));
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });

      setStream('/proxy/ts/stream/ch-2?output_format=hls');
      rerender(<FloatingVideo />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(HLS_LEAVE_WAIT_MS - 1);
      });
      expect(hlsInstances).toHaveLength(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(hlsInstances).toHaveLength(2);
    });

    it('prefers hls.js over native HLS', async () => {
      HTMLVideoElement.prototype.canPlayType = vi.fn(() => 'maybe');
      Hls.isSupported.mockReturnValue(true);
      const { container } = await renderHls();

      expect(hlsInstances).toHaveLength(1);
      expect(container.querySelector('video').src).not.toContain(
        'output_format=hls'
      );
    });

    it('pagehide leaves with keepalive, once', async () => {
      await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest());

      window.dispatchEvent(new Event('pagehide'));
      expect(API.leaveHlsSession).toHaveBeenCalledTimes(1);
      expect(API.leaveHlsSession).toHaveBeenCalledWith(ABS(T, ''), {
        keepalive: true,
      });

      closePlayer();
      expect(API.leaveHlsSession).toHaveBeenCalledTimes(1);
    });

    const forbidden = (url, code = 403) => ({
      type: 'networkError',
      details: 'levelLoadError',
      fatal: false,
      response: { code },
      url,
    });

    it('a 403 from /hls/ re-enters once, then shows that the session ended', async () => {
      await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest());

      // Disarmed and destroyed synchronously, before any flush.
      act(() => {
        fireHls(hlsInstances[0], 'error', forbidden(ABS(T, '/video.m3u8')));
      });
      expect(hlsInstances[0].destroy).toHaveBeenCalled();
      await flush();

      expect(hlsInstances).toHaveLength(2);
      await fire(hlsInstances[1], 'media_attached');
      expect(hlsInstances[1].loadSource).toHaveBeenCalledWith(CH1_ABS);
      expect(API.getAuthToken).toHaveBeenCalledTimes(2);
      expect(API.getAuthToken.mock.invocationCallOrder[1]).toBeLessThan(
        hlsInstances[1].attachMedia.mock.invocationCallOrder[0]
      );

      await fire(hlsInstances[1], 'error', forbidden(ABS(T, '/video.m3u8')));
      await flush();
      expect(hlsInstances).toHaveLength(2);
      expect(screen.getByText(sessionEnded)).toBeInTheDocument();
    });

    it('two 403s from one expired session re-enter exactly once', async () => {
      await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest());

      act(() => {
        fireHls(hlsInstances[0], 'error', forbidden(ABS(T, '/video.m3u8')));
        fireHls(hlsInstances[0], 'error', {
          ...forbidden(ABS(T, '/aac.m3u8')),
          details: 'audioTrackLoadError',
        });
      });
      await flush();

      expect(hlsInstances).toHaveLength(2);
      expect(screen.queryByText(sessionEnded)).not.toBeInTheDocument();
    });

    it('after a re-entry, closing leaves the new session', async () => {
      const addSpy = vi.spyOn(window, 'addEventListener');
      const removeSpy = vi.spyOn(window, 'removeEventListener');
      await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest(T));
      await fire(hlsInstances[0], 'error', forbidden(ABS(T, '/video.m3u8')));
      await flush();
      await fire(hlsInstances[1], 'manifestLoaded', manifest(T2));

      closePlayer();

      expect(API.leaveHlsSession).toHaveBeenCalledTimes(1);
      expect(API.leaveHlsSession).toHaveBeenCalledWith(ABS(T2, ''));
      // Structural: one pagehide listener for the whole player, removed once
      // by the very reference it was added with.
      const added = addSpy.mock.calls.filter((c) => c[0] === 'pagehide');
      const removed = removeSpy.mock.calls.filter((c) => c[0] === 'pagehide');
      expect(added).toHaveLength(1);
      expect(removed).toHaveLength(1);
      expect(removed[0][1]).toBe(added[0][1]);
    });

    it('a close during the re-entry builds no new instance', async () => {
      await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest());

      act(() => {
        fireHls(hlsInstances[0], 'error', forbidden(ABS(T, '/video.m3u8')));
      });
      closePlayer();
      await flush();

      expect(hlsInstances).toHaveLength(1);
      expect(hlsInstances[0].destroy).toHaveBeenCalled();
      expect(API.leaveHlsSession).not.toHaveBeenCalled();
    });

    it('a 403 on a segment re-enters too', async () => {
      await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest());

      act(() => {
        fireHls(hlsInstances[0], 'error', {
          type: 'networkError',
          details: 'fragLoadError',
          fatal: false,
          response: { code: 403, url: ABS(T, '/aac/12.m4s') },
          frag: { url: ABS(T, '/aac/12.m4s') },
        });
      });
      await flush();

      expect(hlsInstances).toHaveLength(2);
    });

    it('a 410 from /hls/ is not re-entered', async () => {
      await renderHls();
      await fire(hlsInstances[0], 'manifestLoaded', manifest());

      await fire(
        hlsInstances[0],
        'error',
        forbidden(ABS(T, '/video.m3u8'), 410)
      );
      await flush();

      expect(hlsInstances).toHaveLength(1);
      expect(
        screen.getByText('The channel stopped, or this idle session was ended.')
      ).toBeInTheDocument();
    });

    it('a manifest refusal shows its message and does not recover', async () => {
      await renderHls();

      await fire(hlsInstances[0], 'error', {
        type: 'networkError',
        details: 'manifestLoadError',
        fatal: true,
        response: { code: 429 },
        url: CH1_ABS,
      });

      expect(hlsInstances[0].startLoad).not.toHaveBeenCalled();
      expect(
        screen.getByText(
          'Stream limit reached. Close another stream and try again.'
        )
      ).toBeInTheDocument();
    });

    it('falls back to native HLS with the access token in the query', async () => {
      Hls.isSupported.mockReturnValue(false);
      HTMLVideoElement.prototype.canPlayType = vi.fn(() => 'maybe');
      const { container } = await renderHls();

      expect(hlsInstances).toHaveLength(0);
      expect(container.querySelector('video').src).toBe(
        'http://localhost:3000/proxy/ts/stream/ch-1?output_format=hls&token=test-token'
      );
    });

    it('says so when neither exists', async () => {
      Hls.isSupported.mockReturnValue(false);
      HTMLVideoElement.prototype.canPlayType = vi.fn(() => '');
      await renderHls();

      expect(
        screen.getByText("This browser can't play live channels.")
      ).toBeInTheDocument();
    });

    it('switching leaves no video-element listener behind', async () => {
      const addSpy = vi.spyOn(HTMLVideoElement.prototype, 'addEventListener');
      const removeSpy = vi.spyOn(
        HTMLVideoElement.prototype,
        'removeEventListener'
      );
      // React binds its own media-event listeners on <video> at mount (bound
      // functions, "[native code]"); only the player's are plain functions.
      const isPlayerListener = (fn) =>
        !/\[native code\]/.test(Function.prototype.toString.call(fn));
      const listeners = (spy, event) =>
        spy.mock.calls
          .filter((c) => c[0] === event && isPlayerListener(c[1]))
          .map((c) => c[1]);
      const zapThrough = async (event) => {
        const { rerender, unmount } = await renderHls(
          '/proxy/ts/stream/ch-1?output_format=hls'
        );
        for (const n of [2, 3, 4]) {
          setStream(`/proxy/ts/stream/ch-${n}?output_format=hls`);
          rerender(<FloatingVideo />);
          await flush();
        }
        const added = listeners(addSpy, event);
        const removed = listeners(removeSpy, event);
        const live = added.filter((fn) => !removed.includes(fn));
        expect(added.length).toBeGreaterThanOrEqual(4);
        expect(live).toHaveLength(1);
        expect(live[0]).toBe(added[added.length - 1]);
        unmount();
      };

      await zapThrough('playing');

      addSpy.mockClear();
      removeSpy.mockClear();
      Hls.isSupported.mockReturnValue(false);
      HTMLVideoElement.prototype.canPlayType = vi.fn(() => 'maybe');
      await zapThrough('canplay');
    });
  });
});
