param(
    [string]$Dotnet = '',
    [string]$ToolDll = ''
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $Dotnet) { $Dotnet = Join-Path (Split-Path $repo -Parent) '.tools\dotnet\dotnet.exe' }
if (-not $ToolDll) { $ToolDll = Join-Path $PSScriptRoot 'bin\Release\net10.0\PopBatchTool.dll' }
if (-not (Test-Path -LiteralPath $Dotnet)) { throw "dotnet host not found: $Dotnet" }
if (-not (Test-Path -LiteralPath $ToolDll)) { throw "PopBatchTool DLL not found: $ToolDll" }

$sourceManifestPath = Join-Path $repo 'catalog-intake\pop909-remaining-2026-10-06-v2\build-manifest.json'
if (-not (Test-Path -LiteralPath $sourceManifestPath)) { throw "offline source manifest not found: $sourceManifestPath" }
$sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$source = $sourceManifest.songs[0]

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('qinban-popbatch-generic-contract-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
try {
    # This is a local contract fixture only. It reuses an existing local MIDI/reference
    # byte pair to test manifest validation; it does not claim or acquire PDMX content.
    $generic = [ordered]@{
        provider = 'PDMX'
        batchKind = 'offline-contract-fixture'
        sourceCommit = 'fixture-no-download'
        retrievedAtUtc = '2026-10-06T00:00:00Z'
        license = 'fixture-license-declared-in-manifest'
        licenseUrl = 'https://example.invalid/pdmx/license'
        rightsStatus = 'unverified'
        rightsNote = 'Contract fixture; no redistribution claim.'
        redistributionVerified = $false
        songs = @([ordered]@{
            id = 'pdmx-a1b2c3-001'
            title = 'offline contract fixture'
            artist = 'fixture'
            midiPath = $source.midiPath
            referencePath = $source.referencePath
            sourceUrl = 'https://example.invalid/pdmx/pdmx-a1b2c3-001.mid'
            sourceSha256 = $source.sourceSha256
            languageTags = @('und')
            artists = @('fixture')
            workId = 'pdmx-work-a1b2c3-001'
            editionId = 'pdmx-edition-a1b2c3-001'
            versionLabel = 'offline fixture'
            completeness = 'unknown'
            musicReview = 'not-reviewed'
            gameReview = 'not-tested'
            redistributionVerified = $false
        })
    }
    $validPath = Join-Path $testRoot 'generic-valid.json'
    $generic | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $validPath -Encoding UTF8
    $validOutput = & $Dotnet $ToolDll validate-manifest $validPath 2>&1
    if ($LASTEXITCODE -ne 0) { throw "generic validate command failed: $($validOutput -join [Environment]::NewLine)" }
    $audit = ($validOutput -join [Environment]::NewLine) | ConvertFrom-Json
    if ($audit.provider -ne 'PDMX') { throw "provider was not preserved" }
    if ($audit.legacyPop909Compatibility) { throw "generic provider entered POP909 compatibility mode" }
    if (-not ($audit.outputFiles -contains 'pdmx-a1b2c3-001.json')) { throw "stable PDMX filename was not derived from ID" }
    if (-not ($audit.rightsStatuses -contains 'unverified')) { throw "manifest rights status was not retained" }

    $invalid = $generic.PSObject.Copy()
    $invalid.provider = 'POP909'
    $invalidPath = Join-Path $testRoot 'generic-invalid-pop-label.json'
    $invalid | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $invalidPath -Encoding UTF8
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $null = & $Dotnet $ToolDll validate-manifest $invalidPath 2>$null
    $invalidExit = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    if ($invalidExit -eq 0) { throw "PDMX-style ID was incorrectly accepted as POP909" }

    $global:LASTEXITCODE = 0
    Write-Output 'PASS generic provider/ID/rights manifest contract; no download, build, install, or input'
}
finally {
    $resolvedTest = [IO.Path]::GetFullPath($testRoot)
    $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedTest.StartsWith($resolvedTemp.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedTest -Recurse -Force -ErrorAction SilentlyContinue
    }
}
