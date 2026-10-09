param([ValidateSet('smart','baseline','audition','cold')][string]$Mode,[Parameter(Mandatory=$true)][string]$Tag,[string]$Executable='')
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'));$batch=Join-Path $repo '.validation\smart-interludes-2026-10-06'
if(!$Executable){$Executable=Join-Path $batch 'publish\QinBan.exe'}
$out=[IO.Path]::GetFullPath((Join-Path $batch $Tag))
if(!$out.StartsWith($batch+'\',[StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $out)){throw 'Use a NEW output tag within the current batch'}
[IO.Directory]::CreateDirectory($out)|Out-Null;$data=Join-Path $out 'data';$utf8=[Text.UTF8Encoding]::new($false)
$catalog=Join-Path $repo 'Songs'
if($Mode -eq 'baseline'){$catalog=Join-Path $repo '.validation\pop100-baseline-2026-10-06\source-snapshot\Songs'}
elseif($Mode -eq 'audition'){$catalog=Join-Path $repo '.validation\pop100-2026-10-06\original32-baseline'}
if(!(Test-Path -LiteralPath (Join-Path $catalog 'catalog.db'))){throw 'Missing fixture catalog'}
$arguments='--ui-test --data-dir "'+$data+'" --catalog-dir "'+$catalog+'"'
if($Mode -eq 'smart'){$arguments+=' --smart-interlude-validation';$report=Join-Path $data 'smart-interlude-validation\smart-interlude-ui-report.json'}
else{
 [IO.Directory]::CreateDirectory($data)|Out-Null;[IO.File]::WriteAllText((Join-Path $data 'preferences.json'),'{"volume":0,"queueAuto":false,"instrumentId":"windsong"}',$utf8)
 if($Mode -eq 'cold'){$arguments+=' --capture-only --expected-builtins 132';$report=Join-Path $out 'cold-start-report.json'}
 elseif($Mode -eq 'audition'){$arguments+=' --audition-validation';$report=Join-Path $out 'audition-ui-report.json'}
 else{$report=Join-Path $out 'ui-test-report.json'}
}
$info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=[IO.Path]::GetFullPath($Executable);$info.WorkingDirectory=Split-Path $Executable
$info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden
$info.Arguments=$arguments;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
$info.EnvironmentVariables.Remove('DOTNET_ROOT');$info.EnvironmentVariables['DOTNET_CLI_TELEMETRY_OPTOUT']='1'
foreach($name in @('TEMP','TMP','DOTNET_BUNDLE_EXTRACT_BASE_DIR')){
 $location=Join-Path $out $name;[IO.Directory]::CreateDirectory($location)|Out-Null;$info.EnvironmentVariables[$name]=$location
}
$watch=[Diagnostics.Stopwatch]::StartNew();$process=[Diagnostics.Process]::new();$process.StartInfo=$info
[void]$process.Start();$owned=$process.Id;$stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
if(!$process.WaitForExit(180000)){$process.Kill();throw "Owned isolated validation PID $owned timed out; user processes untouched"}
$code=$process.ExitCode;[IO.File]::WriteAllText((Join-Path $out 'stdout.log'),$stdout.Result,$utf8);[IO.File]::WriteAllText((Join-Path $out 'stderr.log'),$stderr.Result,$utf8)
[IO.File]::WriteAllText((Join-Path $out 'run.json'),(@{mode=$Mode;executable=$Executable;exeSha256=(Get-FileHash $Executable).Hash;pid=$owned;arguments=$arguments;exitCode=$code;elapsedMs=$watch.Elapsed.TotalMilliseconds;report=$report;realUserDataUsed=$false;audio='muted';nativeInput='prohibited'}|ConvertTo-Json),$utf8)
$process.Dispose()
if(!(Test-Path -LiteralPath $report)){throw "Missing validation report (exit=$code): $report"}
$r=Get-Content -LiteralPath $report -Raw -Encoding UTF8|ConvertFrom-Json
if($code -ne 0 -or $r.failures -gt 0 -or $r.nativeSendAttempts -ne 0){$r.results|Where-Object {$_.status -ne 'PASS'}|ConvertTo-Json -Depth 8;throw "$Mode validation failed exit=$code failures=$($r.failures)"}
if($Mode -eq 'cold' -and ($r.builtinScores -ne 132 -or $r.firstPageItems -ne 50 -or $r.scoreReads -ne 1)){throw 'Cold counts/eager reads incorrect'}
Write-Output "PASS $Mode cases=$($r.cases) failures=$($r.failures) native=$($r.nativeSendAttempts) ms=$([Math]::Round($watch.Elapsed.TotalMilliseconds)) report=$report"