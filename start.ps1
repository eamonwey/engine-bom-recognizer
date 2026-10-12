$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& python -X utf8 -m engine_bom.webapp --host 127.0.0.1 --port 8788
