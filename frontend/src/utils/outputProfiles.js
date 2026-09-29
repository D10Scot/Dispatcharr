// Output Profiles that are HLS profiles (a non-blank hls_mode, spec D12) are
// chosen per channel and built by the relay. Every other Output Profile
// consumer excludes them: they carry no argv a per-client transcode could use.

export const isHlsOutputProfile = (p) => Boolean(p?.hls_mode);

export const selectableOutputProfiles = (profiles) =>
  (profiles ?? []).filter((p) => !isHlsOutputProfile(p));

export const hlsOutputProfiles = (profiles) =>
  (profiles ?? []).filter((p) => isHlsOutputProfile(p) && p.is_active);
