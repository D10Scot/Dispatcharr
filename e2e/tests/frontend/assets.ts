/**
 * A 1x1 transparent PNG, as bytes.
 *
 * In memory rather than on disk: `setInputFiles` accepts
 * `{ name, mimeType, buffer }`, so no temp file, no cleanup, and no binary
 * committed to the repository that a reader cannot inspect. The base64 below
 * is the canonical minimal PNG — an 8-byte signature, IHDR, a single IDAT and
 * IEND.
 */
export const TINY_PNG: Buffer = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk' +
    'YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64'
);
