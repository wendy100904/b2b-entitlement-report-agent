param(
    [int]$Port = 8000
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$ip = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1 -ExpandProperty IPAddress

Write-Host "Starting LAN server on port $Port..." -ForegroundColor Cyan
if ($ip) {
    Write-Host "Share this address on the same network: http://${ip}:$Port" -ForegroundColor Green
} else {
    Write-Host "Could not detect a LAN IP address. Check your network connection." -ForegroundColor Yellow
}
Write-Host "If colleagues cannot connect, allow inbound TCP port $Port in Windows Firewall." -ForegroundColor Yellow

& $python -m uvicorn backend.main:app --host 0.0.0.0 --port $Port
