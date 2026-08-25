import { describe, it, expect } from 'vitest';
import { ScenarioRegistry } from '../src/scenario.js';
import { renderXmltv, XMLTV_CONTENT_TYPE } from '../src/xmltv.js';

const NOW = new Date('2026-08-25T12:34:56Z');

describe('renderXmltv', () => {
  it('declares one <channel> per scenario channel, keyed by tvg-id', () => {
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const xml = renderXmltv(scenario, NOW);

    expect(xml).toContain('<channel id="fake-1.e2e">');
    expect(xml).toContain('<channel id="fake-2.e2e">');
  });

  it('emits programmes in XMLTV timestamp format', () => {
    const scenario = new ScenarioRegistry().create({ channels: 1 });
    // YYYYMMDDHHMMSS +0000 — anything else and the EPG parser drops the row
    // silently, which would look like "EPG import is broken".
    expect(renderXmltv(scenario, NOW)).toMatch(/start="\d{14} \+0000"/);
  });

  it('covers a window starting before now, so a programme is always in progress', () => {
    const scenario = new ScenarioRegistry().create({ channels: 1 });
    const xml = renderXmltv(scenario, NOW);
    const starts = [...xml.matchAll(/start="(\d{14}) \+0000"/g)].map((m) => m[1]);

    // A guide with nothing airing right now makes "is the channel showing
    // the right programme" untestable.
    expect(starts[0] < '20260825123456').toBe(true);
  });

  it('produces programmes that abut without gaps or overlaps', () => {
    const scenario = new ScenarioRegistry().create({ channels: 1 });
    const xml = renderXmltv(scenario, NOW);
    const stops = [...xml.matchAll(/stop="(\d{14}) \+0000"/g)].map((m) => m[1]);
    const starts = [...xml.matchAll(/start="(\d{14}) \+0000"/g)].map((m) => m[1]);

    expect(starts.slice(1)).toEqual(stops.slice(0, -1));
  });

  it('escapes XML metacharacters in channel names', () => {
    const scenario = new ScenarioRegistry().create({
      channels: [{ id: 1, name: 'Rock & Roll <live>', tvgId: 'rock.e2e', logo: null }],
    });
    const xml = renderXmltv(scenario, NOW);

    expect(xml).toContain('Rock &amp; Roll &lt;live&gt;');
    expect(xml).not.toContain('Rock & Roll <live>');
  });

  it('declares the XML content type', () => {
    expect(XMLTV_CONTENT_TYPE).toBe('application/xml');
  });
});
