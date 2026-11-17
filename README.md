# practice-loop

An adaptive practice and teaching loop that any coding agent can run.

You bring a topic, a URL, a document, or your own notes. The agent quizzes you
one question at a time, rotates across subjects in a fixed order, grades what
you actually wrote, and remembers what you got wrong. It can also teach you the
material in small chunks — but teaching never counts as proof.

Works in **OpenCode**, **Claude Code**, **Codex**, and any other host that reads
[agent skills](https://agentskills.io). Progress lives in your workspace, so the
same folder works across all of them.

```text
SQL MCQ → C# DSA exercise → OOP MCQ → DBMS conceptual → SQL exercise → …
```

No two questions from the same subject in a row. A failure does not reset the
rotation. A weakness does not disappear because the agent explained it well.

---

## Install

macOS / Linux:

```bash
git clone https://github.com/Sharjeelbaig/practice-loop.git ~/.agents/skills/practice-loop
mkdir -p ~/.claude/skills/practice-loop
cp -R ~/.agents/skills/practice-loop/{SKILL.md,references,scripts} ~/.claude/skills/practice-loop/
```

Or let the installer do it:

```bash
curl -fsSL https://raw.githubusercontent.com/Sharjeelbaig/practice-loop/main/install.sh | bash
```

The installer clones into `~/.agents/skills/practice-loop` (used by Codex and
OpenCode) and copies the skill files into `~/.claude/skills/practice-loop` (used
by Claude Code). Run `./install.sh --link-claude` if you prefer a symlink.

Windows PowerShell:

```powershell
.\install.ps1
```

Requirements: **Python 3.9+** (standard library only, no packages) and a host
with shell access.

| Host | Where it loads | Invoke |
| --- | --- | --- |
| OpenCode | `~/.agents/skills`, `~/.config/opencode/skills` | `@practice-loop start` |
| Claude Code | `~/.claude/skills` | `/practice-loop start` |
| Codex | `~/.agents/skills` | `$practice-loop start` |

Restart or reload the host after installing. Full matrix:
[`references/hosts.md`](references/hosts.md).

---

## Quick start

```bash
mkdir ~/practice/interview-prep && cd ~/practice/interview-prep
```

```text
# In your agent:
@practice-loop init
```

It asks for subjects, difficulty, and assessment types, then creates:

```text
interview-prep/
├── notes/        # yours; the agent reads it, never writes it
├── rough/        # your scratch space for solving exercises
├── weak/         # topics you missed, taught and retested until cleared
├── topics/       # small teaching chunks, one folder per subject
└── .practice-loop/
    ├── state.json
    └── history.jsonl
```

Then:

```text
@practice-loop start
```

The first question arrives immediately. Answer it, get graded, and the next
subject comes up. Keep going until you say stop.

---

## The three flows

### Main flow — `start`

One question at a time, in strict rotation. MCQs, coding exercises, SQL
exercises, conceptual questions. After every answer:

1. Verdict: correct, partial, or wrong.
2. Why, in a few lines.
3. The expected answer or corrected solution.
4. The exact misconception, saved to `weak/`.

Then the next question. No "would you like another?" — continuous is the
default.

### Teach flow — `teach`

The agent writes `topics/<subject>/01-*.md`, `02-*.md`, … in small chunks, then
teaches one idea at a time, checking after each one. A failed check means
re-teaching a different way, not moving on. Correct checks close the chunk.

Correct answers in the teach flow **never** clear a weakness. Only a correct
answer in the main flow does. Teaching proves you followed an explanation; the
main flow proves you can retrieve it cold.

### Weakness drill — "quiz me on my weak topics"

Off-rotation main-flow questions against your recorded weaknesses, ordered by
miss count. These count as real evidence and can clear a topic without
disturbing the rotation.

---

## Weakness lifecycle

| Event | Result |
| --- | --- |
| First wrong answer | New weakness, `weak/<subject>/<topic>.md` |
| Repeat wrong answers | Miss count rises; three misses harden it |
| Correct in main flow | Cleared after the required streak |
| Missed later | Reopens automatically, with a regression count |
| Correct in teach flow | Never clears |

A first-time weakness clears with one clean answer. A repeatedly failed one
needs two clean answers in a row. That is deliberate: it stops a lucky guess
from erasing a real gap.

Files look like this:

```markdown
---
subject: sql
topic: joins
status: weak
misses: 3
required_streak: 2
---
# sql / joins

## Misconceptions
- Uses COUNT(*) after a LEFT JOIN, so customers with no orders count as 1.

## Notes
```

`weak/*.md` is rendered from state, but the `## Notes` section is preserved and
yours to edit.

---

## Commands

| Say | Effect |
| --- | --- |
| `init` | Create the workspace and configure subjects |
| `start` | Resume or begin the main flow |
| `teach` / `teach sql` | Teach a subject chunk by chunk |
| `status` | Rotation position, session score, pending question |
| `weak` | Prioritised weaknesses with misconceptions |
| `report` | Accuracy overall, per subject, this session |
| `history` | Recent attempts, newest first |
| `quiz me on my weak topics` | Off-rotation drill |
| `hint` | A smaller hint; never the answer |
| `skip` | Skip the slot; nothing is marked weak |
| `harder` / `easier` | Change difficulty |
| `change subjects` / `add dbms` | Edit the rotation |
| `new session` | Reset session counters, keep everything else |
| `reset` | Wipe progress after explicit confirmation |

---

## Example session

```text
You:    @practice-loop init
Agent:  Subjects?  →  [SQL, C# DSA, OOP, DBMS, C# theory]
        Difficulty? →  [adaptive]
        Types?     →  [mcq, exercise]
        Workspace created at ~/practice/interview-prep

You:    @practice-loop start
Agent:  SQL — intermediate — exercise

        Dialect: PostgreSQL
        customers(id, name), orders(id, customer_id, total)
        Return every customer's name and order count, including customers
        with zero orders. Order by count desc, then name.

You:    SELECT c.name, COUNT(*) FROM customers c
        LEFT JOIN orders o ON o.customer_id = c.id
        GROUP BY c.name ORDER BY 2 DESC, 1;

Agent:  Partial. LEFT JOIN is right, but COUNT(*) counts the NULL row that a
        customer with no orders produces, so they score 1 instead of 0.
        Expected: COUNT(o.id).
        Remember: COUNT(column) ignores NULL; COUNT(*) counts rows.

        C# DSA — intermediate — exercise
        Implement int LongestRun(string s). …
```

That partial answer becomes `weak/sql/left-join-count.md` and is retested a few
questions later, with different tables and numbers.

---

## Why this rather than a prompt

A long prompt drifts. This keeps the parts that must not drift in a small state
machine:

- **One pending question.** The CLI refuses to open a second slot, so the model
  cannot sprint ahead or lose track of what it asked.
- **Rotation in state.** Subject selection is not a model judgement, so a bad
  answer never causes a subject to be dropped.
- **Teach ≠ mastery.** Enforced by the recorder, not by good intentions.
- **Execution-verified grading.** For SQL and code, the skill runs the answer in
  a scratch fixture with a timeout and compares results, not vibes.
- **Persistent, portable progress.** Plain files in your folder. Commit them,
  move them, open them in another agent.

The full behavioural spec is in
[`SKILL.md`](SKILL.md), with references
for question design, grading, authoring, state, and host install.

---

## Configure

```bash
python3 ~/.agents/skills/practice-loop/scripts/practice_loop.py set \
  --difficulty advanced --types mcq,exercise,conceptual --mastery-streak 2 --limit 10
```

`--difficulty adaptive` adjusts per subject from the last five results.
`--limit 0` means continuous.

## Update

```bash
git -C ~/.agents/skills/practice-loop pull --ff-only
```

Skill updates never touch a workspace.

## Uninstall

```bash
rm -rf ~/.agents/skills/practice-loop ~/.claude/skills/practice-loop
```

## Development

```bash
python3 -m unittest discover -s tests -v
```

No dependencies. Tests cover rotation, pending slots, weakness lifecycle,
teach-flow isolation, adaptive difficulty, reporting, and reset safety.

## License

MIT
