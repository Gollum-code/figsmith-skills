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

function Copy-File {
    param([string]$Src, [string]$Dst)
    if (-not (Test-Path -LiteralPath $Src)) { return }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dst) | Out-Null
    Copy-Item -LiteralPath $Src -Destination $Dst -Force
}

Write-Host "installing figsmith ($mode) -> $Dest"

# core and backends are always installed
Copy-Tree (Join-Path $RepoRoot "core") $Dest\core
Copy-Tree (Join-Path $RepoRoot "backends") $Dest\backends
Copy-File (Join-Path $RepoRoot "README.md") $Dest\README.md
# The verification commands in AGENTS.md section 4 run against the installed tree, so
# the tree needs the modules they invoke. tools/ is what `python tools/regress.py` needs;
# tests/ is what `python tests/test_verify.py` needs.
Copy-Tree (Join-Path $RepoRoot "tools") $Dest\tools
Copy-Tree (Join-Path $RepoRoot "tests") $Dest\tests
Copy-File (Join-Path $RepoRoot "requirements.txt") $Dest\requirements.txt
Copy-File (Join-Path $RepoRoot "AGENTS.md") $Dest\AGENTS.md
Copy-Tree (Join-Path $RepoRoot "docs") $Dest\docs
# The router is installed in every mode, so it needs the merged catalog to answer from.
# Shipping only the index (not the whole gallery/) keeps a core-only install minimal.
$catalogIndex = Join-Path $RepoRoot "gallery\catalog.json"
if (Test-Path -LiteralPath $catalogIndex) {
    New-Item -ItemType Directory -Force -Path "$Dest\gallery" | Out-Null
    Copy-File $catalogIndex "$Dest\gallery\catalog.json"
}

if ($mode -eq "full") {
    Copy-Tree (Join-Path $RepoRoot "domains") $Dest\domains
    Copy-Tree (Join-Path $RepoRoot "examples") $Dest\examples
    Copy-Tree (Join-Path $RepoRoot "gallery") $Dest\gallery
} elseif ($mode -like "domain:*") {
    Copy-Tree (Join-Path $RepoRoot "domains\$Domain") "$Dest\domains\$Domain"
    if (Test-Path -LiteralPath (Join-Path $RepoRoot "examples\$Domain")) {
        Copy-Tree (Join-Path $RepoRoot "examples\$Domain") "$Dest\examples\$Domain"
    }
}

Write-Host ""
Write-Host "done. installed:"
Write-Host "  core\       METHOD.md, IR.md, tokens\, probe\, verify\"
Write-Host "  backends\   svg, png, mpl2svg, pdf, drawio, pptx, html2pdf"
Write-Host "  tools\      router, regression, gallery, four-way, pipeline"
Write-Host "  tests\      fixtures, blessed baselines, unit tests"
Write-Host "  docs\       cookbook, spike notes, vision probe report"
switch -Wildcard ($mode) {
    "full"        { Write-Host "  domains\    all 7 domain packages"; Write-Host "  examples\   regenerable cases"; Write-Host "  gallery\    offline chart-type gallery" }
    "domain:*"    { Write-Host "  domains\    $Domain"; Write-Host "  examples\   $Domain cases (if any)" }
}
Write-Host ""
Write-Host "verify: cd $Dest; python tools/regress.py; python tests/test_verify.py"
Write-Host ""
Write-Host "the agent finds this via SKILL.md. see AGENTS.md for host-specific notes."
