# FigSmith installer (Windows PowerShell)
#
#   .\install.ps1                            # full install (all domains)
#   .\install.ps1 -CoreOnly                  # core + backends only
#   .\install.ps1 -Domain paper-figure       # core + one domain
#   .\install.ps1 -Target "$HOME\.claude\skills"
#
# The skill tree is plain files; installing means copying it where the host agent
# scans for SKILL.md. Nothing is compiled, nothing is registered.

[CmdletBinding()]
param(
    [switch]$CoreOnly,
    [string]$Domain,
    [string]$Target = (Join-Path $HOME ".claude\skills")
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot

if ($CoreOnly -and $Domain) {
    Write-Error "-CoreOnly and -Domain are mutually exclusive"
    exit 2
}

if ($Domain) {
    $domainPath = Join-Path $RepoRoot "domains\$Domain"
    if (-not (Test-Path -LiteralPath $domainPath)) {
        Write-Error "no such domain: $Domain. available: $((Get-ChildItem (Join-Path $RepoRoot 'domains') -Directory).Name -join ', ')"
        exit 2
    }
    $mode = "domain:$Domain"
} elseif ($CoreOnly) {
    $mode = "core"
} else {
    $mode = "full"
}

$Dest = Join-Path $Target "figsmith"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

function Copy-Tree {
    param([string]$Src, [string]$Dst)
    if (-not (Test-Path -LiteralPath $Src)) { return }
    New-Item -ItemType Directory -Force -Path $Dst | Out-Null
    Copy-Item -Path (Join-Path $Src "*") -Destination $Dst -Recurse -Force
}

Write-Host "installing figsmith ($mode) -> $Dest"

# core and backends are always installed
Copy-Tree (Join-Path $RepoRoot "core") $Dest\core
Copy-Tree (Join-Path $RepoRoot "backends") $Dest\backends
Copy-Item -LiteralPath (Join-Path $RepoRoot "README.md") -Destination $Dest -Force

if ($mode -eq "full") {
    Copy-Tree (Join-Path $RepoRoot "domains") $Dest\domains
    Copy-Tree (Join-Path $RepoRoot "examples") $Dest\examples
    Copy-Tree (Join-Path $RepoRoot "gallery") $Dest\gallery
} elseif ($mode -like "domain:*") {
    Copy-Tree (Join-Path $RepoRoot "domains\$Domain") "$Dest\domains\$Domain"
    Copy-Tree (Join-Path $RepoRoot "examples\$Domain") "$Dest\examples\$Domain"
}

Write-Host ""
Write-Host "done. installed:"
Write-Host "  core\       METHOD.md, IR.md, tokens\, probe\, verify\"
Write-Host "  backends\   svg, png, mpl2svg, pdf, drawio, pptx"
switch -Wildcard ($mode) {
    "full"        { Write-Host "  domains\    all 7 domain packages"; Write-Host "  examples\   regenerable cases" }
    "domain:*"    { Write-Host "  domains\    $Domain"; Write-Host "  examples\   $Domain cases (if any)" }
}
Write-Host ""
Write-Host "the agent finds this via SKILL.md. see AGENTS.md for host-specific notes."
