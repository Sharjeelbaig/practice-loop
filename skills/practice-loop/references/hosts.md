# Install and invocation per host

This is an agent skill, not a plugin with a server. One folder of Markdown and
one Python script. It runs anywhere the host can read files and run a shell.

Canonical install location:

```text
~/.agents/skills/practice-loop/
```

Codex and OpenCode both read `~/.agents/skills` natively. Claude Code reads
`~/.claude/skills`, so the installer adds a symlink there. One clone, three
hosts, one progress folder per workspace.

## Install

macOS / Linux:

```bash
git clone https://github.com/Sharjeelbaig/practice-loop.git ~/.agents/skills/practice-loop
mkdir -p ~/.claude/skills
ln -sfn ~/.agents/skills/practice-loop ~/.claude/skills/practice-loop
```

Or use the installer, which does the same and verifies the result:

```bash
curl -fsSL https://raw.githubusercontent.com/Sharjeelbaig/practice-loop/main/install.sh | bash
```

Project-local install (checked into a repo, shared with a team):

```bash
./install.sh --project .
# creates .agents/skills/practice-loop and .claude/skills/practice-loop
```

Windows (PowerShell):

```powershell
git clone https://github.com/Sharjeelbaig/practice-loop.git "$HOME\.agents\skills\practice-loop"
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse -Force "$HOME\.agents\skills\practice-loop" "$HOME\.claude\skills\practice-loop"
```

## Where each host looks

| Host | User scope | Project scope |
| --- | --- | --- |
| OpenCode | `~/.config/opencode/skills/`, `~/.agents/skills/`, `~/.claude/skills/` | `.opencode/skills/`, `.agents/skills/`, `.claude/skills/` |
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Codex | `~/.agents/skills/` | `.agents/skills/` (scanned up to the repo root) |
| Other agentskills.io hosts | whatever they document | same |

The folder name is the skill id: `practice-loop`. The frontmatter `name` is a
display label only.

## Invoke

| Host | Explicit | Implicit |
| --- | --- | --- |
| OpenCode | `@practice-loop start` | "quiz me on SQL" when the description matches |
| Claude Code | `/practice-loop start` | same |
| Codex | `$practice-loop start`, or `/skills` then pick it | same |
| Text-only | paste `SKILL.md` and say "follow this" | not applicable |

The command after the skill name is the argument: `@practice-loop init`,
`@practice-loop teach sql`, `@practice-loop report`.

If the host exposes the skill through a plugin namespace, the command is
prefixed (`/practice-loop:practice-loop`). The clone install above avoids that.

## Interactive question tool

| Host | Tool | Fallback |
| --- | --- | --- |
| OpenCode | `question` | numbered options |
| Claude Code | `AskUserQuestion` | numbered options |
| Codex | none | numbered options in plain text |
| Generic | whatever is available | numbered options |

Use the tool for MCQs and setup choices. Never use it for code or SQL answers —
those need free text.

## Shell

All three hosts expose a shell tool. Use it for the CLI. Keep commands short and
quote paths. Never construct a command by interpolating learner text; write
answers to files and pass paths.

## Path resolution inside the skill

When the skill loads, the host reports its base directory (OpenCode and Claude
Code both do; Codex lists the skill's path). Use that. Fallbacks in order:

1. `$SKILL_DIR` if the host set it.
2. The directory containing the `SKILL.md` you were given.
3. `~/.agents/skills/practice-loop`.
4. `~/.claude/skills/practice-loop`.
5. `practice-loop` on `PATH`.

If none resolve, ask the learner where they installed it. Do not guess more than
once.

## Update

```bash
git -C ~/.agents/skills/practice-loop pull --ff-only
```

Progress lives in workspaces, not in the skill folder, so updates never touch
learner data. Restart the host or reload plugins if the new version does not
appear.

## Uninstall

```bash
rm -rf ~/.agents/skills/practice-loop ~/.claude/skills/practice-loop
```

Workspaces are untouched. Delete them separately if the learner wants that.

## Troubleshooting

**The skill is not in the list.** Check the file is exactly
`<skill-dir>/SKILL.md` with `name` and `description` frontmatter. Restart the
host. In OpenCode, confirm the selected agent has `skill` permission and the
skill is not hidden with `metadata.opencode/autoinvoke: false`.

**Two copies appear.** `~/.agents/skills` and `~/.config/opencode/skills` can
both define `practice-loop`; the higher-precedence one wins. Remove the extra
copy rather than debugging which loaded.

**`python3: command not found`.** Try `python --version`. On Windows try `py -3`.
If Python is genuinely absent, tell the learner; do not install software without
asking. Until then, use the no-shell fallback in `state.md`.

**`no practice-loop workspace`.** Run `init` in the folder they want to practise
in, or pass `--workspace /path/to/workspace`.

**A question is stuck pending.** `status --json` shows it. Either re-ask that
slot or `record --result skipped`. Never delete `state.json` to clear it.

**Progress does not follow between hosts.** It will, if both hosts open the same
workspace folder. It will not if each session starts in a different directory
without `--workspace`.
