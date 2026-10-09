param([ValidateSet('build','test','publish')][string]$Mode='build',[string]$SdkRoot='')
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
[xml]$project=Get-Content -LiteralPath (Join-Path $root "QinBan.Desktop\QinBan.Desktop.csproj") -Encoding UTF8
$version=[string]$project.Project.PropertyGroup.Version
$publishTarget=Join-Path (Split-Path -Parent $root) ("dist\QinBan-"+$version+"-win-x64")
if($SdkRoot) { $dotnet=Join-Path $SdkRoot 'dotnet.exe' } else {
  $local=Join-Path (Split-Path -Parent $root) '.tools\dotnet\dotnet.exe'
  if(Test-Path -LiteralPath $local) { $dotnet=$local } else { $dotnet=(Get-Command dotnet -ErrorAction Stop).Source }
}
$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'; $env:DOTNET_NOLOGO='1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1'; $env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false'; $env:DOTNET_ADD_GLOBAL_TOOLS_TO_PATH='false'
$env:DOTNET_CLI_HOME=Join-Path (Split-Path -Parent $root) '.tools\cli-home'
Push-Location $root
try {
  if($Mode -eq 'build') { & $dotnet build QinBan.slnx -c Release --nologo }
  elseif($Mode -eq 'test') { & $dotnet run --project QinBan.Tests\QinBan.Tests.csproj -c Release -- (Join-Path $root ('.validation\core-'+$version+'-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff'))) }
  else { if(Test-Path -LiteralPath $publishTarget){throw "Refusing to publish over an existing release or UserData: $publishTarget"}; & $dotnet publish QinBan.Desktop\QinBan.Desktop.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:PublishTrimmed=false -p:DebugType=none -o $publishTarget }
  if($LASTEXITCODE -ne 0) { throw "dotnet $Mode failed with exit code $LASTEXITCODE" }
  if($Mode -eq 'publish') {
    $target=$publishTarget
    foreach($name in @('VALIDATION.md','design-qa.md','BUILD-ENVIRONMENT.json','INSTRUMENTS.md')) {
      $file=Join-Path $root $name
      if(-not (Test-Path -LiteralPath $file)){throw "Required delivery document missing: $file"}
      Copy-Item -LiteralPath $file -Destination (Join-Path $target $name)
    }
    Copy-Item -LiteralPath (Join-Path $root 'tools\Start-QinBan.cmd') -Destination (Join-Path $target 'Start-QinBan.cmd')
    $sourceEvidence=Join-Path $root ('verification\'+$version)
    if(Test-Path -LiteralPath $sourceEvidence -PathType Container) {
      $evidence=Join-Path $target 'verification'; New-Item -ItemType Directory -Path $evidence -Force | Out-Null
      Get-ChildItem -LiteralPath $sourceEvidence -File | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $evidence $_.Name) }
    } else { Write-Warning '未附本地验证证据：公开源码克隆不含 verification，请对新生成的运行包单独验证。' }
  }
} finally { Pop-Location }
