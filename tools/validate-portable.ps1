param(
  [ValidateSet('ui','cold-start','scale','preparation','scroll')][string]$Mode='ui',
  [string]$Executable='',
  [string]$OutputRoot='',
  [string]$CatalogDirectory='',
  [int]$ExpectedBuiltins=0
)
$ErrorActionPreference='Stop'
$source=Split-Path -Parent $PSScriptRoot
if(-not $Executable){
  $version=(Get-Content -LiteralPath (Join-Path $source 'BUILD-ENVIRONMENT.json') -Encoding UTF8 | ConvertFrom-Json).version
  $Executable=Join-Path (Split-Path -Parent $source) ('dist\QinBan-'+$version+'-win-x64\QinBan.exe')
}
$Executable=[IO.Path]::GetFullPath($Executable)
if(-not (Test-Path -LiteralPath $Executable -PathType Leaf)){throw "Executable not found: $Executable"}
if(-not $OutputRoot){$OutputRoot=Join-Path $source ('.validation\portable-'+$Mode+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))}
if($Mode -eq 'scale') {
  if(-not $CatalogDirectory){throw 'Scale validation requires an explicitly marked synthetic catalogue directory.'}
  $CatalogDirectory=[IO.Path]::GetFullPath($CatalogDirectory)
  if($CatalogDirectory.Contains('"') -or -not (Test-Path -LiteralPath (Join-Path $CatalogDirectory 'catalog.db'))){throw 'Invalid synthetic catalogue directory.'}
} elseif($CatalogDirectory){throw 'Catalogue override is only available for scale validation.'}
if($Mode -eq 'cold-start' -and $ExpectedBuiltins -le 0) {
  $catalogDir=Join-Path (Split-Path -Parent $Executable) 'Songs'
  if(-not (Test-Path -LiteralPath (Join-Path $catalogDir 'catalog.db'))){throw "Cold-start validation requires a catalogue beside the executable or -ExpectedBuiltins."}
  $ExpectedBuiltins=(Get-ChildItem -LiteralPath $catalogDir -Filter '*.json' -File | Measure-Object).Count
  if($ExpectedBuiltins -lt 1){throw "Cold-start catalogue contains no score JSON files."}
}
$OutputRoot=[IO.Path]::GetFullPath($OutputRoot)
if(Test-Path -LiteralPath $OutputRoot){throw "Use a new isolated output directory; refusing to overwrite: $OutputRoot"}
if($OutputRoot.Contains('"')){throw 'Output directory cannot contain a quote.'}
New-Item -ItemType Directory -Path $OutputRoot | Out-Null
$si=[Diagnostics.ProcessStartInfo]::new()
$si.FileName=$Executable; $si.WorkingDirectory=Split-Path -Parent $Executable
$si.UseShellExecute=$false; $si.CreateNoWindow=$true; $si.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden
$si.RedirectStandardOutput=$true; $si.RedirectStandardError=$true
$si.Arguments='--ui-test '+$(if($Mode -eq 'cold-start'){'--capture-only --expected-builtins '+$ExpectedBuiltins+' '}else{''})+'--data-dir "'+(Join-Path $OutputRoot 'UserData')+'"'
if($Mode -eq 'preparation'){$si.Arguments+=' --preparation-validation'}
if($Mode -eq 'scroll'){$si.Arguments+=' --scroll-validation'}
if($Mode -eq 'scale'){$si.Arguments+=' --scale-validation --catalog-dir "'+$CatalogDirectory+'"'}
$si.EnvironmentVariables.Remove('DOTNET_ROOT')
$si.EnvironmentVariables['DOTNET_CLI_TELEMETRY_OPTOUT']='1'
$si.EnvironmentVariables['DOTNET_NOLOGO']='1'
$si.EnvironmentVariables['DOTNET_GENERATE_ASPNET_CERTIFICATE']='false'
$p=[Diagnostics.Process]::new(); $p.StartInfo=$si
[void]$p.Start(); $ownedPid=$p.Id
if(-not $p.WaitForExit(90000)){throw "Validation timed out; inspect only the launched process PID $ownedPid. No unrelated process was stopped."}
$code=$p.ExitCode; $utf8=[Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $OutputRoot 'stdout.log'),$p.StandardOutput.ReadToEnd(),$utf8)
[IO.File]::WriteAllText((Join-Path $OutputRoot 'stderr.log'),$p.StandardError.ReadToEnd(),$utf8)
$run=[ordered]@{date=(Get-Date).ToString('o');executable=$Executable;sha256=(Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash;pid=$ownedPid;exitCode=$code;arguments=$si.Arguments;dotnetRootInChild=$null;runtime='self-contained Windows x64'}
[IO.File]::WriteAllText((Join-Path $OutputRoot 'run.json'),($run | ConvertTo-Json),$utf8)
$p.Dispose()
if($code -ne 0){throw "Validation exit code $code; see $OutputRoot"}
$report=Join-Path $OutputRoot $(if($Mode -eq 'ui'){'ui-test-report.json'}elseif($Mode -eq 'scale'){'scale-ui-report.json'}elseif($Mode -eq 'preparation'){'preparation-ui-report.json'}elseif($Mode -eq 'scroll'){'scroll-ui-report.json'}else{'cold-start-report.json'})
if(-not (Test-Path -LiteralPath $report)){throw "No report was written: $report"}
$r=Get-Content -LiteralPath $report -Encoding UTF8 | ConvertFrom-Json
if($r.nativeSendAttempts -ne 0){throw 'Unexpected native keyboard attempt in isolated validation.'}
if($Mode -in @('ui','scale','preparation','scroll') -and $r.failures -ne 0){throw 'UI cases failed; inspect the report.'}
if($Mode -eq 'cold-start' -and ($r.expectedBuiltinScores -ne $ExpectedBuiltins -or $r.builtinScores -ne $ExpectedBuiltins)){throw "Unexpected built-in score count: expected $ExpectedBuiltins, report expected $($r.expectedBuiltinScores), observed $($r.builtinScores)."}
Write-Output ("PASS portable $Mode; exit=$code; native attempts=0; report=$report")
