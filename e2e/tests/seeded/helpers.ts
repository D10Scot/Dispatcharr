import type { Seeder, User, UserOverrides } from '../../fixtures';

/**
 * Local stand-in for G5's future `seed.xcUser()` — not landed as of
 * 2026-08-29 (see G8 task-11-report.md). The root XC catch-up routes
 * (`/timeshift/...`, `/streaming/timeshift.php`) authenticate through
 * `_authenticate_user` (apps/timeshift/views.py:758), which reads
 * `User.custom_properties['xc_password']` and compares it via
 * `hmac.compare_digest` against the URL's password segment — a credential
 * distinct from the Dispatcharr login password, and one no other fixture
 * factory sets.
 *
 * Deliberately not added to `e2e/fixtures/seed.ts`: when G5 lands its own
 * canonical `seed.xcUser()`, the two names would otherwise collide, and the
 * shared fixture is where every other goal's tests would then start reading
 * from. Kept local to G8's own specs instead, so G5's addition needs no
 * merge conflict — whichever lands second should delete this function and
 * repoint `tests/streaming/catchup-path-layout.spec.ts` at the shared one.
 *
 * `user_level: 10` (admin) rather than a Streamer/Standard level wired to a
 * `ChannelProfile`: `_user_can_access_channel` grants an admin every channel
 * unconditionally, sidestepping a profile-membership concern this task does
 * not test. The generated password is run through `Seeder.generatedName`,
 * which already sanitises to `^[A-Za-z0-9._@-]+$` — the exact set
 * `UserSerializer.validate_custom_properties` requires of `xc_password`.
 */
export async function seedXcUser(
  seed: Seeder,
  overrides: UserOverrides = {}
): Promise<User & { xcPassword: string }> {
  const xcPassword = seed.generatedName('xcpass');
  const user = await seed.user({
    user_level: 10,
    ...overrides,
    // Assigned after ...overrides, and after merging in any override's own
    // custom_properties, so a caller can add other keys but can never
    // silently shadow the one property this helper exists to set.
    custom_properties: {
      ...(overrides.custom_properties ?? {}),
      xc_password: xcPassword,
    },
  });
  return { ...user, xcPassword };
}
