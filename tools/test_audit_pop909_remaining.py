from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

import audit_pop909_remaining as audit


def _xlsx_fixture(path: Path, rows: list[list[str]]) -> None:
    sheet_rows = []
    for row_number, row in enumerate(rows, 1):
        cells = []
        for col, value in enumerate(row, 1):
            ref = ""
            n = col
            while n:
                n, rem = divmod(n - 1, 26)
                ref = chr(65 + rem) + ref
            escaped = (
                value.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            cells.append(f'<c r="{ref}{row_number}" t="inlineStr"><is><t>{escaped}</t></is></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    workbook = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="POP909" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
        '</Relationships>'
    )
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def _write_fixture_workspace(root: Path) -> None:
    intake = root / "catalog-intake" / "pop100-2026-10-06"
    songs = root / "Songs"
    intake.mkdir(parents=True)
    songs.mkdir()
    headers = ["song_id", "name", "artist", "modify_times", "num_beats_per_measure", "num_quavers_per_beat"]
    rows = [headers]
    for number in range(1, audit.TOTAL_POP909 + 1):
        song_id = f"{number:03d}"
        if song_id == "001":
            title, artist = "Alpha\u3010\u539f\u7248\u3011", "Artist A"
        elif song_id == "002":
            title, artist = "Alpha\u65b0\u7248", "Artist A"
        elif song_id == "003":
            title, artist = "Beta", "Artist B"
        else:
            title, artist = f"Song {song_id}", f"Artist {number}"
        rows.append([song_id, title, artist, "1", "2", "2"])
    _xlsx_fixture(intake / "index.xlsx", rows)

    archive_root = "POP909-Dataset-test"
    members = []
    tree = []
    for number in range(1, audit.TOTAL_POP909 + 1):
        song_id = f"{number:03d}"
        data = b"midi-a" if song_id in {"001", "002"} else f"midi-{song_id}".encode("ascii")
        path = f"POP909/{song_id}/{song_id}.mid"
        members.append((f"{archive_root}/{path}", data))
        tree.append({
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": audit._git_blob_sha1(data),
            "size": len(data),
            "url": "https://example.invalid/unused",
        })
    with zipfile.ZipFile(intake / "source-archive.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            archive.writestr(name, data)
    (intake / "source-tree.json").write_text(
        json.dumps({"sha": audit.DEFAULT_COMMIT, "tree": tree, "truncated": False}),
        encoding="utf-8",
    )

    connection = sqlite3.connect(songs / "catalog.db")
    connection.executescript(
        """
        CREATE TABLE entries(id TEXT PRIMARY KEY, work_id TEXT NOT NULL, relative_path TEXT NOT NULL,
            content_hash TEXT NOT NULL, original_hash TEXT NOT NULL, metadata_json TEXT NOT NULL);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE search_index(entry_id TEXT PRIMARY KEY, title_key TEXT NOT NULL, author_key TEXT NOT NULL,
            search_text TEXT NOT NULL, pinyin TEXT NOT NULL, initials TEXT NOT NULL, sort_title TEXT NOT NULL,
            duration REAL NOT NULL, added_ms INTEGER NOT NULL, provider TEXT NOT NULL,
            timing_verified INTEGER NOT NULL, completeness TEXT NOT NULL, human_reviewed INTEGER NOT NULL);
        """
    )
    source_hash = hashlib.sha256(b"midi-a").hexdigest().upper()
    metadata = {
        "title": "Alpha",
        "provenance": {
            "provider": "POP909",
            "artist": "Artist A",
            "versionLabel": "",
            "sourceSha256": source_hash,
        },
    }
    connection.execute(
        "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)",
        ("builtin:pop909-001.json", "pop909:001", "pop909-001.json", source_hash, source_hash, json.dumps(metadata)),
    )
    connection.execute(
        "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)",
        ("builtin:demo.json", "qinban-demo:demo", "demo.json", "D" * 64, "D" * 64, json.dumps({"title": "Demo", "provenance": {"provider": "qinban-demo"}})),
    )
    connection.commit()
    connection.close()


class AuditTests(unittest.TestCase):
    def test_version_label_and_work_key(self) -> None:
        base, labels, markers = audit.extract_version_labels("Alpha\u3010\u539f\u7248\u3011")
        self.assertEqual(base, "Alpha")
        self.assertIn("original", labels)
        self.assertIn("\u539f\u7248", markers)
        keys = audit.make_work_keys("Alpha\u65b0\u7248", "Artist A")
        self.assertEqual(keys["normalized_work_key"], "alpha::artista")
        self.assertEqual(keys["version_labels"], ["new"])

    def test_fixture_audit_detects_remaining_conflict_and_sha_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            _write_fixture_workspace(workspace)
            result = audit.build_audit(workspace, batch_size=2)
            summary = result["summary"]
            self.assertEqual(summary["pop909_total"], 909)
            self.assertEqual(summary["catalog_entry_count"], 2)
            self.assertEqual(summary["catalog_pop909_collected"], 1)
            self.assertEqual(summary["pop909_remaining"], 908)
            self.assertEqual(summary["source_sha_duplicate_group_count"], 1)
            self.assertEqual(summary["version_conflict_group_count"], 1)
            self.assertEqual(summary["version_conflict_record_count"], 2)
            remaining = {item["song_id"]: item for item in result["remaining"]}
            self.assertTrue(remaining["002"]["version_conflict"])
            self.assertTrue(remaining["002"]["source_sha_duplicate"])
            self.assertEqual(sum(item["recommended_next_batch"] for item in result["remaining"]), 2)

    def test_real_workspace_summary(self) -> None:
        workspace = Path(__file__).resolve().parents[1]
        result = audit.build_audit(workspace, batch_size=100)
        summary = result["summary"]
        self.assertEqual(summary["pop909_total"], 909)
        # The live source catalogue now includes the installed 601-edition
        # batch. WorkId may repeat across editions, but source song IDs remain
        # unique because the audit resolves them from relative_path/sourceUrl.
        self.assertGreaterEqual(summary["catalog_entry_count"], 1900)
        self.assertEqual(summary["catalog_pop909_collected"], 901)
        self.assertEqual(summary["pop909_remaining"], 8)
        self.assertEqual(summary["source_archive_midi_count"], 909)
        self.assertEqual(summary["source_sha_duplicate_group_count"], 0)


if __name__ == "__main__":
    unittest.main()
