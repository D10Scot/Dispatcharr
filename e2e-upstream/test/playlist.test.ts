import { describe, it, expect } from 'vitest';
import { ScenarioRegistry } from '../src/scenario.js';
import { renderPlaylist, PLAYLIST_CONTENT_TYPE } from '../src/playlist.js';

const ORIGIN = 'http://e2e-upstream:8080';

describe('renderPlaylist', () => {
  it('starts with the #EXTM3U header', () => {
    const scenario = new ScenarioRegistry().create({ channels: 1 });
    expect(renderPlaylist(scenario, ORIGIN).split('\n')[0]).toBe('#EXTM3U');
  });

  it('emits one EXTINF and one URL per channel, in order', () => {
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const lines = renderPlaylist(scenario, ORIGIN).trim().split('\n');

    // header + 2 channels * 2 lines
    expect(lines).toHaveLength(5);
    expect(lines[1]).toContain('tvg-id="fake-1.e2e"');
    expect(lines[2]).toBe(`${ORIGIN}/s/${scenario.id}/stream/1.ts`);
    expect(lines[3]).toContain('tvg-id="fake-2.e2e"');
    expect(lines[4]).toBe(`${ORIGIN}/s/${scenario.id}/stream/2.ts`);
  });

  it('carries the channel name after the comma, which is what Dispatcharr imports as the name', () => {
    const scenario = new ScenarioRegistry().create({
      channels: [{ id: 1, name: 'Named Channel', tvgId: 'named.e2e', logo: null }],
    });
    expect(renderPlaylist(scenario, ORIGIN)).toContain(',Named Channel');
  });

  it('omits tvg-logo entirely when a channel has no logo', () => {
    const scenario = new ScenarioRegistry().create({
      channels: [{ id: 1, name: 'No Logo', tvgId: 'nologo.e2e', logo: null }],
    });
    // An empty tvg-logo="" is not the same as an absent one, and G3 will
    // test the absent case. Emitting an empty attribute would make that
    // test unwritable.
    expect(renderPlaylist(scenario, ORIGIN)).not.toContain('tvg-logo');
  });

  it('appends credentials to stream URLs when the scenario declares them', () => {
    const scenario = new ScenarioRegistry().create({
      channels: 1,
      username: 'user@example.com',
      password: 'p a s s',
    });
    const lines = renderPlaylist(scenario, ORIGIN).trim().split('\n');
    const streamLine = lines[2];

    // The product sends no credentials of its own on a standard M3U fetch,
    // so anything the provider wants to validate has to be in the URL.
    // Asserted on the stream URL line specifically, not the whole document,
    // so this can't pass because the query landed somewhere unrelated (e.g.
    // an EXTINF attribute).
    expect(streamLine).toBe(
      `${ORIGIN}/s/${scenario.id}/stream/1.ts?username=user%40example.com&password=p%20a%20s%20s`,
    );
  });

  it('passes an unescaped double quote in a channel name through, since M3U has no standard escape for it and real providers emit it that way', () => {
    // Regression guard: without this test, someone will later "harden" the
    // renderer by escaping quotes and silently remove a case G3 needs.
    const scenario = new ScenarioRegistry().create({
      channels: [{ id: 1, name: 'The "Best" Channel', tvgId: 'best.e2e', logo: null }],
    });
    expect(renderPlaylist(scenario, ORIGIN)).toContain('tvg-name="The "Best" Channel"');
  });

  it('declares the content type the product will accept', () => {
    // apps/m3u/tasks.py rejects "non-text content" outright, so this
    // constant is load-bearing rather than cosmetic.
    expect(PLAYLIST_CONTENT_TYPE).toBe('application/vnd.apple.mpegurl');
  });
});
