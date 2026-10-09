# PopBatchTool: auditable generic structured-MIDI batches

`PopBatchTool` converts a manifest-declared batch of local structured MIDI files into the same QinBan `Songs`/catalog shape used by the existing POP909 pipeline. The tool is provider-neutral for new batches and keeps the legacy POP909 file names and metadata wording when the legacy manifest shape is detected.

## Scope and evidence boundary

- Reads only local MIDI and manifest-provided reference JSON files.
- Compares source timing numerically through the existing `PlanChecks` contract.
- Runs offline mapping checks for the nine melodic profiles and blocks drum profiles.
- Does not download sources, play audio, send OS/game input, inject into a process, or install into the runtime.
- `musicReview`, `gameReview`, and rights fields are not independently certified by this tool.

## Manifest contract

The strict JSON manifest contains `provider`, `batchKind`, `sourceCommit`, `retrievedAtUtc`, and `songs`. Batch-level `license`, `licenseUrl`, `rightsStatus`, `rightsNote`, and `redistributionVerified` may provide defaults; a song-level value overrides the batch value.

A generic entry must provide:

- `id`: stable Windows-filename-safe token, for example `pdmx-a1b2c3-001`.
- `title`, `artist`, `midiPath`, `referencePath`, `sourceUrl`, `sourceSha256`, and `languageTags`.
- `workId` and `editionId`; `editionId` is unique within the manifest.
- `versionLabel` when multiple editions share one `workId`; labels for those editions must be non-empty and distinct.
- `musicReview=not-reviewed` and `gameReview=not-tested`, because this tool only produces source-timing evidence.
- A non-empty license and rights status. No generic-provider rights default is applied.

`sourceUrl` must be an absolute HTTP(S) URL. `sourceSha256` must be 64 hexadecimal characters and must match the local MIDI bytes. The reference is independently hashed before and after conversion.

## Provider-neutral output names

- Legacy POP909 IDs (`001` through `909` with provider `POP909`) keep the existing names: `pop909-001.json` and `pop909-001.<instrument>.plan.json`.
- Other providers use the stable ID directly: `pdmx-a1b2c3-001.json` and `pdmx-a1b2c3-001.<instrument>.plan.json`.
- A generic provider cannot use a PDMX-style ID while claiming to be POP909; the legacy POP909 compatibility branch accepts only the old numeric ID form.

## Rights handling

`License`, `LicenseUrl`, `RightsStatus`, and `RedistributionVerified` are copied from the manifest into score provenance and the build report. The only fallback is the pre-existing POP909 manifest shape, whose old repository-license declaration is retained solely so the already-built POP909 path remains compatible. This fallback is never used for PDMX or any other provider.

## Commands

```powershell
# Build the tool offline
D:\原神弹琴脚本\.tools\dotnet\dotnet.exe build `
  D:\原神弹琴脚本\AutoMidiPlayer\tools\PopBatchTool\PopBatchTool.csproj `
  -c Release --nologo --disable-build-servers `
  -p:UseSharedCompilation=false -p:NuGetAudit=false

# Validate a manifest without building, downloading, or installing anything
D:\原神弹琴脚本\.tools\dotnet\dotnet.exe \
  D:\原神弹琴脚本\AutoMidiPlayer\tools\PopBatchTool\bin\Release\net10.0\PopBatchTool.dll \
  validate-manifest <manifest.json>

# Build an additive batch into a new output directory
D:\原神弹琴脚本\.tools\dotnet\dotnet.exe \
  D:\原神弹琴脚本\AutoMidiPlayer\tools\PopBatchTool\bin\Release\net10.0\PopBatchTool.dll \
  build <manifest.json> <existing-baseline-Songs-dir> <new-output-dir>
```

`test_generic_manifest.ps1` exercises the provider/ID/rights contract with a temporary offline fixture. It deliberately does not download PDMX, execute a build, modify the library, or install a runtime batch.
