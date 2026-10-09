param([ValidateSet('matrix','evidence','fixtures')][string]$Mode='matrix',[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot)
$repo=[IO.Path]::GetFullPath((Join-Path $root '..\..'))
$env:DOTNET_CLI_HOME=Join-Path $root '.cli-home'
$env:NUGET_PACKAGES=Join-Path $root '.nuget\packages'
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1';$env:DOTNET_NOLOGO='1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1';$env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false'
$env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH='false';$env:DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE='true'
$env:TEMP=Join-Path $root '.tmp';$env:TMP=$env:TEMP
$dotnet=Join-Path (Split-Path -Parent $repo) '.tools\dotnet\dotnet.exe'
$dll=Join-Path $root 'artifacts\bin\SmartInterludeProbe\release\SmartInterludeProbe.dll'
& $dotnet $dll "--$Mode" $repo $Output
if($LASTEXITCODE -ne 0){throw "Probe returned $LASTEXITCODE (reports are retained if created)"}