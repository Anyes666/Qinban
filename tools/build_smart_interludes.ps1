param([ValidateSet('build','publish','tests')][string]$Mode='build')
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$work=Join-Path $repo '.validation\smart-interludes-2026-10-06'
$buildHome=Join-Path $work 'build-home';$feed=Join-Path $buildHome 'offline-feed';$artifacts=Join-Path $work 'artifacts'
$env:DOTNET_CLI_HOME=Join-Path $buildHome 'cli';$env:NUGET_PACKAGES=Join-Path $buildHome 'packages'
$env:TEMP=Join-Path $buildHome 'tmp';$env:TMP=$env:TEMP
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1';$env:DOTNET_NOLOGO='1';$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false';$env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH='false'
$env:DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE='true'
foreach($p in @($feed,$artifacts,$env:DOTNET_CLI_HOME,$env:NUGET_PACKAGES,$env:TEMP)){[IO.Directory]::CreateDirectory($p)|Out-Null}
$cache=Join-Path (Split-Path $repo -Parent) '.tools\cli-home\.nuget\packages'
foreach($p in Get-ChildItem -LiteralPath $cache -Filter '*.nupkg' -Recurse -File){
 $target=Join-Path $feed $p.Name
 if(Test-Path -LiteralPath $target){if((Get-FileHash $p.FullName).Hash -ne (Get-FileHash $target).Hash){throw 'Offline cache collision'}}
 else{[IO.File]::Copy($p.FullName,$target,$false)}
}
$dotnet=Join-Path (Split-Path $repo -Parent) '.tools\dotnet\dotnet.exe'
$common=@('-c','Release','--nologo','--disable-build-servers','--artifacts-path',$artifacts,'--source',$feed,
 '-p:UseSharedCompilation=false','-p:NuGetAudit=false','-p:DefaultItemExcludes=**/obj/**','-p:DefaultExcludesInProjectFolder=**/bin/**')
if($Mode -eq 'publish'){
 $out=Join-Path $work 'publish'
 if(Test-Path -LiteralPath $out){throw "Use build for a rebuild; preserve existing publish: $out"}
 & $dotnet publish (Join-Path $repo 'QinBan.Desktop\QinBan.Desktop.csproj') @common -r win-x64 --self-contained true `
  -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:PublishTrimmed=false -p:DebugType=none -o $out
}elseif($Mode -eq 'tests'){
 & $dotnet build (Join-Path $repo 'QinBan.Tests\QinBan.Tests.csproj') @common
}else{
 & $dotnet build (Join-Path $repo 'QinBan.slnx') @common
}
if($LASTEXITCODE -ne 0){throw "Isolated $Mode failed: $LASTEXITCODE"}
Write-Output "PASS isolated $Mode (production bin/obj unchanged)"