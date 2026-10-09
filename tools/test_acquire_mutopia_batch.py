"""Offline regression tests for acquire_mutopia_batch.py.

The tests use injected source data and an injected HTTP opener. They never call
network, the QinBan runtime, a game process, native input, or elevation.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import acquire_mutopia_batch as intake  # noqa: E402


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self._payload if limit < 0 else self._payload[:limit]


def midi_bytes(pitch: int = 60, *, duration_delta: bytes = b"\x87\x40", tempo_us: int = 500_000) -> bytes:
    """Return a tiny valid format-0 MIDI lasting one second at 120 BPM by default."""
    track = b"\x00\xff\x51\x03" + tempo_us.to_bytes(3, "big")
    track += b"\x00\x90" + bytes((pitch, 100))
    track += duration_delta + b"\x80" + bytes((pitch, 64))
    track += b"\x00\xff\x2f\x00"
    return b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + (480).to_bytes(2, "big") + b"MTrk" + len(track).to_bytes(4, "big") + track


def write_ly(path: Path, title: str, composer: str, *, license_name: str = "Public Domain", footer: str = "edition") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\\version \"2.24.0\"\n"
        "\\header {\n"
        f"  title = \"{title}\"\n"
        f"  composer = \"{composer}\"\n"
        f"  license = \"{license_name}\"\n"
        f"  footer = \"{footer}\"\n"
        "}\n"
        "{ c'1 }\n",
        encoding="utf-8",
    )


def make_opener(payloads: dict[str, bytes]):
    def opener(request, timeout=30):
        url = request.full_url
        if url not in payloads:
            raise URLError(f"fixture missing: {url}")
        return _Response(payloads[url])

    return opener


class AcquireMutopiaBatchTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "mutopia-source"
        write_ly(source / "ftp" / "same-work" / "alpha.ly", "Same Work", "Example Composer", footer="Version A")
        write_ly(source / "ftp" / "same-work" / "beta.ly", "Same Work", "Example Composer", footer="Version B")
        write_ly(source / "ftp" / "other" / "gamma.ly", "Other Work", "Second Composer", footer="Version C")
        write_ly(source / "ftp" / "excluded" / "cc.ly", "Not Bundled", "Composer", license_name="CC BY-SA 4.0")
        write_ly(source / "ftp" / "excluded" / "header.ly", "Fragment", "Composer")
        return source

    def test_creates_parent_and_preserves_work_and_edition_versions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mutopia-intake-") as temporary:
            root = Path(temporary)
            source = self._source(root)
            payloads = {
                "https://www.mutopiaproject.org/ftp/same-work/alpha.mid": midi_bytes(60),
                "https://www.mutopiaproject.org/ftp/same-work/beta.mid": midi_bytes(62),
            }
            output = root / "new" / "nested" / "batch"
            result = intake.acquire_batch(
                source,
                output,
                limit=2,
                opener=make_opener(payloads),
                now_fn=lambda: "2026-10-06T00:00:00+00:00",
                enforce_output_root=False,
            )

            self.assertTrue(output.is_dir())
            self.assertEqual(result["report"]["selectedCount"], 2)
            self.assertEqual(result["report"]["distinctWorkIds"], 1)
            self.assertEqual(result["report"]["sourceHashes"], 2)
            self.assertEqual(result["report"]["rightsStatus"], "candidate-unverified")
            self.assertFalse(result["report"]["redistributionVerified"])
            self.assertTrue(result["manifest"]["SmartInterludesDefault"])
            songs = result["manifest"]["Songs"]
            self.assertEqual(len(songs), 2)
            self.assertEqual({song["WorkId"] for song in songs}, {"mutopia-work:same-work::example-composer"})
            self.assertEqual(len({song["EditionId"] for song in songs}), 2)
            self.assertEqual({song["VersionLabel"] for song in songs}, {"Mutopia Version A / same-work/alpha.ly", "Mutopia Version B / same-work/beta.ly"})
            self.assertEqual({song["Title"] for song in songs}, {"Same Work (edition alpha)", "Same Work (edition beta)"})
            self.assertTrue(all(song["SmartInterludes"] for song in songs))
            self.assertTrue(all(song["RightsStatus"] == "candidate-unverified" for song in songs))
            self.assertTrue(all(Path(song["MidiPath"]).is_file() for song in songs))
            groups = json.loads((output / "version-groups.json").read_text(encoding="utf-8"))
            self.assertEqual(len(next(iter(groups["groups"].values()))), 2)

    def test_exclude_manifest_skips_source_hash_and_keeps_next_edition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mutopia-exclude-") as temporary:
            root = Path(temporary)
            source = self._source(root)
            payloads = {
                "https://www.mutopiaproject.org/ftp/same-work/alpha.mid": midi_bytes(60),
                "https://www.mutopiaproject.org/ftp/same-work/beta.mid": midi_bytes(62),
                "https://www.mutopiaproject.org/ftp/other/gamma.mid": midi_bytes(64),
            }
            first = root / "first"
            intake.acquire_batch(source, first, limit=1, opener=make_opener(payloads), enforce_output_root=False)
            second = root / "second"
            result = intake.acquire_batch(
                source,
                second,
                limit=1,
                exclude_manifests=[first / "manifest.json"],
                opener=make_opener(payloads),
                enforce_output_root=False,
            )
            selected = result["manifest"]["Songs"][0]
            first_song = json.loads((first / "manifest.json").read_text(encoding="utf-8"))["Songs"][0]
            self.assertNotEqual(selected["SourceSha256"], first_song["SourceSha256"])
            self.assertEqual(result["report"]["existingIntake"]["uniqueSourceSha256"], 1)
            self.assertEqual(result["report"]["existingIntake"]["uniqueEditionIds"], 1)

    def test_rejects_existing_output_and_outside_default_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mutopia-guards-") as temporary:
            root = Path(temporary)
            source = self._source(root)
            payloads = {"https://www.mutopiaproject.org/ftp/same-work/alpha.mid": midi_bytes(60)}
            output = root / "first"
            intake.acquire_batch(source, output, limit=1, opener=make_opener(payloads), enforce_output_root=False)
            with self.assertRaises(intake.IntakeError):
                intake.acquire_batch(source, output, limit=1, opener=make_opener(payloads), enforce_output_root=False)

            outside = root / "outside"
            with self.assertRaises(intake.IntakeError):
                intake.acquire_batch(source, outside, limit=1, opener=make_opener(payloads))

    def test_source_filter_excludes_non_public_domain_and_fragments(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mutopia-filter-") as temporary:
            source = self._source(Path(temporary))
            rows = intake._source_candidates(source)
            paths = {row["lyPath"] for row in rows}
            self.assertEqual(paths, {"other/gamma.ly", "same-work/alpha.ly", "same-work/beta.ly"})
            self.assertTrue(all(candidate.endswith(".mid") for row in rows for candidate in row["midCandidates"]))
            self.assertFalse(any(candidate.endswith("mid") and not candidate.endswith(".mid") for row in rows for candidate in row["midCandidates"]))

    def test_work_id_folds_unicode_accents_without_changing_display_metadata(self) -> None:
        self.assertEqual(
            intake._work_id("Prelude", "Frederic Chopin (1810-1849)"),
            intake._work_id("Prelude", "Fr\u00e9d\u00e9ric Chopin (1810-1849)"),
        )

    def test_avoid_title_disambiguates_existing_baseline_collision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mutopia-avoid-title-") as temporary:
            root = Path(temporary)
            source = root / "mutopia-source"
            write_ly(source / "ftp" / "piece" / "piece.ly", "Andantino", "Another Composer", footer="Avoided")
            payloads = {
                "https://www.mutopiaproject.org/ftp/piece/piece.mid": midi_bytes(60),
            }
            result = intake.acquire_batch(
                source, root / "out", limit=1, avoid_titles=["Andantino"],
                opener=make_opener(payloads), enforce_output_root=False
            )
            self.assertEqual(result["manifest"]["Songs"][0]["Title"], "Andantino (edition piece)")

    def test_duplicate_titles_across_composers_are_disambiguated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mutopia-title-collision-") as temporary:
            root = Path(temporary)
            source = root / "mutopia-source"
            write_ly(source / "ftp" / "one" / "piece.ly", "Shared Title", "Composer One", footer="One")
            write_ly(source / "ftp" / "two" / "piece.ly", "Shared Title", "Composer Two", footer="Two")
            payloads = {
                "https://www.mutopiaproject.org/ftp/one/piece.mid": midi_bytes(60),
                "https://www.mutopiaproject.org/ftp/two/piece.mid": midi_bytes(64),
            }
            result = intake.acquire_batch(
                source, root / "out", limit=2, opener=make_opener(payloads), enforce_output_root=False
            )
            titles = [song["Title"] for song in result["manifest"]["Songs"]]
            self.assertEqual(len(titles), len(set(titles)))
            self.assertTrue(all(title.startswith("Shared Title (edition ") for title in titles))

    def test_cc_by_sa_license_is_preserved_and_filterable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mutopia-cc-") as temporary:
            root = Path(temporary)
            source = root / "mutopia-source"
            write_ly(
                source / "ftp" / "licensed" / "piece.ly",
                "Licensed Piece",
                "CC Composer",
                license_name="Creative Commons Attribution-ShareAlike 4.0",
                footer="CC edition",
            )
            payloads = {
                "https://www.mutopiaproject.org/ftp/licensed/piece.mid": midi_bytes(67),
            }
            output = root / "cc-batch"
            result = intake.acquire_batch(
                source,
                output,
                limit=1,
                license_filter="CC BY-SA 4.0",
                opener=make_opener(payloads),
                enforce_output_root=False,
            )

            manifest = result["manifest"]
            song = manifest["Songs"][0]
            self.assertEqual(manifest["License"], "CC BY-SA 4.0")
            self.assertEqual(manifest["LicenseUrl"], "https://creativecommons.org/licenses/by-sa/4.0/")
            self.assertEqual(manifest["BatchKind"], "mutopia-cc-by-sa-4.0-candidate-intake")
            self.assertEqual(song["License"], "CC BY-SA 4.0")
            self.assertEqual(song["LicenseUrl"], "https://creativecommons.org/licenses/by-sa/4.0/")
            self.assertIn("ShareAlike", song["RightsNote"])
            self.assertIn("cc-by-sa-4.0-candidate", song["Tags"])
            self.assertEqual(song["WorkId"], "mutopia-work:licensed-piece::cc-composer")
            self.assertIn("CC BY-SA 4.0", (output / "source-LICENSE.txt").read_text(encoding="utf-8"))

    def test_rejects_bpm_outside_qinban_budget(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mutopia-bpm-") as temporary:
            root = Path(temporary)
            source = root / "mutopia-source"
            write_ly(source / "ftp" / "slow" / "slow.ly", "Too Slow", "Composer")
            row = intake._source_candidates(source)[0]
            payloads = {
                "https://www.mutopiaproject.org/ftp/slow/slow.mid": midi_bytes(60, tempo_us=4_285_714),
            }
            with self.assertRaises(intake.IntakeError):
                intake._download_candidate(row, opener=make_opener(payloads))


if __name__ == "__main__":
    unittest.main(verbosity=2)


