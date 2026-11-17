# CLI and state reference

`scripts/practice_loop.py` is the only writer of machine state. Pure standard
library, Python 3.9+.

```bash
CLI="$SKILL_DIR/scripts/practice_loop.py"
python3 "$CLI" <command> [flags] --json
```

`--json` and `--workspace <path>` are accepted anywhere in the argument list.

## Commands

### `init`

```bash
init [--dir .] [--subjects sql,csharp-dsa] [--difficulty adaptive] [--types mcq,exercise] [--limit 10]
```

Creates `notes/ rough/ weak/ topics/ .practice-loop/`, a primer if absent, and
`state.json`. Idempotent; never overwrites notes, rough work, or existing state.

### `status`

```bash
status
```

Returns workspace, rotation position, cycle, difficulty, session counters,
active weak count, teach progress, and the pending slot if one is open.

### `next`

```bash
next
```

Opens exactly one slot and returns a brief. Advances nothing.

```json
{
  "ok": true,
  "subject": "sql",
  "position": 1,
  "of": 3,
  "cycle": 2,
  "difficulty": "intermediate",
  "suggested_type": "exercise",
  "allowed_types": ["mcq", "exercise"],
  "focus": {"kind": "weak", "topic": "joins", "misses": 3, "retest": true},
  "recent_accuracy": 0.4,
  "limit": null,
  "session_remaining": null,
  "weak_in_subject": [{"topic": "joins", "misses": 3, "required_streak": 2}],
  "teach": {"completed": ["01-select-basics.md"], "current": null},
  "pending": {"subject": "sql", "focus": {}, "type": "exercise", "difficulty": "intermediate"}
}
```

If a slot is already open:

```json
{"ok": false, "reason": "pending", "message": "...", "pending": { ... }}
```

If the session question limit is reached:

```json
{"ok": false, "reason": "limit", "limit": 10, "message": "..."}
```

Exit code stays 0 for both domain states; neither is a crash.

### `record`

```bash
record --result correct|partial|wrong|skipped \
       [--topic joins] [--subject sql] [--type exercise] \
       [--question "..."] [--answer "..."] [--expected "..."] \
       [--misconception "..."] [--concept "..."] [--retest "..."]
```

Records the pending slot, advances the rotation, updates session and subject
stats, and updates the weakness lifecycle. `--topic` is required for `wrong` and
`partial` unless the slot's focus already names a topic.

With `--subject` and no pending slot, it records an **off-rotation main-flow
attempt**. It does not advance the rotation and it can clear a weakness. This is
the mechanism for "quiz me on my weak topics".

### `weak`

```bash
weak [--all]
```

Lists active weaknesses (or all, including mastered) with misses, required
streak, misconceptions, and the file path.

### `report`

```bash
report
```

Overall and current-session accuracy, per-subject breakdown, top weaknesses,
mastered topics, and rotation.

`accuracy_weighted` counts a partial as 0.5. `accuracy_strict` counts only
correct answers. Both exclude skipped questions from the denominator.

### `teach next` / `teach record`

```bash
teach next --subject sql
teach record --subject sql --result correct --complete
teach record --subject sql --result wrong --topic left-join-null \
             --misconception "Thinks LEFT JOIN drops unmatched rows"
```

`teach next` returns the first uncompleted `topics/<subject>/*.md` file. If the
folder is empty it returns `reason: "no_chunks"`; author material first.

`teach record` never advances the chunk on `wrong` or `partial`, and never
clears a weakness on `correct`. Pass `--complete` only when the chunk's checks
have been passed.

### `set`

```bash
set --difficulty adaptive|beginner|intermediate|advanced
set --types mcq,exercise,conceptual
set --mastery-streak 2
set --continuous true|false
set --limit 10
set --subjects oop,dbms
```

`set --subjects` and `init --subjects` take a comma list of the learner's own
wording, so quote names with spaces or symbols:

```bash
init --subjects "SQL,C# DSA,OOP,DBMS,C# theory"
set --subjects "SQL,C# DSA,OOP,DBMS,C# theory"
```

Each name is slugified for folder paths (`C# DSA` → `csharp-dsa`) while the
original text is kept in `rotation.labels` and shown in `status`, `next`,
`record`, `weak`, `report`, and `history` as `subject_label`.

Changing subjects resets the rotation index and clears the pending slot. It does
not delete weaknesses or history.

### `history`

```bash
history [--limit 20] [--subject sql] [--flow main|teach]
```

Recent attempts, newest first, with the recorded misconception.

### `add-subject`

```bash
add-subject dbms --title "Database Management Systems"
```

Creates `topics/dbms/` and appends to the rotation. Appending keeps existing
progress; inserting mid-rotation is not supported.

### `session new`

```bash
session new
```

Archives the current session counters and starts a fresh session id. Keeps
history, weaknesses, rotation, and teach progress. Clears a pending slot.

### `reset`

```bash
reset --yes
```

Deletes `state.json`, `history.jsonl`, and the contents of `weak/`. Keeps
`notes/`, `rough/`, and `topics/`. Refuses without `--yes` (exit 8).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success, including `ok: false` domain states like a pending slot |
| 2 | Invalid argument |
| 3 | No workspace (run `init`) |
| 4 | No subjects in the rotation |
| 5 | No pending slot and no `--subject` |
| 6 | `wrong`/`partial` without a topic |
| 7 | No teach chunk in progress |
| 8 | `reset` without `--yes` |
| 9 | `--subject` contradicts the pending slot |

## `state.json`

```json
{
  "version": 1,
  "created_at": "2026-11-18T09:00:00+00:00",
  "updated_at": "2026-11-18T09:40:00+00:00",
  "config": {
    "difficulty": "adaptive",
    "types": ["mcq", "exercise"],
    "continuous": true,
    "mastery_streak": 1,
    "limit": 0
  },
  "rotation": {
    "subjects": ["sql", "csharp-dsa", "oop"],
    "labels": {"sql": "SQL", "csharp-dsa": "C# DSA", "oop": "OOP"},
    "index": 1,
    "cycle": 2
  },
  "subjects": {
    "sql": {
      "asked": 6, "correct": 4, "partial": 1, "wrong": 1, "skipped": 0,
      "level": 1, "correct_streak": 2, "recent": ["correct", "wrong", "correct"],
      "last_seen": "2026-11-18T09:39:00+00:00"
    }
  },
  "pending": null,
  "session": {"id": "...", "started_at": "...", "asked": 3, "correct": 2, "partial": 0, "wrong": 1, "skipped": 0},
  "teach": {
    "sql": {"completed": ["01-select-basics.md"], "current": null, "checks": 7, "attempts": {}}
  },
  "weak": {
    "sql": {
      "joins": {
        "status": "weak", "misses": 3, "partials": 1, "hits": 1, "streak": 1,
        "required_streak": 2, "regressions": 0,
        "first_seen": "...", "last_seen": "...", "last_result": "correct",
        "misconceptions": ["Uses COUNT(*) after a LEFT JOIN"],
        "retest": "Give a customer with no orders",
        "mastered_at": null
      }
    }
  }
}
```

`history.jsonl` is append-only, one JSON object per attempt: `ts`, `session`,
`flow` (`main` or `teach`), `subject`, `topic`, `type`, `difficulty`, `result`,
`retest`, `question`, `answer`, `expected`, `misconception`, `concept`. `report`
reads it, so deleting it loses reporting even if `state.json` survives.

## Weakness lifecycle

| Event | Effect |
| --- | --- |
| wrong, main | `misses += 1`, streak 0, status `weak` |
| partial, main | `partials += 1`, streak 0, status `weak` |
| wrong/partial, teach | same as above; this is how teaching feeds the main flow |
| correct, main | `hits += 1`, `streak += 1`; `mastered` once streak ≥ required |
| correct, teach | `hits += 1` only; never clears |
| missed after mastered | status back to `weak`, `regressions += 1`, file moves out of `mastered/` |
| skipped | no effect |

`required_streak` is `config.mastery_streak` (default 1), raised to at least 2
once a topic has 3 misses or has regressed. A single correct answer clears a
first-time weakness; a repeatedly failed one needs two clean main-flow answers
in a row. That is deliberate anti-flapping, not a bug.

Mastered files live in `weak/mastered/<subject>/<topic>.md` so a later miss can
move them back. Delete that folder only if the learner wants the history gone.

## Invariants

- At most one pending slot.
- Rotation advances only inside `record`, only when a slot was open.
- `teach record` cannot change `weak` status upward.
- `notes/` is never written.
- `weak/*.md` is rendered from `state.json`; the `## Notes` section is preserved.
- Writes are atomic (temp file + rename).

## No-shell fallback

If the host cannot run commands, you must maintain the files by hand. Say so
once, plainly: progress may drift.

Minimum procedure per main-flow attempt:

1. Read `.practice-loop/state.json`.
2. `subject = rotation.subjects[rotation.index]`.
3. Compose, ask, grade.
4. Append to `history.jsonl` with `flow: "main"`.
5. Update `subjects[subject]` counters and `recent` (keep last 5, drop skipped).
6. Update `weak[subject][topic]` per the lifecycle table above.
7. Advance `rotation.index = (index + 1) % len(subjects)`; increment `cycle` on
   wrap. Clear `pending`.
8. Write the rendered `weak/<subject>/<topic>.md` if the record changed.
9. Write `state.json` back with an updated `updated_at`.

Prefer asking the learner to run the CLI at the end of the session over
hand-editing JSON. If they can run one command, `record` is the one.
