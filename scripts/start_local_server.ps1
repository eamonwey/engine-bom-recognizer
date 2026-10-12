$ErrorActionPreference = 'Stop'
$bomProjectPath = Split-Path -Parent $PSScriptRoot
$bomListener = Get-NetTCPConnection -LocalPort 8788 -State Listen -ErrorAction SilentlyContinue
if ($bomListener) {
    Write-Host 'Local service already listening: http://127.0.0.1:8788/'
    exit 0
}
$bomPythonPath = (Get-Command python -ErrorAction Stop).Source
$bomLogPath = Join-Path $bomProjectPath 'data\server_logs'
New-Item -ItemType Directory -Path $bomLogPath -Force | Out-Null
$bomServerProcess = Start-Process -FilePath $bomPythonPath -ArgumentList '-u','-X','utf8','-m','engine_bom.webapp','--host','127.0.0.1','--port','8788' -WorkingDirectory $bomProjectPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $bomLogPath 'web.stdout.log') -RedirectStandardError (Join-Path $bomLogPath 'web.stderr.log') -PassThru
Write-Host "Started local service (PID $($bomServerProcess.Id)): http://127.0.0.1:8788/"
