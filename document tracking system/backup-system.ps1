$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupRoot = Join-Path $projectRoot "backups"
$targetDir = Join-Path $backupRoot $timestamp

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

$databasePath = Join-Path $projectRoot "db.sqlite3"
$mediaPath = Join-Path $projectRoot "media"

if (Test-Path $databasePath) {
    Copy-Item -LiteralPath $databasePath -Destination (Join-Path $targetDir "db.sqlite3") -Force
}

if (Test-Path $mediaPath) {
    Copy-Item -LiteralPath $mediaPath -Destination (Join-Path $targetDir "media") -Recurse -Force
}

Write-Host "Backup created at: $targetDir"
