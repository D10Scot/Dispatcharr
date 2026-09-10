"""Install the stand-in as `ffmpeg`, first on PATH.

Why PATH and not a patch: posix_spawn_proc resolves its executable with
shutil.which(cmd[0]) (apps/proxy/live_proxy/utils.py:152), and
output/fmp4/manager.py:32's FFMPEG_REMUX_CMD is a module constant whose first
element is the bare string "ffmpeg". A directory placed first on PATH therefore
redirects every one of those spawns without touching a line of production code.
input/manager.py's spawn is reached the other way, through a StreamProfile row's
`command` -- see stand_in_stream_profile below -- and a profile whose command is
the literal string "ffmpeg" also selects the ffmpeg log parser
(input/manager.py:750-758), which is what the buffering-detector rows need.

The stand-in is COPIED into a temp directory rather than run in place: the
repository is bind-mounted read-only in the hook container, so nothing in the
tree can be given an exec bit at test time, and a copy that imports nothing from
this repository is a genuinely external program rather than a Python object
pretending to be one.
"""

import os
import shutil
import stat
import sys
import tempfile

from .ffmpeg_stderr import CORPUS_NAMES
from .ffmpeg_stderr import path as corpus_path

_STANDIN_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standin.py")


class StandInBin:
    """Context manager: a temp dir holding an executable `ffmpeg`, first on PATH."""

    def __init__(
        self,
        *,
        stderr_corpus: str | None = "normal",
        stderr_interval: float = 0.05,
        stderr_loop: bool = False,
        exit_after_bytes: int | None = None,
        exit_code: int = 0,
        dead_air_after_bytes: int | None = None,
    ) -> None:
        if stderr_corpus is not None and stderr_corpus not in CORPUS_NAMES:
            raise ValueError(
                f"unknown corpus {stderr_corpus!r}; expected one of {', '.join(CORPUS_NAMES)} "
                "or None for a silent stand-in"
            )
        self.stderr_corpus = stderr_corpus
        self.stderr_interval = stderr_interval
        self.stderr_loop = stderr_loop
        self.exit_after_bytes = exit_after_bytes
        self.exit_code = exit_code
        self.dead_air_after_bytes = dead_air_after_bytes
        self.path = ""
        self._previous_path = ""

    @property
    def extra_parameters(self) -> str:
        """The stand-in flags a StreamProfile's `parameters` must carry, as a string."""
        parts = []
        if self.stderr_corpus is not None:
            parts += [
                "--stderr-corpus", os.path.join(self.path, "corpus.stderr"),
                "--stderr-interval", str(self.stderr_interval),
            ]
            if self.stderr_loop:
                parts += ["--stderr-loop"]
        if self.exit_after_bytes is not None:
            parts += ["--exit-after-bytes", str(self.exit_after_bytes)]
        if self.exit_code:
            parts += ["--exit-code", str(self.exit_code)]
        if self.dead_air_after_bytes is not None:
            parts += ["--dead-air-after-bytes", str(self.dead_air_after_bytes)]
        return " ".join(parts)

    def __enter__(self) -> "StandInBin":
        self.path = tempfile.mkdtemp(prefix="dispatcharr-standin-")
        shutil.copyfile(_STANDIN_SOURCE, os.path.join(self.path, "standin.py"))

        if self.stderr_corpus is not None:
            shutil.copyfile(
                corpus_path(self.stderr_corpus), os.path.join(self.path, "corpus.stderr")
            )

        wrapper = os.path.join(self.path, "ffmpeg")
        body = (
            f"#!{sys.executable}\n"
            "import runpy, sys, os\n"
            "sys.argv[0] = 'ffmpeg'\n"
            f"sys.argv[1:1] = {self._defaults_for_wrapper()!r}\n"
            f"runpy.run_path(os.path.join({self.path!r}, 'standin.py'), run_name='__main__')\n"
        )
        with open(wrapper, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        self._previous_path = os.environ["PATH"]
        os.environ["PATH"] = self.path + os.pathsep + self._previous_path
        return self

    def _defaults_for_wrapper(self) -> list[str]:
        """Stand-in flags injected by the wrapper itself.

        The fMP4 and Output Profile spawns use a command this harness does not
        build (FFMPEG_REMUX_CMD, and an OutputProfile row), so their arguments
        cannot carry these flags. Baking them into the wrapper means every
        spawn of this stand-in behaves the way the test asked for, however it
        was reached.
        """
        return self.extra_parameters.split() if self.extra_parameters else []

    def __exit__(self, *exc) -> None:
        if self._previous_path:
            os.environ["PATH"] = self._previous_path
            self._previous_path = ""
        shutil.rmtree(self.path, ignore_errors=True)
        self.path = ""


def stand_in_stream_profile(name: str = "harness-stand-in"):
    """An unlocked StreamProfile whose command is the literal string `ffmpeg`.

    Unlocked deliberately: core/models.py:78-101 forbids editing a locked
    profile's command, and the harness has no reason to touch the seeded ones.
    """
    from core.models import StreamProfile

    profile, _ = StreamProfile.objects.get_or_create(
        name=name,
        defaults={"command": "ffmpeg", "parameters": "-i {streamUrl}"},
    )
    return profile
