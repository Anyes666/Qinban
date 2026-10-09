from __future__ import annotations

import hashlib
import re
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import download_ranges as downloader


_RANGE = re.compile(r"^bytes=(\d+)-(\d+)$")


class _RangeFixture:
    """Loopback-only HTTP Range fixture; no external network is used."""

    def __init__(
        self,
        payload: bytes,
        *,
        mode: str = "normal",
        short_start: int | None = None,
        delay: float = 0.0,
    ) -> None:
        self.payload = payload
        self.mode = mode
        self.short_start = short_start
        self.delay = delay
        self.requests: list[tuple[int, int]] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                fixture._handle(self)

            def log_message(self, format: str, *args: object) -> None:
                return

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            name="download-range-fixture",
            daemon=True,
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/archive.bin"

    def __enter__(self) -> "_RangeFixture":
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        if self.thread.is_alive():
            raise AssertionError("local Range fixture did not stop")

    def _handle(self, request: BaseHTTPRequestHandler) -> None:
        if urlsplit(request.path).path != "/archive.bin":
            request.send_error(404)
            return

        match = _RANGE.fullmatch(request.headers.get("Range", ""))
        if not match:
            request.send_error(416)
            return
        start, end = int(match.group(1)), int(match.group(2))
        with self._lock:
            self.requests.append((start, end))
            self.active += 1
            self.max_active = max(self.max_active, self.active)

        try:
            is_probe = start == 0 and end == 0
            status = 206
            content_range = f"bytes {start}-{end}/{len(self.payload)}"
            body = self.payload[start : end + 1]

            if self.mode == "probe-status-200" and is_probe:
                status = 200
            elif self.mode == "probe-bad-content-range" and is_probe:
                content_range = f"bytes 1-0/{len(self.payload)}"
            elif self.mode == "part-status-200" and not is_probe:
                status = 200
            elif self.mode == "part-bad-content-range" and not is_probe:
                content_range = f"bytes {start + 1}-{end}/{len(self.payload)}"
            elif self.mode == "short-part" and not is_probe and start == self.short_start:
                # Keep a valid declared range but deliberately send only a prefix.
                # The downloader must retain this partial part and refuse promotion.
                body = body[: max(1, len(body) // 2)]

            if self.delay and not is_probe:
                time.sleep(self.delay)

            request.send_response(status)
            request.send_header("Content-Type", "application/octet-stream")
            request.send_header("Content-Range", content_range)
            request.send_header("Content-Length", str(len(body)))
            request.send_header("Connection", "close")
            request.end_headers()
            request.wfile.write(body)
            request.wfile.flush()
        finally:
            with self._lock:
                self.active -= 1


class DownloadRangesTests(unittest.TestCase):
    def _data(self, size: int = 257) -> bytes:
        return bytes((index * 37 + 11) % 256 for index in range(size))

    def _part_path(self, parts: Path, start: int, end: int) -> Path:
        return parts / f"part-{start:012d}-{end:012d}.bin"

    def test_probe_requires_206_and_exact_content_range(self) -> None:
        payload = self._data(32)
        for mode, expected in (
            ("probe-status-200", "server did not return 206"),
            ("probe-bad-content-range", "invalid Content-Range"),
        ):
            with self.subTest(mode=mode), _RangeFixture(payload, mode=mode) as fixture:
                with self.assertRaisesRegex(RuntimeError, expected):
                    downloader.probe(fixture.url, timeout=2.0)
                self.assertEqual(fixture.requests, [(0, 0)])

    def test_parallel_ranges_require_206_and_assemble_in_order(self) -> None:
        payload = self._data(257)
        expected_ranges = downloader._ranges(len(payload), 17)
        with TemporaryDirectory() as temp, _RangeFixture(payload, delay=0.03) as fixture:
            root = Path(temp)
            output = root / "archive.bin"
            parts = root / "parts"
            report = downloader.download(
                fixture.url,
                output,
                parts,
                expected_size=len(payload),
                expected_md5=hashlib.md5(payload).hexdigest(),
                workers=4,
                chunk_size=17,
                retries=0,
                timeout=2.0,
            )

            self.assertEqual(output.read_bytes(), payload)
            self.assertEqual(report["status"], "PASS_RANGE_DOWNLOAD")
            self.assertEqual(report["remoteSize"], len(payload))
            self.assertEqual(report["partCount"], len(expected_ranges))
            self.assertEqual(report["md5"], hashlib.md5(payload).hexdigest())
            self.assertEqual(report["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertGreaterEqual(fixture.max_active, 2)
            self.assertTrue(
                set(expected_ranges).issubset(set(fixture.requests)),
                msg=f"missing Range requests: expected={expected_ranges!r}, got={fixture.requests!r}",
            )
            self.assertTrue(all((parts / name).stat().st_size > 0 for name in (p.name for p in parts.iterdir())))

    def test_part_response_requires_206_and_exact_content_range(self) -> None:
        payload = self._data(64)
        for mode, expected in (
            ("part-status-200", "part request did not return 206"),
            ("part-bad-content-range", "invalid part Content-Range"),
        ):
            with self.subTest(mode=mode), TemporaryDirectory() as temp, _RangeFixture(payload, mode=mode) as fixture:
                root = Path(temp)
                output = root / "archive.bin"
                parts = root / "parts"
                with self.assertRaisesRegex(RuntimeError, expected):
                    downloader.download(
                        fixture.url,
                        output,
                        parts,
                        expected_size=None,
                        expected_md5=None,
                        workers=1,
                        chunk_size=16,
                        retries=0,
                        timeout=2.0,
                    )
                self.assertFalse(output.exists())

    def test_partial_part_is_resumed_from_existing_size(self) -> None:
        payload = self._data(96)
        start, end = 32, 47
        prefix_size = 5
        with TemporaryDirectory() as temp, _RangeFixture(payload) as fixture:
            root = Path(temp)
            output = root / "archive.bin"
            parts = root / "parts"
            parts.mkdir()
            part = self._part_path(parts, start, end)
            part.write_bytes(payload[start : start + prefix_size])

            downloader.download(
                fixture.url,
                output,
                parts,
                expected_size=len(payload),
                expected_md5=hashlib.md5(payload).hexdigest(),
                workers=3,
                chunk_size=16,
                retries=0,
                timeout=2.0,
            )

            self.assertEqual(output.read_bytes(), payload)
            self.assertEqual(part.read_bytes(), payload[start : end + 1])
            self.assertIn((start + prefix_size, end), fixture.requests)
            self.assertNotIn((start, end), fixture.requests)

    def test_size_mismatch_fails_before_creating_parts_or_output(self) -> None:
        payload = self._data(48)
        with TemporaryDirectory() as temp, _RangeFixture(payload) as fixture:
            root = Path(temp)
            output = root / "archive.bin"
            parts = root / "parts"
            with self.assertRaisesRegex(RuntimeError, "remote size mismatch"):
                downloader.download(
                    fixture.url,
                    output,
                    parts,
                    expected_size=len(payload) + 1,
                    expected_md5=None,
                    workers=2,
                    chunk_size=12,
                    retries=0,
                    timeout=2.0,
                )
            self.assertFalse(output.exists())
            self.assertFalse(parts.exists())

    def test_md5_mismatch_does_not_promote_assembled_output(self) -> None:
        payload = self._data(73)
        with TemporaryDirectory() as temp, _RangeFixture(payload) as fixture:
            root = Path(temp)
            output = root / "archive.bin"
            parts = root / "parts"
            with self.assertRaisesRegex(RuntimeError, "assembled MD5 mismatch"):
                downloader.download(
                    fixture.url,
                    output,
                    parts,
                    expected_size=len(payload),
                    expected_md5="0" * 32,
                    workers=3,
                    chunk_size=13,
                    retries=0,
                    timeout=2.0,
                )
            self.assertFalse(output.exists())
            self.assertTrue(output.with_name(output.name + ".assembling").exists())
            self.assertTrue(list(parts.glob("part-*.bin")))

    def test_existing_output_and_report_are_never_overwritten(self) -> None:
        payload = self._data(32)
        with TemporaryDirectory() as temp, _RangeFixture(payload) as fixture:
            root = Path(temp)
            output = root / "archive.bin"
            parts = root / "parts"
            output.write_bytes(b"keep-output")
            with self.assertRaises(FileExistsError):
                downloader.download(
                    fixture.url,
                    output,
                    parts,
                    expected_size=None,
                    expected_md5=None,
                    workers=1,
                    chunk_size=8,
                    retries=0,
                    timeout=2.0,
                )
            self.assertEqual(output.read_bytes(), b"keep-output")
            self.assertEqual(fixture.requests, [])

            report = root / "report.json"
            report.write_text("keep-report", encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                downloader.main(
                    [
                        "--url",
                        fixture.url,
                        "--output",
                        str(root / "new.bin"),
                        "--parts",
                        str(root / "new-parts"),
                        "--report",
                        str(report),
                        "--workers",
                        "1",
                        "--chunk-size",
                        "8",
                        "--retries",
                        "0",
                        "--timeout",
                        "2",
                    ]
                )
            self.assertIn("refusing to overwrite report", str(raised.exception))
            self.assertEqual(report.read_text(encoding="utf-8"), "keep-report")
            self.assertEqual(fixture.requests, [])

    def test_failed_part_keeps_partial_file_and_does_not_create_output(self) -> None:
        payload = self._data(80)
        bad_start = 20
        with TemporaryDirectory() as temp, _RangeFixture(
            payload,
            mode="short-part",
            short_start=bad_start,
        ) as fixture:
            root = Path(temp)
            output = root / "archive.bin"
            parts = root / "parts"
            with self.assertRaisesRegex(RuntimeError, "short part after response"):
                downloader.download(
                    fixture.url,
                    output,
                    parts,
                    expected_size=len(payload),
                    expected_md5=None,
                    workers=3,
                    chunk_size=20,
                    retries=0,
                    timeout=2.0,
                )

            failed_part = self._part_path(parts, bad_start, bad_start + 19)
            self.assertTrue(failed_part.exists())
            self.assertGreater(failed_part.stat().st_size, 0)
            self.assertLess(failed_part.stat().st_size, 20)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
