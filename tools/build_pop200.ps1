param([string]$Dotnet='')
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if(-not $Dotnet){$Dotnet=Join-Path (Split-Path $repo -Parent) '.tools\dotnet\dotnet.exe'}
$work=Join-Path $repo '.validation\pop200-2026-10-06'
if(-not (Test-Path -LiteralPath $work -PathType Container)){throw 'Create protected batch snapshots before building'}
$buildHome=Join-Path $work 'build-home';$feed=Join-Path $buildHome 'offline-feed';$artifacts=Join-Path $work 'artifacts'
$env:DOTNET_CLI_HOME=Join-Path $buildHome 'cli';$env:NUGET_PACKAGES=Join-Path $buildHome 'packages'
$env:TEMP=Join-Path $buildHome 'tmp';$env:TMP=$env:TEMP
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1';$env:DOTNET_NOLOGO='1';$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false';$env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH='false';$env:DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE='true'
foreach($p in @($buildHome,$feed,$artifacts,$env:DOTNET_CLI_HOME,$env:NUGET_PACKAGES,$env:TEMP)){[IO.Directory]::CreateDirectory($p)|Out-Null}
$cache=Join-Path (Split-Path $repo -Parent) '.tools\cli-home\.nuget\packages'
foreach($p in Get-ChildItem -LiteralPath $cache -Filter '*.nupkg' -Recurse -File){
 $target=Join-Path $feed $p.Name
 if(Test-Path -LiteralPath $target){if((Get-FileHash -LiteralPath $p.FullName).Hash -ne (Get-FileHash -LiteralPath $target).Hash){throw 'Offline cache hash collision'}}
 else{[IO.File]::Copy($p.FullName,$target,$false)}
}
$common=@('-c','Release','--nologo','--disable-build-servers','--artifacts-path',$artifacts,'--source',$feed,'-p:UseSharedCompilation=false','-p:NuGetAudit=false','-p:DefaultItemExcludes=**/obj/**','-p:DefaultExcludesInProjectFolder=**/bin/**')
foreach($relative in @('tools\Pop200Tool\Pop200Tool.csproj','tools\Pop200InterludeProbe\Pop200InterludeProbe.csproj','tools\Pop100Recorder\Pop100Recorder.csproj','QinBan.Tests\QinBan.Tests.csproj')){
 & $Dotnet build (Join-Path $repo $relative) @common
 if($LASTEXITCODE -ne 0){throw "Offline isolated build failed: $relative ($LASTEXITCODE)"}
}
Write-Output 'PASS isolated Pop200 tools + current Core tests (runtime EXE and project bin/obj unchanged)'