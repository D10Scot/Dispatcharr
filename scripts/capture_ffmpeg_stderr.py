#!/usr/bin/env python3
"""Capture a real ffmpeg stderr corpus for the stage-2a subprocess harness.

Run inside the backend test container:

    docker exec -w /repo dispatcharr-testrunner bash -lc \
      'export PATH=/dispatcharrpy/bin:$PATH; python scripts/capture_ffmpeg_stderr.py \
         apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr'

Drives the PRODUCTION ffmpeg command -- core/migrations/0003_preload_stream_profiles.py's
`ffmpeg -i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1`, no -loglevel, so the
default `info` -- against a looping lavfi asset served over HTTP at a controlled
rate, and writes each run's raw stderr bytes verbatim (\\r separators included).

LD_LIBRARY_PATH is set for every child: the image carries two librist and the
loader picks the wrong one without it, so an unqualified ffmpeg dies with
`undefined symbol: rist_peer_config_defaults_set_versioned`. docker/entrypoint.sh
sets this in production; no test context runs that entrypoint.
"""

import http.server
import os
import socketserver
import subprocess
import sys
import threading
import time

FFMPEG_ENV = {**os.environ, "LD_LIBRARY_PATH": "/usr/local/lib"}
ASSET_SECONDS = 8

# name, seconds to run, upstream rate (x real time), truncate after N seconds of media
RUNS = [
    ("normal", 8, 2.0, None),
    ("slow-trickle", 45, 0.25, None),
    ("truncation", 10, 2.0, 3.0),
]


def build_asset():
    done = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=25:duration={ASSET_SECONDS}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={ASSET_SECONDS}",
         "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "400k", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "64k", "-f", "mpegts", "pipe:1"],
        capture_output=True, env=FFMPEG_ENV, timeout=120,
    )
    if done.returncode != 0:
        raise SystemExit("ffmpeg could not build the asset: "
                         + done.stderr.decode(errors="replace")[:400])
    return done.stdout


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    asset = build_asset()
    byte_rate = len(asset) / ASSET_SECONDS
    print(f"asset: {len(asset)} bytes, {len(asset) // 188} packets, {int(byte_rate)} B/s")

    mode = {"rate": 1.0, "truncate_at": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Connection", "close")
            self.end_headers()
            rate = mode["rate"] * byte_rate
            truncate_at = mode["truncate_at"]
            sent = at = 0
            started = time.monotonic()
            try:
                while True:
                    if truncate_at is not None and sent >= truncate_at:
                        self.connection.close()
                        return
                    want = 9400
                    if truncate_at is not None:
                        want = min(want, truncate_at - sent)
                    piece = bytearray()
                    while len(piece) < want:
                        take = min(want - len(piece), len(asset) - at)
                        piece += asset[at:at + take]
                        at = (at + take) % len(asset)
                    self.wfile.write(bytes(piece))
                    sent += len(piece)
                    due = started + sent / rate
                    now = time.monotonic()
                    if due > now:
                        time.sleep(min(due - now, 0.2))
            except OSError:
                return

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/live.ts"

    for name, seconds, rate, truncate_seconds in RUNS:
        mode["rate"] = rate
        mode["truncate_at"] = None if truncate_seconds is None else int(byte_rate * truncate_seconds)
        child = subprocess.Popen(
            ["ffmpeg", "-i", url, "-c:v", "copy", "-c:a", "copy", "-f", "mpegts", "pipe:1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=FFMPEG_ENV,
        )
        chunks = []

        def drain(stream=child.stderr, sink=chunks):
            while True:
                block = stream.read(4096)
                if not block:
                    break
                sink.append(block)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        time.sleep(seconds)
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        reader.join(timeout=5)

        data = b"".join(chunks)
        path = os.path.join(out_dir, f"{name}.stderr")
        with open(path, "wb") as handle:
            handle.write(data)
        print(f"{name}: {len(data)} bytes, {data.count(b'speed=')} progress records -> {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
