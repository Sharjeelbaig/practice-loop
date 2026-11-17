#!/usr/bin/env bash
# Install practice-loop as an agent skill.
#
#   ./install.sh                 # user scope, into ~/.agents/skills + ~/.claude/skills
#   ./install.sh --project .     # project scope, into ./.agents/skills + ./.claude/skills
#   ./install.sh --copy          # copy instead of clone (offline / tarball)
#   ./install.sh --force         # replace an existing install
#   ./install.sh --bin           # also link the CLI into ~/.local/bin
#
# Environment:
#   PRACTICE_LOOP_REPO   git URL to clone (default: the public repo)
#   HOME                 respected for all user-scope paths

set -euo pipefail

REPO_URL="${PRACTICE_LOOP_REPO:-https://github.com/Sharjeelbaig/practice-loop.git}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

MODE="user"
PROJECT_DIR=""
COPY=0
FORCE=0
WANT_BIN=0

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project) MODE="project"; PROJECT_DIR="${2:-}"; shift 2 ;;
    --copy) COPY=1; shift ;;
    --force) FORCE=1; shift ;;
    --bin) WANT_BIN=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || say "warning: python3 not found; the skill needs it to run"
command -v git >/dev/null 2>&1 || true

if [ "$MODE" = "project" ]; then
  [ -n "$PROJECT_DIR" ] || die "--project needs a directory"
  [ -d "$PROJECT_DIR" ] || die "not a directory: $PROJECT_DIR"
  ROOT="$(cd "$PROJECT_DIR" && pwd)"
  AGENTS_DEST="$ROOT/.agents/skills/practice-loop"
  CLAUDE_DEST="$ROOT/.claude/skills/practice-loop"
else
  ROOT="$HOME"
  AGENTS_DEST="$HOME/.agents/skills/practice-loop"
  CLAUDE_DEST="$HOME/.claude/skills/practice-loop"
fi

mkdir -p "$(dirname "$AGENTS_DEST")"

install_from_source() {
  mkdir -p "$AGENTS_DEST"
  # Copy the skill payload only; leave repo docs, tests, and .git behind.
  rm -rf "$AGENTS_DEST/references" "$AGENTS_DEST/scripts" 2>/dev/null || true
  cp -R "$SOURCE_DIR/SKILL.md" "$SOURCE_DIR/references" "$SOURCE_DIR/scripts" "$AGENTS_DEST/"
  find "$AGENTS_DEST" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$AGENTS_DEST" -type f -name '*.pyc' -delete 2>/dev/null || true
}

install_from_remote() {
  if [ -d "$AGENTS_DEST/.git" ]; then
    say "updating $AGENTS_DEST"
    git -C "$AGENTS_DEST" pull --ff-only
  elif [ -e "$AGENTS_DEST" ] && [ "$(ls -A "$AGENTS_DEST" 2>/dev/null)" ]; then
    if [ "$FORCE" -eq 1 ]; then
      rm -rf "$AGENTS_DEST"
      git clone --depth 1 "$REPO_URL" "$AGENTS_DEST"
    else
      die "$AGENTS_DEST exists; re-run with --force or --copy to replace it"
    fi
  else
    git clone --depth 1 "$REPO_URL" "$AGENTS_DEST"
  fi
}

if [ "$COPY" -eq 1 ] || [ "$MODE" = "project" ]; then
  [ -f "$SOURCE_DIR/SKILL.md" ] \
    || die "--copy and --project must run from a practice-loop checkout"
  say "installing from $SOURCE_DIR"
  install_from_source
elif [ -f "$SOURCE_DIR/SKILL.md" ] && [ -d "$SOURCE_DIR/.git" ]; then
  # A checkout installs the published copy so `git pull` keeps it current.
  say "installing from $REPO_URL"
  install_from_remote
elif [ -f "$SOURCE_DIR/SKILL.md" ]; then
  say "installing from $SOURCE_DIR"
  install_from_source
else
  say "installing from $REPO_URL"
  install_from_remote
fi

[ -f "$AGENTS_DEST/SKILL.md" ] || die "install failed: $AGENTS_DEST/SKILL.md missing"

# Claude Code reads ~/.claude/skills; Codex and OpenCode read ~/.agents/skills.
mkdir -p "$(dirname "$CLAUDE_DEST")"
if [ -L "$CLAUDE_DEST" ]; then
  rm -f "$CLAUDE_DEST"
elif [ -e "$CLAUDE_DEST" ]; then
  if [ "$FORCE" -eq 1 ]; then
    rm -rf "$CLAUDE_DEST"
  else
    say "note: $CLAUDE_DEST exists and is not a symlink; leaving it alone (use --force to replace)"
  fi
fi
if [ ! -e "$CLAUDE_DEST" ]; then
  if ln -sfn "$AGENTS_DEST" "$CLAUDE_DEST" 2>/dev/null; then
    :
  else
    cp -R "$AGENTS_DEST" "$CLAUDE_DEST"
  fi
fi

if [ "$WANT_BIN" -eq 1 ] && [ "$MODE" = "user" ]; then
  mkdir -p "$HOME/.local/bin"
  chmod +x "$AGENTS_DEST/scripts/practice_loop.py" 2>/dev/null || true
  ln -sfn "$AGENTS_DEST/scripts/practice_loop.py" "$HOME/.local/bin/practice-loop"
  say "linked CLI: $HOME/.local/bin/practice-loop"
fi

say ""
say "installed: $AGENTS_DEST"
say "claude:    $CLAUDE_DEST"
say ""
say "detected hosts:"
for cmd in opencode claude codex; do
  if command -v "$cmd" >/dev/null 2>&1; then
    say "  - $cmd ($(command -v "$cmd"))"
  fi
done
say ""

if command -v python3 >/dev/null 2>&1; then
  python3 "$AGENTS_DEST/scripts/practice_loop.py" --help >/dev/null || die "CLI failed to start"
  say "CLI check: ok"
fi

cat <<'EOF'
Next:
  1. Restart or reload your agent so it discovers the skill.
  2. In an empty practice folder:  @practice-loop init
     (Claude Code: /practice-loop init   Codex: $practice-loop init)
  3. Then:  @practice-loop start
EOF
