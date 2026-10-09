param([string]$Dotnet = 'D:\原神弹琴脚本\.tools\dotnet\dotnet.exe', [switch]$IncludeCoreTests)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$repo = [IO.Path]::GetFullPath((Join-Path $root '..\..'))
# SDK, NuGet, temp and referenced Core/Test build artifacts ALL remain in the sole write set.
$env:DOTNET_CLI_HOME = Join-Path $root '.cli-home'
$env:NUGET_PACKAGES = Join-Path $root '.nuget\packages'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'; $env:DOTNET_NOLOGO = '1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'; $env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH = 'false'; $env:DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE = 'true'
$env:TEMP = Join-Path $root '.tmp'; $env:TMP = $env:TEMP
$feed = Join-Path $root '.nuget\offline-feed'
$artifacts = Join-Path $root 'artifacts'
foreach ($p in @($env:DOTNET_CLI_HOME, $env:NUGET_PACKAGES, $env:TEMP, $feed, $artifacts)) {
    [IO.Directory]::CreateDirectory($p) | Out-Null
}
$cache = Join-Path (Split-Path -Parent $repo) '.tools\cli-home\.nuget\packages'
$packages = @('melanchall.drywetmidi/8.0.3','microsoft.data.sqlite/10.0.12','microsoft.data.sqlite.core/10.0.12',
    'sqlitepclraw.bundle_e_sqlite3/2.1.12','sqlitepclraw.core/2.1.12','sqlitepclraw.lib.e_sqlite3/2.1.12','sqlitepclraw.provider.e_sqlite3/2.1.12')
foreach ($p in $packages) {
    $parts = $p.Split('/'); $name = "$($parts[0]).$($parts[1]).nupkg"
    $input = Join-Path (Join-Path $cache $p) $name; $output = Join-Path $feed $name
    if (-not (Test-Path -LiteralPath $input -PathType Leaf)) { throw "Offline cache missing (no network fallback): $input" }
    if (Test-Path -LiteralPath $output) {
        if ((Get-FileHash -LiteralPath $input).Hash -ne (Get-FileHash -LiteralPath $output).Hash) { throw "Cache hash mismatch: $name" }
    } else { [IO.File]::Copy($input, $output, $false) }
}
$projects = @((Join-Path $root 'Pop100GapProbe.csproj'))
if ($IncludeCoreTests) { $projects += Join-Path $repo 'QinBan.Tests\QinBan.Tests.csproj' }
foreach ($project in $projects) {
    & $Dotnet build $project -c Release --nologo --disable-build-servers --artifacts-path $artifacts --source $feed `
        -p:UseSharedCompilation=false -p:NuGetAudit=false '-p:DefaultItemExcludes=**/obj/**' '-p:DefaultExcludesInProjectFolder=**/bin/**'
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $project ($LASTEXITCODE)" }
}
Write-Output ('Tool DLL: ' + (Join-Path $artifacts 'bin\Pop100GapProbe\release\Pop100GapProbe.dll'))

