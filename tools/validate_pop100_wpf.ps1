param([Parameter(Mandatory=$true)][string]$Executable,[Parameter(Mandatory=$true)][string]$OutputRoot,[int]$ExpectedBuiltins=132,[string]$CatalogDirectory='', [string]$Instrument='windsong')
$ErrorActionPreference='Stop'
$Executable=[IO.Path]::GetFullPath($Executable);$OutputRoot=[IO.Path]::GetFullPath($OutputRoot)
if(Test-Path -LiteralPath $OutputRoot){throw 'Use a new isolated output directory'}
if($OutputRoot.Contains('"') -or $Executable.Contains('"') -or $CatalogDirectory.Contains('"')){throw 'Quotes in paths are unsupported'}
New-Item -ItemType Directory -Path (Join-Path $OutputRoot 'UserData') -Force | Out-Null
$utf8=[Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $OutputRoot 'UserData\preferences.json'),(@{volume=0;queueAuto=$false;instrumentId=$Instrument}|ConvertTo-Json),$utf8)
$si=[Diagnostics.ProcessStartInfo]::new();$si.FileName=$Executable;$si.WorkingDirectory=Split-Path -Parent $Executable
$si.UseShellExecute=$false;$si.CreateNoWindow=$true;$si.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden
$si.RedirectStandardOutput=$true;$si.RedirectStandardError=$true
$si.Arguments='--ui-test --capture-only --expected-builtins '+$ExpectedBuiltins+' --data-dir "'+(Join-Path $OutputRoot 'UserData')+'"'
if($CatalogDirectory){$CatalogDirectory=[IO.Path]::GetFullPath($CatalogDirectory);$si.Arguments+=' --catalog-dir "'+$CatalogDirectory+'"'}
$si.EnvironmentVariables.Remove('DOTNET_ROOT');$si.EnvironmentVariables['DOTNET_CLI_TELEMETRY_OPTOUT']='1';$si.EnvironmentVariables['DOTNET_NOLOGO']='1'
$sw=[Diagnostics.Stopwatch]::StartNew();$p=[Diagnostics.Process]::new();$p.StartInfo=$si;[void]$p.Start();$ownedPid=$p.Id
if(-not $p.WaitForExit(60000)){$p.Kill();throw "Owned isolated validation PID $ownedPid timed out; user processes not stopped"}
$code=$p.ExitCode;[IO.File]::WriteAllText((Join-Path $OutputRoot 'stdout.log'),$p.StandardOutput.ReadToEnd(),$utf8);[IO.File]::WriteAllText((Join-Path $OutputRoot 'stderr.log'),$p.StandardError.ReadToEnd(),$utf8)
$run=@{executable=$Executable;exeSha256=(Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash;arguments=$si.Arguments;pid=$ownedPid;exitCode=$code;elapsedMs=$sw.Elapsed.TotalMilliseconds;instrument=$Instrument;actualUserDataUsed=$false;dotnetRootInChild=$null}
[IO.File]::WriteAllText((Join-Path $OutputRoot 'run.json'),($run|ConvertTo-Json),$utf8);$p.Dispose()
if($code -ne 0){throw "Cold/render validation failed exit=$code"}
$r=Get-Content -LiteralPath (Join-Path $OutputRoot 'cold-start-report.json') -Encoding UTF8|ConvertFrom-Json
if($r.builtinScores -ne $ExpectedBuiltins -or $r.nativeSendAttempts -ne 0 -or $r.scoreReads -ne 1 -or $r.firstPageItems -ne [Math]::Min(50,$ExpectedBuiltins)){throw 'Unexpected count, eager reads or native input'}
Write-Output "PASS cold/render: $ExpectedBuiltins builtins; first page=$($r.firstPageItems); reads=1; native=0; instrument=$Instrument; $OutputRoot"
