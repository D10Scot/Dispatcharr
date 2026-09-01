import { test, expect } from '../../fixtures';
import { StreamClient } from '../../fixtures';
import type { VodCategory } from '../../fixtures';

test('readBytes returns exactly the requested byte count', async ({ upstream, seed, streamClient }) => {
  test.setTimeout(60_000);
  // The provider's own control origin, not the product: this asserts the
  // fixture, not Dispatcharr. A scenario with one movie is the cheapest way
  // to get a finite body with a known length.
  //
  // Generated names even though nothing here is ingested: D3 is a global
  // constraint, and a one-line exemption costs a reader more than obeying it.
  const prefix = seed.generatedName('readbytes');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-u`,
    password: `${prefix}-p`,
    vod: [{ id: 1, name: `${prefix}-movie`, year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null }],
    series: 0,
  });
  const url = upstream.toControl(`${scenario.internal}/movie/${prefix}-u/${prefix}-p/1.mp4`);
  await streamClient.open(url);
  const head = await streamClient.readBytes(8);
  expect(head.byteLength).toBe(8);
  // `ftyp` is the first box of every MP4 — proves the bytes are the asset's
  // and start at offset zero, not that eight arbitrary bytes arrived.
  expect(head.subarray(4, 8).toString('ascii')).toBe('ftyp');

  // A second call must consume, not replay: it has to return the NEXT eight
  // bytes of the stream, not the same window again. Proved against an
  // independent Range request for that exact offset — not against
  // knowledge of MP4 structure, which the second eight bytes have none of —
  // so a `readBytes` that never advances `bufferedBytes` (still returning
  // the right count, since the first chunk is still fully buffered) fails
  // this specifically rather than passing by construction.
  const second = await streamClient.readBytes(8);
  const referenceRes = await fetch(url, { headers: { Range: 'bytes=8-15' } });
  const reference = Buffer.from(await referenceRes.arrayBuffer());
  expect(second.equals(reference)).toBe(true);
});

test('readBytes throws if the stream ends before count bytes arrive', async ({ upstream, seed }) => {
  test.setTimeout(60_000);
  // Own scenario and own StreamClient: the other test's connection must stay
  // open for its own assertions, so ending a stream early needs a second one.
  const prefix = seed.generatedName('readbytes-short');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-u`,
    password: `${prefix}-p`,
    vod: [{ id: 1, name: `${prefix}-movie`, year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null }],
    series: 0,
  });
  const url = upstream.toControl(`${scenario.internal}/movie/${prefix}-u/${prefix}-p/1.mp4`);

  // A Range request for exactly 4 bytes gives a body whose end readBytes
  // will hit deterministically — no fault or timing dependency needed.
  const client = new StreamClient('');
  await client.open(url, { headers: { Range: 'bytes=0-3' } });
  await expect(client.readBytes(1_000)).rejects.toThrow(
    /stream ended after 4 bytes, wanted 1000/
  );
  await client.close();
});

test('the VOD category list is an unpaginated array', async ({ upstream, seed, waitFor }) => {
  test.setTimeout(60_000);
  // Not just "an array": locates a category THIS test ingested and checks
  // its fields, so swapping the URL for any other array-returning endpoint
  // (or an accidentally-empty result) fails rather than passing by luck.
  const prefix = seed.generatedName('vodcat');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-u`,
    password: `${prefix}-p`,
    vodCategories: [{ id: 1, name: `${prefix}-category` }],
    vod: [{ id: 1, name: `${prefix}-movie`, year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null }],
    series: 0,
  });
  const account = await seed.xcAccount(scenario, { enable_vod: true });
  await waitFor.m3uRefreshComplete(account.id);

  // Categories are created by refresh_categories, part of the async VOD
  // refresh fired *after* the M3U refresh above reaches a terminal status —
  // so the category is not guaranteed to exist yet and must be polled for,
  // same as vod-catalogue-ingest.spec.ts polls for the movie row.
  const categoryName = `${prefix}-category`;
  const categories = await waitFor.resource<VodCategory[]>(
    '/api/vod/categories/',
    (body) => Array.isArray(body) && body.some((c) => c.name === categoryName),
    { description: `the VOD category named ${categoryName} to be ingested`, timeoutMs: 120_000 }
  );
  // Pins the shape VodCategory[] depends on: a bare array, not { results }.
  // VODCategoryViewSet declares no pagination_class and settings.py sets no
  // DEFAULT_PAGINATION_CLASS. If this ever starts returning an object, every
  // `find` in G9 silently stops finding anything.
  expect(Array.isArray(categories)).toBe(true);

  const category = categories.find((c) => c.name === categoryName)!;
  expect(typeof category.id).toBe('number');
  expect(category.category_type).toBe('movie');
  expect(
    category.m3u_accounts.some((rel) => rel.m3u_account === account.id && rel.category === category.id)
  ).toBe(true);
});
