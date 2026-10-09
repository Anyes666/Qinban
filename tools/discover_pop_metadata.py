"""Parse an already fetched POP909 title index. OFFLINE metadata only, never scores.
Candidate IDs are provider row IDs, not verified global work/recording identities.
"""
import argparse, csv, hashlib, io, json, re, unicodedata, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MAX_INDEX_BYTES = 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
SOURCE = "https://github.com/music-x-lab/POP909-Dataset/blob/master/POP909/index.xlsx"


def xml_member(archive, name):
    info = archive.getinfo(name)
    if info.file_size > MAX_XML_BYTES: raise ValueError("Index XML exceeds 8 MiB")
    data = archive.read(name)
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data: raise ValueError("XML declarations/entities are not accepted")
    return ET.fromstring(data)


def parse_index(data):
    if len(data) > MAX_INDEX_BYTES: raise ValueError("Metadata index exceeds 1 MiB")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(t.text or "" for t in item.findall(".//s:t", NS)) for item in xml_member(archive, "xl/sharedStrings.xml").findall("s:si", NS)]
        sheet = xml_member(archive, "xl/worksheets/sheet1.xml")
        rows = sheet.findall("s:sheetData/s:row", NS)
        if not rows or len(rows) > 10001: raise ValueError("Expected bounded title metadata rows")
        decoded = []
        for row in rows:
            values = {}
            for cell in row.findall("s:c", NS):
                address = cell.get("r", "")
                match = re.fullmatch(r"([A-Z]+)[1-9][0-9]*", address)
                if not match: raise ValueError("Invalid cell address")
                column = match.group(1)
                if column in values: raise ValueError("Duplicate metadata cell")
                if cell.find("s:f", NS) is not None: raise ValueError("Formula cells are not title metadata")
                text = cell.findtext("s:v", default="", namespaces=NS)
                kind = cell.get("t", "n")
                if kind == "s":
                    if not text.isdigit() or int(text) >= len(shared): raise ValueError("Invalid shared-string index")
                    text = shared[int(text)]
                elif kind == "inlineStr": text = "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                elif kind not in ("n", "str"): raise ValueError("Unsupported title cell type")
                values[column] = text.strip()
            if any(values.values()): decoded.append(values)
        if not decoded: raise ValueError("Metadata worksheet has no rows")
        header = decoded[0]
        columns = {name: next((col for col, value in header.items() if value == name), None) for name in ("song_id", "name", "artist")}
        if any(col is None for col in columns.values()) or len(set(header.values())) != len(header): raise ValueError("Unexpected or duplicate title-index columns")
        candidates, ids = [], set()
        for row in decoded[1:]:
            identity, title, artist = (row.get(columns[name], "") for name in ("song_id", "name", "artist"))
            if not re.fullmatch(r"[0-9]{3}", identity) or identity in ids: raise ValueError("Missing/duplicate POP909 metadata identity")
            if not title or len(title) > 180 or not artist or len(artist) > 256: raise ValueError("Invalid title/artist metadata")
            ids.add(identity)
            candidates.append({"candidateId": "pop909-index:" + identity, "sourceIndexId": identity, "title": title,
                "artists": [artist], "languageTags": [], "album": "", "versionLabel": "", "verifiedWorkId": None, "verifiedRecordingId": None,
                "metadataStatus": "provider-title-artist-only", "languageStatus": "not-stated-by-source", "notationStatus": "not-acquired",
                "completeWorkStatus": "not-reviewed", "usageStatus": "not-reviewed", "musicReview": "not-reviewed", "gameReview": "not-tested",
                "metadataSource": SOURCE, "notationCandidateDirectory": "https://github.com/music-x-lab/POP909-Dataset/tree/master/POP909/" + identity})
        return candidates


def build_report(data):
    candidates = parse_index(data)
    normalize = lambda value: unicodedata.normalize("NFKC", value).casefold()
    pairs = {(normalize(c["title"]), normalize(c["artists"][0])) for c in candidates}
    return {"kind": "PUBLIC TITLE/ARTIST METADATA ONLY; NOT SCORES OR CERTIFIED WORKS", "indexSha256": hashlib.sha256(data).hexdigest().upper(),
        "candidateRows": len(candidates), "distinctTitleArtistPairs": len(pairs), "realScoresObtained": 0, "formalSongsAdded": 0, "verifiedDifferentWorks": 0,
        "languagesInferred": 0, "limitations": ["Provider index artist text is retained verbatim; it is not independently verified singer identity.",
        "Language, album, recording edition and complete musical notation are absent, not guessed.", "Same title/artist pair does not prove the same work; differing rows do not prove distinct works.",
        "Candidate directories are references only; this tool never fetches MIDI, audio or notation and never edits Songs/UserData."], "candidates": candidates}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("local_index", type=Path); parser.add_argument("new_output_directory", type=Path)
    args = parser.parse_args()
    if args.local_index.stat().st_size > MAX_INDEX_BYTES: raise ValueError("Metadata index exceeds 1 MiB")
    result = build_report(args.local_index.read_bytes()); out = args.new_output_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    with (out / "candidates.json").open("x", encoding="utf-8") as stream: json.dump(result, stream, ensure_ascii=False, indent=2); stream.write("\n")
    with (out / "candidates.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        fields = ["candidate_id", "title", "source_artist_text", "language_tags", "album", "version_label", "notation_status", "usage_status", "metadata_source"]
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for c in result["candidates"]: writer.writerow(dict(zip(fields, [c["candidateId"], c["title"], c["artists"][0], "", "", "", "not-acquired", "not-reviewed", c["metadataSource"]])))
    print(f"CANDIDATES {result['candidateRows']}; title/artist pairs {result['distinctTitleArtistPairs']}; actual scores obtained=0; formal songs added=0")


if __name__ == "__main__": main()
