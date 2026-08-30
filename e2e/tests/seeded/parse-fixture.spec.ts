import { test, expect, parseM3u, parseXmltv, expectWellFormedXml } from '../../fixtures';

const PLAYLIST = [
  '#EXTM3U x-tvg-url="http://h:9191/output/epg" url-tvg="http://h:9191/output/epg"',
  '#EXTINF:-1 tvg-id="42" tvg-name="News, Live" tvg-logo="" tvg-chno="42" group-title="World",News, Live',
  'http://h:9191/proxy/ts/stream/2a5d0f5e-0000-4000-8000-000000000001',
  '#EXTINF:-1 tvg-id="43" tvg-name="Sport" tvg-logo="http://h/l.png" tvg-chno="43" tvc-guide-stationid="X1" group-title="World",Sport',
  'http://h:9191/proxy/ts/stream/2a5d0f5e-0000-4000-8000-000000000002',
  '',
].join('\n');

test('parseM3u reads the header attributes', () => {
  const playlist = parseM3u(PLAYLIST);
  expect(playlist.header['x-tvg-url']).toBe('http://h:9191/output/epg');
  expect(playlist.header['url-tvg']).toBe('http://h:9191/output/epg');
});

test('parseM3u pairs each EXTINF with the URL beneath it', () => {
  const playlist = parseM3u(PLAYLIST);
  expect(playlist.entries).toHaveLength(2);
  expect(playlist.entries[0].attributes['tvg-chno']).toBe('42');
  expect(playlist.entries[0].url).toBe(
    'http://h:9191/proxy/ts/stream/2a5d0f5e-0000-4000-8000-000000000001'
  );
  expect(playlist.entries[1].attributes['tvc-guide-stationid']).toBe('X1');
});

test('parseM3u keeps a comma inside the title', () => {
  // The title is everything after the comma that FOLLOWS the last quoted
  // attribute. A naive lastIndexOf(',') would return "Live" here, silently
  // truncating every channel whose name contains a comma.
  expect(parseM3u(PLAYLIST).entries[0].title).toBe('News, Live');
});

test('parseM3u rejects a body that is not a playlist', () => {
  expect(() => parseM3u('<html>nope</html>')).toThrow(/not an M3U playlist/);
});

test('parseM3u rejects an EXTINF with no URL beneath it', () => {
  expect(() =>
    parseM3u('#EXTM3U\n#EXTINF:-1 tvg-id="1",A\n#EXTINF:-1 tvg-id="2",B\nhttp://h/2')
  ).toThrow(/not followed by a URL/);
});

const GUIDE = [
  '<?xml version="1.0" encoding="UTF-8"?>',
  '<tv generator-info-name="Dispatcharr">',
  '  <channel id="42">',
  '    <display-name>News &amp; Weather</display-name>',
  '    <icon src="" />',
  '  </channel>',
  '  <programme start="20260829120000 +0000" stop="20260829160000 +0000" channel="42">',
  '    <title>Morning &lt;Show&gt;</title>',
  '    <desc>Words</desc>',
  '  </programme>',
  '</tv>',
].join('\n');

test('parseXmltv reads channels and decodes entities', () => {
  const guide = parseXmltv(GUIDE);
  expect(guide.channels).toHaveLength(1);
  expect(guide.channels[0].id).toBe('42');
  expect(guide.channels[0].displayNames).toEqual(['News & Weather']);
});

test('parseXmltv reads programmes with their channel and title', () => {
  const guide = parseXmltv(GUIDE);
  expect(guide.programmes).toHaveLength(1);
  expect(guide.programmes[0].channel).toBe('42');
  expect(guide.programmes[0].start).toBe('20260829120000 +0000');
  expect(guide.programmes[0].title).toBe('Morning <Show>');
});

test('expectWellFormedXml accepts valid XML', async ({ adminPage }) => {
  await expectWellFormedXml(adminPage, GUIDE);
});

test('expectWellFormedXml rejects malformed XML', async ({ adminPage }) => {
  // Not vacuous: a helper that passes on anything reads as coverage and is
  // worse than no helper. `<tv>` is never closed.
  await expect(expectWellFormedXml(adminPage, '<tv><channel id="1">')).rejects.toThrow();
});
