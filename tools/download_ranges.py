"""Resumable parallel HTTP Range downloader for auditable source archives.

The tool is deliberately source-only: it never touches QinBan runtime/Songs/UserData,
does not delete partial files, and refuses servers that do not honor byte ranges.
Existing partial archives are preserved; use a new output name for a new acquisition.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


@dataclass(frozen=True)
class Remote:
    url: str
    size: int


def _request(url: str, start: int, end: int, timeout: float):
    request = Request(url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"})
    return urlopen(request, timeout=timeout)


def probe(url: str, timeout: float = 60.0) -> Remote:
    with _request(url, 0, 0, timeout) as response:
        if getattr(response, "status", None) != 206:
            raise RuntimeError(f"server did not return 206 for range probe: {getattr(response, 'status', None)}")
        header = response.headers.get("Content-Range", "")
        match = CONTENT_RANGE.fullmatch(header.strip())
        if not match or match.group(1) != "0" or match.group(2) != "0":
            raise RuntimeError(f"invalid Content-Range from source: {header!r}")
        size = int(match.group(3))
        if size <= 0:
            raise RuntimeError(f"invalid remote size: {size}")
        response.read(1)
        return Remote(url=url, size=size)


def _download_part(remote: Remote, start: int, end: int, path: Path, retries: int, timeout: float) -> dict:
    expected = end - start + 1
    if path.exists():
        size = path.stat().st_size
        if size > expected:
            raise RuntimeError(f"part is larger than assigned range: {path}")
    else:
        size = 0
    if size == expected:
        return {"path": str(path), "start": start, "end": end, "bytes": expected, "resumed": True, "complete": True}
    path.parent.mkdir(parents=True, exist_ok=True)
    current = start + size
    last_error = None
    for attempt in range(retries + 1):
        try:
            with _request(remote.url, current, end, timeout) as response:
                if getattr(response, "status", None) != 206:
                    raise RuntimeError(f"part request did not return 206: {getattr(response, 'status', None)}")
                header = response.headers.get("Content-Range", "")
                match = CONTENT_RANGE.fullmatch(header.strip())
                if not match or int(match.group(1)) != current or int(match.group(2)) != end or int(match.group(3)) != remote.size:
                    raise RuntimeError(f"invalid part Content-Range: {header!r}")
                with path.open("ab") as stream:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
            final_size = path.stat().st_size
            if final_size != expected:
                raise RuntimeError(f"short part after response: {path} {final_size}/{expected}")
            return {"path": str(path), "start": start, "end": end, "bytes": expected, "resumed": size > 0, "complete": True}
        except (OSError, HTTPError, URLError, RuntimeError) as error:
            last_error = error
            if attempt >= retries:
                break
            time.sleep(min(30.0, 2.0 ** attempt))
            size = path.stat().st_size if path.exists() else 0
            if size > expected:
                raise RuntimeError(f"part grew beyond assigned range after retry: {path}")
            current = start + size
    raise RuntimeError(f"failed part {start}-{end}: {last_error}")


def _ranges(size: int, chunk_size: int) -> list[tuple[int, int]]:
    if chunk_size < 1:
        raise ValueError("chunk size must be positive")
    return [(start, min(size - 1, start + chunk_size - 1)) for start in range(0, size, chunk_size)]


def _digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def download(url: str, output: Path, parts: Path, expected_size: int | None, expected_md5: str | None, workers: int, chunk_size: int, retries: int, timeout: float) -> dict:
    output = Path(output).absolute()
    parts = Path(parts).absolute()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    remote = probe(url, timeout)
    if expected_size is not None and remote.size != expected_size:
        raise RuntimeError(f"remote size mismatch: {remote.size} != expected {expected_size}")
    ranges = _ranges(remote.size, chunk_size)
    parts.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="range") as pool:
        futures = {
            pool.submit(_download_part, remote, start, end, parts / f"part-{start:012d}-{end:012d}.bin", retries, timeout): (start, end)
            for start, end in ranges
        }
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["start"])
    assembling = output.with_name(output.name + ".assembling")
    with assembling.open("wb") as target:
        for item in results:
            part = Path(item["path"])
            if part.stat().st_size != item["bytes"]:
                raise RuntimeError(f"part size changed before assembly: {part}")
            with part.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
    if assembling.stat().st_size != remote.size:
        raise RuntimeError(f"assembled size mismatch: {assembling.stat().st_size} != {remote.size}")
    md5 = _digest(assembling, "md5")
    sha256 = _digest(assembling, "sha256")
    if expected_md5 and md5.lower() != expected_md5.lower().replace("md5:", ""):
        raise RuntimeError(f"assembled MD5 mismatch: {md5} != {expected_md5}")
    os.replace(assembling, output)
    report = {
        "status": "PASS_RANGE_DOWNLOAD",
        "atUtc": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "output": str(output),
        "remoteSize": remote.size,
        "chunkSize": chunk_size,
        "workers": workers,
        "partCount": len(results),
        "md5": md5,
        "sha256": sha256,
        "expectedMd5": expected_md5,
        "partsDirectory": str(parts),
        "partialFilesPreserved": True,
    }
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--parts", required=True, type=Path)
    parser.add_argument("--expected-size", type=int)
    parser.add_argument("--expected-md5")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.report.exists():
        raise SystemExit(f"refusing to overwrite report: {args.report}")
    result = download(args.url, args.output, args.parts, args.expected_size, args.expected_md5, args.workers, args.chunk_size, args.retries, args.timeout)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"{result['status']}: {result['remoteSize']} bytes; md5={result['md5']}; sha256={result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
