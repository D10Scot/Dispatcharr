// frontend/src/utils/securePassword.js
const ALPHABET =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
// 248 = 4 * 62: the largest multiple of the alphabet size below 256. A byte
// at or above it is discarded, so every character is equally likely.
const LIMIT = 256 - (256 % ALPHABET.length);

export function generateSecurePassword(length = 20) {
  let out = '';
  const buf = new Uint8Array(length * 2);
  while (out.length < length) {
    globalThis.crypto.getRandomValues(buf);
    for (const byte of buf) {
      if (byte < LIMIT) out += ALPHABET[byte % ALPHABET.length];
      if (out.length === length) break;
    }
  }
  return out;
}
