# Shared subprocess helper for build-step tests that need a throwaway git
# repo. Split out (R10) so later Part B test modules can reuse it instead of
# redefining it inline.
import subprocess


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
