# Install practice-loop as an agent skill (Windows PowerShell).
#
#   .\install.ps1              # user scope
#   .\install.ps1 -Project .   # project scope
#   .\install.ps1 -Copy        # copy from this checkout instead of cloning
#   .\install.ps1 -Force       # replace an existing install
#   .\install.ps1 -Bin         # print the CLI path
#
# Environment:
#   PRACTICE_LOOP_REPO   git URL to clone (default: the public repo)

param(
  [string]$Project = "",
  [switch]$Copy,
  [switch]$Force,
  [switch]$Bin
)

$ErrorActionPreference = "Stop"
$RepoUrl = if ($env:PRACTICE_LOOP_REPO) { $env:PRACTICE_LOOP_REPO } else { "https://github.com/Sharjeelbaig/practice-loop.git" }
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HasPayload = Test-Path (Join-Path $SourceDir "SKILL.md")

$Root = if ($Project) { (Resolve-Path $Project).Path } else { $HOME }
$AgentsDest = if ($Project) { Join-Path $Root ".agents\skills\practice-loop" } else { Join-Path $HOME ".agents\skills\practice-loop" }
$ClaudeDest = if ($Project) { Join-Path $Root ".claude\skills\practice-loop" } else { Join-Path $HOME ".claude\skills\practice-loop" }

function Copy-Payload {
  New-Item -ItemType Directory -Force $AgentsDest | Out-Null
  Copy-Item -Force (Join-Path $SourceDir "SKILL.md") $AgentsDest
  Copy-Item -Recurse -Force (Join-Path $SourceDir "references") $AgentsDest
  Copy-Item -Recurse -Force (Join-Path $SourceDir "scripts") $AgentsDest
}

if ($Force -and (Test-Path $AgentsDest)) {
  Remove-Item -Recurse -Force $AgentsDest
}

if ((Test-Path $AgentsDest) -and -not $Force) {
  Write-Host "updating $AgentsDest"
  if ($HasPayload) { Copy-Payload } else { git -C $AgentsDest pull --ff-only }
} elseif ($Copy -or $Project) {
  if (-not $HasPayload) { throw "-Copy and -Project must run from a practice-loop checkout" }
  Copy-Payload
} elseif ($HasPayload -and (Test-Path (Join-Path $SourceDir ".git"))) {
  Write-Host "installing from $RepoUrl"
  git clone --depth 1 $RepoUrl $AgentsDest
} elseif ($HasPayload) {
  Copy-Payload
} else {
  Write-Host "installing from $RepoUrl"
  git clone --depth 1 $RepoUrl $AgentsDest
}

if (-not (Test-Path (Join-Path $AgentsDest "SKILL.md"))) {
  throw "install failed: $AgentsDest\SKILL.md missing"
}

New-Item -ItemType Directory -Force (Split-Path -Parent $ClaudeDest) | Out-Null
if (Test-Path $ClaudeDest) {
  if ($Force) {
    Remove-Item -Recurse -Force $ClaudeDest
  } else {
    Write-Host "note: $ClaudeDest exists; leaving it (use -Force)"
  }
}
if (-not (Test-Path $ClaudeDest)) {
  try {
    New-Item -ItemType SymbolicLink -Path $ClaudeDest -Target $AgentsDest -ErrorAction Stop | Out-Null
  } catch {
    Copy-Item -Recurse -Force $AgentsDest $ClaudeDest
  }
}

if ($Bin -and -not $Project) {
  Write-Host "CLI: $AgentsDest\scripts\practice_loop.py"
}

Write-Host ""
Write-Host "installed: $AgentsDest"
Write-Host "claude:    $ClaudeDest"
Write-Host ""
Write-Host "Next: restart your agent, then run:  `$practice-loop init"
