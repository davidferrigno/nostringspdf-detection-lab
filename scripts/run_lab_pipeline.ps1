param(
    [string]$Manifest = "corpus/manifest.json",
    [string]$Out = "runs"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "runs/logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "pipeline-$Stamp.log"

Write-Host "Running lab pipeline..."
Write-Host "Log: $LogPath"

& py -3.13 scripts/run_lab_pipeline.py --manifest $Manifest --out $Out *> $LogPath
$ExitCode = $LASTEXITCODE

Get-Content $LogPath

if ($ExitCode -ne 0) {
    Write-Error "Lab pipeline failed with exit code $ExitCode"
    exit $ExitCode
}

$LatestScorecard = Join-Path $RepoRoot "$Out/latest/scorecard.md"
Write-Host "Latest scorecard: $LatestScorecard"
exit 0
