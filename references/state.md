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
active weak count, and per-subject teach progress. A ready course reports
`chunks_done/chunks_total` and `topics_done/topics_total`; a course with no
roadmap reports `ready: false`.

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
  "teach": {"completed": ["select-basics/filtering-rows.md"], "current": null},
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

### `teach plan` / `teach next` / `teach record`

```bash
teach plan --subject sql
teach next --subject sql [--topic "Joins"]
teach record --subject sql --result correct --complete
teach record --subject sql --result wrong --topic left-join-null \
             --misconception "Thinks LEFT JOIN drops unmatched rows"
```

A course is a roadmap of topics, and each topic is 2–8 chunks. The plan lives in
`topics/<subject>/ROADMAP.json`; `teach plan` validates it and renders
`ROADMAP.md`.

- `reason: "no_plan"` → write `ROADMAP.json` first.
- `reason: "invalid_plan"` → `errors` lists what to fix (fewer than 2 topics, a
  topic with fewer than 2 chunks, duplicates, more than 8 chunks).
- `reason: "chunk_missing"` → author only the file at `path`, then rerun
  `teach next`. Teaching never skips an unwritten chunk.
- `--topic` on `teach next` starts the first incomplete chunk of one topic.
- `teach record` never advances the chunk on `wrong` or `partial`, and never
  clears a weakness on `correct`. Pass `--complete` only when the chunk's checks
  have been passed.
- The teach chunk key is `<topic-id>/<chunk-file>`, for example
  `select-basics/filtering-rows.md`. `--chunk` accepts that key, the bare
  filename, or an absolute path.

`teach record` reports `topic_complete` when that topic's last chunk closes, and
`next` names the following topic/chunk. If a journey is active and the chunk
completes a scheduled lesson day, it also returns `journey_day` with an
`action` (`journey wrap ...`).

### `journey`

```bash
journey [--subject sql] [--today 2026-11-27]
journey plan --subject sql [--start next-monday|today|YYYY-MM-DD] \
  [--chunks-per-day 2] [--exam-types mcq,exercise] \
  [--exam-questions 8] [--exam-scope week|course] [--labs auto|on|off]
journey exam-done --subject sql --score "7/8" [--notes "..."]
journey wrap --subject sql [--today YYYY-MM-DD]
```

`journey` divides the roadmap into teaching days and Friday exams. The first
call creates a default plan if none exists: start today (Mon–Thu) or next
Monday, 2 chunks/day, 8 questions, the configured types, weekly scope. Every
plan and status call writes `topics/<subject>/JOURNEY.md`, the day-by-day
outline with dates, lesson topics, chunks, exam results, and checkboxes.

The status payload uses `status`. It also returns `outline`, the path to
`topics/<subject>/JOURNEY.md`; point the learner there when they ask "what does
the schedule look like?"

| status | Meaning |
| --- | --- |
| `teach` | today's teaching session; `session.chunks` is the exact batch |
| `exam` | the Friday exam; use `session.types`, `question_count`, `topics` |
| `rest` | weekend, next session is in the future |
| `ahead` | today's session is already done; wait for the next date |
| `before_start` | the plan starts later |
| `complete` | every teaching day and exam is done |

Dates are skipped weekends. A missed teaching day is returned as `late_days`
instead of skipped. Friday's exam opens only after that week's teaching days are
complete; falling behind makes Friday a catch-up day first. `--today` previews
a date without changing state.

Teaching completion is derived from `teach[subject].completed`. Exams close with
`journey exam-done`, which stores the score under that week. Re-planning clears
exam history but keeps teaching progress.

`journey wrap` is the end-of-day step after the day's last chunk. It returns two
assignments and, when the course is practical, one lab task with a `kind`
(`sql`, `code`, `calculation`, or `exercise`). Theory-only courses return
`lab.required: false`. `--labs auto` is the default; `on`/`off` override it.
Submit paths point under `rough/`. `repeat: true` means this day was already
wrapped; `wrapped` is stored in the journey config.

### `topics` / `list-topics`

```bash
topics [--subject sql] [--chunks]
```

Lists every course roadmap with topic and chunk counts. `--chunks` includes
each chunk. The alias `list-topics` is equivalent.

### `quick-teach`

```bash
quick-teach "Prompting" [--subject sql]
```

Starts the first incomplete chunk of one named topic without touching the
journey calendar or the rotation. If no subject is given it prefers the current
rotation subject, then searches other courses. Exit 11 if the topic is missing
or ambiguous.

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
| 11 | `teach next --topic` names no topic in the roadmap |
| 12 | Journey action refused: no plan, wrong session kind, or already complete |

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
    "sql": {
      "completed": ["select-basics/anatomy-of-a-select.md"],
      "current": "select-basics/filtering-rows.md",
      "checks": 7,
      "attempts": {"select-basics/anatomy-of-a-select.md": {"correct": 2, "partial": 0, "wrong": 0}}
    }
  },
  "journey": {
    "sql": {
      "start": "2026-11-23",
      "chunks_per_day": 2,
      "exam_types": ["mcq", "exercise"],
      "exam_questions": 8,
      "exam_scope": "week",
      "labs": "auto",
      "created_at": "...",
      "exams": {
        "1": {"completed_at": "...", "date": "2026-11-27", "score": "7/8", "notes": null}
      },
      "wrapped": ["w1d1", "w1d2"]
    }
  },
  "weak": {
    "sql": {
      "joins": {
        "status": "weak", "misses": 3, "partials": 1, "hits": 1, "streak": 1,
        "required_streak": 2, "regressions": 0,
        "first_seen": "...", "last_seen": "...", "last_result": "correct",
        "unit": "Joins",
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
`retest`, `question`, `answer`, `expected`, `misconception`, `concept`. Teach
rows also carry `unit`, `unit_title`, `chunk`, and `chunk_title`. `report` reads
it, so deleting it loses reporting even if `state.json` survives.

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
