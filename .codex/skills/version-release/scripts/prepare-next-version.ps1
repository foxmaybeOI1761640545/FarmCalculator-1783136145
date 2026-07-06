[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$NextTag,
    [string]$Pattern = "v*.0.*",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:CurrentScriptDir = Split-Path -Parent $PSCommandPath

function Resolve-RepoRoot {
    $root = git rev-parse --show-toplevel
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($root)) { throw "Failed to resolve repository root." }
    return $root.Trim()
}

function Get-NextTag {
    param([string]$TagPattern)
    if (-not [string]::IsNullOrWhiteSpace($NextTag)) { return $NextTag.Trim() }
    $nextTagScript = Join-Path $script:CurrentScriptDir "next-release-tag.ps1"
    $raw = & powershell -ExecutionPolicy Bypass -File $nextTagScript -Pattern $TagPattern
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($raw -join ""))) { throw "Failed to compute next release tag." }
    return (($raw -join "`n").Trim())
}

function Parse-TagToVersion {
    param([Parameter(Mandatory = $true)][string]$Tag)
    if ($Tag -notmatch "^v(\d+)\.0\.(\d+)$") { throw "Tag '$Tag' does not match required format vX.0.Y." }
    return "$($Matches[1]).0.$($Matches[2])"
}

function Ensure-NoIllegalTextChars {
    param([Parameter(Mandatory = $true)][string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { throw "File contains UTF-8 BOM: $Path" }
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false, $true))
    if ($text.IndexOf([char]0xFFFD) -ge 0) { throw "File contains replacement character U+FFFD: $Path" }
    if ([regex]::IsMatch($text, "[\x00-\x08\x0B\x0C\x0E-\x1F]")) { throw "File contains disallowed control characters: $Path" }
}

$repoRoot = Resolve-RepoRoot
$resolvedTag = Get-NextTag -TagPattern $Pattern
$nextVersion = Parse-TagToVersion -Tag $resolvedTag

if (-not $DryRun) {
    Push-Location $repoRoot
    try {
        & npm version $nextVersion --no-git-tag-version
        if ($LASTEXITCODE -ne 0) { throw "npm version failed while setting version to $nextVersion." }
        & npm run verify:version
        if ($LASTEXITCODE -ne 0) { throw "Version verification failed after npm version." }
    } finally { Pop-Location }
}

foreach ($relative in @("package.json", "package-lock.json", "scripts/verify-release-version.mjs")) {
    $path = Join-Path $repoRoot $relative
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing file: $relative" }
    if (-not $DryRun) { Ensure-NoIllegalTextChars -Path $path }
}

$versionParts = $nextVersion.Split('.') | ForEach-Object { [int]$_ }
$versionCode = $versionParts[0] * 1000000 + $versionParts[2]
Write-Output "next_tag=$resolvedTag"
Write-Output "next_version=$nextVersion"
Write-Output "next_version_code=$versionCode"
Write-Output "updated_files=package.json,package-lock.json"
Write-Output "dry_run=$DryRun"
