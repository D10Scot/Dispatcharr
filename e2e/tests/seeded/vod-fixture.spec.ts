import { test, expect } from '../../fixtures';
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
  await streamClient.open(
    upstream.toControl(`${scenario.internal}/movie/${prefix}-u/${prefix}-p/1.mp4`)
  );
  const head = await streamClient.readBytes(8);
  expect(head.byteLength).toBe(8);
  // `ftyp` is the first box of every MP4 — proves the bytes are the asset's
  // and start at offset zero, not that eight arbitrary bytes arrived.
  expect(head.subarray(4, 8).toString('ascii')).toBe('ftyp');
});

test('the VOD category list is an unpaginated array', async ({ api }) => {
  test.setTimeout(60_000);
  // Pins the shape VodCategory[] depends on: a bare array, not { results }.
  // VODCategoryViewSet declares no pagination_class and settings.py sets no
  // DEFAULT_PAGINATION_CLASS. If this ever starts returning an object, every
  // `find` in G9 silently stops finding anything.
  const body = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'vod categories');
  expect(Array.isArray(body)).toBe(true);
});
