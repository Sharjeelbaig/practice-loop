# Install practice-loop as an agent skill (Windows PowerShell).
#
#   .\install.ps1              # user scope
#   .\install.ps1 -Project .   # project scope
#   .\install.ps1 -Force       # replace an existing install
#
# Environment:
#   PRACTICE_LOOP_REPO   git URL to clone (default: the public repo)

param(
  [string]$Project = "",
  [switch]$Force,
  [switch]$Bin
)

$ErrorActionPreference = "Stop"
$RepoUrl = if ($env:PRACTICE_LOOP_REPO) { $env:PRACTICE_LOOP_REPO } else { "https://github.com/Sharjeelbaig/practice-loop.git" }
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Project) {
  $Root = (Resolve-Path $Project).Path
} else {
  $Root = $HOME
}

$AgentsDest = if ($Project) { Join-Path $Root ".agents\skills\practice-loop" } else { Join-Path $HOME ".agents\skills\practice-loop" }
$ClaudeDest = if ($Project) { Join-Path $Root ".claude\skills\practice-loop" } else { Join-Path $HOME ".claude\skills\practice-loop" }

if (Test-Path $AgentsDest) {
  if ($Force) {
    Remove-Item -Recurse -Force $AgentsDest
  } else {
    Write-Host "updating $AgentsDest"
    Copy-Item -Recurse -Force (Join-Path $SourceDir "skills\practice-loop\*") $AgentsDest
  }
}

if (-not (Test-Path $AgentsDest)) {
  if (Test-Path (Join-Path $SourceDir ".git")) {
    New-Item -ItemType Directory -Force $AgentsDest | Out-Null
    Copy-Item -Recurse -Force (Join-Path $SourceDir "skills\practice-loop\*") $AgentsDest
  } else {
    git clone --depth 1 $RepoUrl $AgentsDest
  }
}

if (-not (Test-Path (Join-Path $AgentsDest "SKILL.md"))) {
  throw "install failed: $AgentsDest\SKILL.md missing"
}

New-Item -ItemType Directory -Force (Split-Path -Parent $ClaudeDest) | Out-Null
if (Test-Path $ClaudeDest) {
  if ($Force) { Remove-Item -Recurse -Force $ClaudeDest } else { Write-Host "note: $ClaudeDest exists; leaving it (use -Force)" }
}
if (-not (Test-Path $ClaudeDest)) {
  try {
    New-Item -ItemType SymbolicLink -Path $ClaudeDest -Target $AgentsDest -ErrorAction Stop | Out-Null
  } catch {
    Copy-Item -Recurse -Force $AgentsDest $ClaudeDest
  }
}

if ($Bin -and -not $Project) {
  New-Item -ItemType Directory -Force (Join-Path $HOME ".local\bin") | Out-Null
  Write-Host "CLI: $AgentsDest\scripts\practice_loop.py"
}

Write-Host ""
Write-Host "installed: $AgentsDest"
Write-Host "claude:    $ClaudeDest"
Write-Host ""
Write-Host "Next: restart your agent, then run:  `$practice-loop init"
