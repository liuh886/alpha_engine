param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Runtime,
    [Parameter(Mandatory=$true)][string]$Episode,
    [string]$Proxy = 'http://127.0.0.1:7900'
)
$ErrorActionPreference = 'Stop'
$taskName = 'AlphaEngine-E7-Rules-Paper'
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$runtimePath = (Resolve-Path -LiteralPath $Runtime).Path
$episodePath = (Resolve-Path -LiteralPath $Episode).Path
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'E7 task already exists; inspect its immutable episode before replacing it.'
}
if (-not (Test-Path -LiteralPath (Join-Path $episodePath 'registration.json'))) {
    throw 'Initialize the independent E7 episode before installing automation.'
}
Push-Location $runtimePath
try {
    & $pythonPath -m src.research.e7_paper_daily status --root $episodePath
    if ($LASTEXITCODE -ne 0) { throw 'Frozen runtime/episode identity preflight failed.' }
} finally { Pop-Location }
$deployment = Join-Path $episodePath 'deployment'
New-Item -ItemType Directory -Force -Path $deployment | Out-Null
$launcher = Join-Path $deployment 'run-e7.ps1'
# All interpolated values are local deployment paths; quote literal apostrophes.
$pyLiteral = $pythonPath.Replace("'", "''")
$runtimeLiteral = $runtimePath.Replace("'", "''")
$episodeLiteral = $episodePath.Replace("'", "''")
$proxyLiteral = $Proxy.Replace("'", "''")
$content = @"
`$ErrorActionPreference = 'Stop'
`$e7Episode = '$episodeLiteral'
`$e7Jobs = Join-Path `$e7Episode 'jobs'
New-Item -ItemType Directory -Force -Path `$e7Jobs | Out-Null
`$e7Run = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ') + '-' + [Guid]::NewGuid().ToString('N')
`$e7Log = Join-Path `$e7Jobs (`$e7Run + '.log')
`$e7Started = [DateTime]::UtcNow.ToString('o')
`$e7Exit = 11
try {
    Set-Location -LiteralPath '$runtimeLiteral'
    `$env:HTTPS_PROXY = '$proxyLiteral'
    `$env:HTTP_PROXY = '$proxyLiteral'
    `$ErrorActionPreference = 'Continue'
    & '$pyLiteral' -m src.research.e7_paper_daily run --root `$e7Episode *> `$e7Log
    `$e7Exit = `$LASTEXITCODE
    `$ErrorActionPreference = 'Stop'
} catch {
    `$_ | Out-String | Add-Content -LiteralPath `$e7Log
} finally {
    `$e7Result = @{ started_at_utc=`$e7Started; completed_at_utc=[DateTime]::UtcNow.ToString('o');
        exit_code=`$e7Exit; log_name=[IO.Path]::GetFileName(`$e7Log);
        log_sha256=(Get-FileHash -LiteralPath `$e7Log -Algorithm SHA256).Hash.ToLowerInvariant();
        research_only=`$true; trade_ready=`$false }
    `$e7Result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path `$e7Jobs (`$e7Run + '.json')) -Encoding UTF8
}
exit `$e7Exit
"@
Set-Content -LiteralPath $launcher -Value $content -Encoding UTF8
$start = [DateTime]::UtcNow.Date.AddHours(22)
if ($start -le [DateTime]::UtcNow) { $start = $start.AddDays(1) }
$boundary = $start.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$identityXml = [Security.SecurityElement]::Escape($identity)
$argumentsXml = [Security.SecurityElement]::Escape("-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`"")
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Frozen E7 rules-only private paper evidence. No broker, model fitting or historical backfill.</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>$boundary</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
  <Principals><Principal id="Owner"><UserId>$identityXml</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><Enabled>true</Enabled><WakeToRun>true</WakeToRun><ExecutionTimeLimit>PT20M</ExecutionTimeLimit><RestartOnFailure><Interval>PT30M</Interval><Count>2</Count></RestartOnFailure></Settings>
  <Actions Context="Owner"><Exec><Command>powershell.exe</Command><Arguments>$argumentsXml</Arguments></Exec></Actions>
</Task>
"@
$null = Register-ScheduledTask -TaskName $taskName -Xml $xml
$definition = Export-ScheduledTask -TaskName $taskName
Set-Content -LiteralPath (Join-Path $deployment 'task-definition.xml') -Value $definition -Encoding Unicode
$result = @{ task_name=$taskName; status='INSTALLED'; schedule_utc='22:00 daily';
    logon_requirement='current user signed in'; wake_to_run=$true; start_when_available=$true;
    launcher_sha256=(Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash.ToLowerInvariant();
    task_xml_sha256=(Get-FileHash -LiteralPath (Join-Path $deployment 'task-definition.xml') -Algorithm SHA256).Hash.ToLowerInvariant();
    research_only=$true; trade_ready=$false }
$result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $deployment 'installation.json') -Encoding UTF8
$result | ConvertTo-Json
