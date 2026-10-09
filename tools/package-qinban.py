"""Create local, version-matched archives; never delete or overwrite user data."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {".git", ".validation", "UserData", "bin", "obj", "__pycache__", ".tools", "dist"}

def digest_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()

def validate_source_path(rel):
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or any(part in EXCLUDED for part in p.parts):
        raise ValueError(f"Excluded or unsafe source path: {rel}")
    resolved = (ROOT / p).resolve()
    if not resolved.is_relative_to(ROOT) or not resolved.is_file() or (ROOT / p).is_symlink():
        raise ValueError(f"Invalid source file: {rel}")
    return p.as_posix()

def collect_sources():
    if (ROOT / ".git").exists():
        subprocess.run(["git", "diff", "--exit-code"], cwd=ROOT, check=True, capture_output=True)
        raw = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
        files = {validate_source_path(p) for p in raw.decode("utf-8").split("\0") if p}
    else:
        manifest = json.loads((ROOT / "SOURCE-MANIFEST.json").read_text(encoding="utf-8"))
        files = {validate_source_path(p) for p in manifest["files"]}
    for folder in ("QinBan.Core", "QinBan.Desktop", "QinBan.Tests", "QinBan.LibraryTools", "Songs", "tools", "licenses", "verification", "catalog-intake"):
        for p in (ROOT / folder).rglob("*"):
            rel = p.relative_to(ROOT)
            if p.is_file() and not any(part in EXCLUDED for part in rel.parts):
                files.add(validate_source_path(rel))
    for name in ("AGENTS.md", "CONTEXT.md", "QinBan.slnx", "README-QINBAN.md", "QINBAN-NOTICES.md", "VALIDATION.md", "design-qa.md", "BUILD-ENVIRONMENT.json", "build-qinban.ps1", "INSTRUMENTS.md", "APPEARANCE.md", "SCORE-LIBRARY.md", "SOURCE-INTAKE.md"):
        files.add(validate_source_path(name))
    return sorted(files)

def write_archive(path, prefix, base, files, manifest=None):
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in files:
            z.write(base / rel, prefix + "/" + rel)
        if manifest is not None:
            z.writestr(prefix + "/SOURCE-MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(path) as z:
        corrupt = z.testzip()
        if corrupt:
            raise ValueError(f"CRC failure: {corrupt}")
        names = z.namelist()
        if len(names) != len(set(names)) or any(".." in Path(n).parts for n in names):
            raise ValueError("Duplicate or unsafe archive entries")
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": digest_file(path), "entries": len(names), "crc": "PASS"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT.parent / "dist")
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    env = json.loads((ROOT / "BUILD-ENVIRONMENT.json").read_text(encoding="utf-8"))
    version = env["version"]
    portable = ROOT.parent / "dist" / f"QinBan-{version}-win-x64"
    exe = portable / "QinBan.exe"
    run = json.loads((ROOT / "verification" / version / "ui-run.json").read_text(encoding="utf-8"))
    if digest_file(exe) != run["sha256"] or run["exitCode"] != 0:
        raise ValueError("Published executable does not match passing validation evidence")
    portable_zip = out / f"QinBan-{version}-win-x64.zip"
    source_zip = out / f"QinBan-{version}-source.zip"
    report_path = out / f"packaging-report-{version}.json"
    sums_path = out / f"SHA256SUMS-{version}.txt"
    for p in (portable_zip, source_zip, report_path, sums_path):
        if p.exists():
            raise FileExistsError(f"Refusing to overwrite existing delivery artifact: {p}")
    portable_files = sorted(p.relative_to(portable).as_posix() for p in portable.rglob("*") if p.is_file() and "UserData" not in p.relative_to(portable).parts)
    needed = {"QinBan.exe", "Start-QinBan.cmd", "LICENSE", "QINBAN-NOTICES.md", "VALIDATION.md", "design-qa.md", "使用说明.md", "INSTRUMENTS.md", "instrument-assets.json", "background-assets.json", "外观与背景.md", "曲库与迁移.md", "谱源准入.md", "Songs/catalog.db", "search-data-manifest.json"}
    if not needed.issubset(portable_files):
        raise ValueError("Missing required portable files")
    if sum(n.startswith("Songs/") and n.endswith(".json") for n in portable_files) != 30:
        raise ValueError("Expected 30 built-in score files")
    sources = collect_sources()
    manifest = {"application": "QinBan", "version": version, "upstream": env["upstream"], "matchingExecutableSha256": digest_file(exe), "files": {rel: digest_file(ROOT / rel) for rel in sources}, "excluded": sorted(EXCLUDED)}
    archives = [write_archive(portable_zip, f"QinBan-{version}-win-x64", portable, portable_files), write_archive(source_zip, "QinBan-source", ROOT, sources, manifest)]
    report = {"application": "QinBan", "version": version, "executable": {"file": f"QinBan-{version}-win-x64/QinBan.exe", "bytes": exe.stat().st_size, "sha256": digest_file(exe)}, "archives": archives, "sourceFiles": len(sources), "portableFiles": len(portable_files), "userDataBundled": False, "publishedOnline": False}
    with report_path.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    lines = [a["sha256"] + "  " + a["file"] for a in archives]
    lines.append(digest_file(exe) + f"  QinBan-{version}-win-x64/QinBan.exe")
    with sums_path.open("x", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
