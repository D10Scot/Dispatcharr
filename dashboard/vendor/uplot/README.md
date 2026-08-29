# Vendored: uPlot

- Version: `1.6.32`
- Source: https://github.com/leeoniya/uPlot (published to npm as `uplot`)
- Fetched from: https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.iife.min.js
  and https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.min.css
- npm tarball shasum (per `npm view uplot dist.shasum` at time of vendoring):
  `c800a63b432bad692d6d746f44f0882aa73a49ae`

## File hashes (sha256)

```
19c8d4c6ad88929a79f4ae49d6f7161566dfd0ba3d15cc495e974f787eb78f1f  uPlot.iife.min.js
df630c6a8d6f8eeaff264b50f73ce5b114f646ffd9a0bb74f049b0a00135fa04  uPlot.min.css
```

Verify with `shasum -a 256 dashboard/vendor/uplot/*`.

## Why vendored, not CDN

Repo supply-chain rules forbid loading unpinned remote content at runtime.
uPlot is dependency-free and tiny (~50 KB minified JS + ~2 KB CSS), so it is
checked in directly rather than fetched from a CDN or built from source. To
upgrade: download the new `dist/uPlot.iife.min.js` and `dist/uPlot.min.css`
for the target version, recompute the sha256 hashes above, and update the
version/hashes in this file in the same commit.

License: MIT (see https://github.com/leeoniya/uPlot/blob/master/LICENSE.txt).
