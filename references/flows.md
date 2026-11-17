# Flow state machines

Two flows, one memory. The main flow produces evidence; the teach flow produces
understanding. Mixing them is the most common way this skill goes wrong.

## Main flow

```text
next ──► [pending open] ──► ask ONE question ──► learner answers
  ▲                                                    │
  │                                                    ▼
  └──── record (advances rotation) ◄──── grade ◄───────┘
```

### Step by step

1. `next --json` opens one slot and returns a brief. It advances nothing.
2. If `ok` is false with `reason: "pending"`, an earlier question is still open.
   Ask that one again, or skip it. Do not call `next` again hoping for another
   subject.
3. Compose one question for `brief.subject` at `brief.difficulty`, using
   `brief.focus` and `brief.suggested_type`.
4. Present it. Wait.
5. Grade honestly (`grading.md`).
6. `record --result correct|partial|wrong|skipped ...`. This is the only step
   that advances the rotation.
7. Give four-line feedback, then immediately `next` again.

### Invariants

- Exactly one pending question at a time. The CLI enforces this.
- The rotation advances only inside `record`, only for the pending subject.
- A skipped question advances the rotation and changes no weakness.
- A wrong answer never changes the subject. The next subject is whatever the
  rotation says, even if they just failed the previous one.
- `next` is idempotent in the sense that a second call returns the pending slot
  instead of opening a new one.

### Recovering a lost pending question

If the conversation was compacted and you no longer have the question text:
`status --json` returns `pending` with subject, focus, type, and difficulty.
Re-compose an equivalent question for that same slot and say so. Do not clear
the slot silently. If the learner would rather move on:

```bash
python3 "$CLI" record --result skipped
```

### Count-limited sessions

If the learner asked for "10 questions", set `--limit 10` and let the CLI stop
the session. It returns `reason: "limit"` when the count is reached; do not count
in your head. If they asked for continuous, never ask "another one?" — keep
going until they stop.

### Stopping

"Stop", "pause", "that's enough" → stop asking immediately. Leave `pending`
alone if a question is open; it will resume where it was. Do not reset the
session unless they ask for a new one.

## Teach flow

```text
teach next ──► read chunk ──► teach one idea ──► check ──► pass? ──► next idea
                                   ▲                │
                                   └── re-teach ◄───┘ fail (record to weak/)
                                                        │
                                             chunk checks passed
                                                        ▼
                                     teach record --complete ──► next chunk
```

### Step by step

1. `teach next --subject <slug> --json`. If `reason: "no_chunks"`, author the
   chunks first (`authoring.md`).
2. Read the returned `path` file in full before teaching from it.
3. Teach one idea. Short. Concrete example. Then one check question.
4. On a wrong or partial check:

```bash
python3 "$CLI" teach record --json --subject sql --result wrong \
  --chunk 02-joins.md --topic left-join-null \
  --misconception "Believes LEFT JOIN removes unmatched rows"
```

   The chunk does not advance. Re-teach the same idea with a different
   explanation, example, or counterexample, then check again. Do not simply
   repeat the same wording louder.
5. On correct checks — two in a row is the default bar — close the chunk:

```bash
python3 "$CLI" teach record --json --subject sql --result correct --complete
```

6. Continue into the next chunk automatically unless the learner stops. When
   `teach next` reports `done: true`, say: teaching finished, now prove it in
   the main flow.

### Teach-flow rules

- Correct teach answers never clear `weak/`. The CLI enforces this; do not
  work around it.
- Wrong teach answers do create or strengthen a weakness. That is how teaching
  feeds the main flow.
- The learner may interrupt with any question. Answer fully. Explanation is the
  point of this flow.
- Do not dump the whole chunk as a lecture. One idea, one check, repeat.
- If a learner already knows a chunk cold (two confident correct answers before
  you finish explaining), mark it complete and move on.

## Switching between flows

| Learner says | Action |
| --- | --- |
| "teach me X" while mid-main-flow | Finish or skip the pending question first, then `teach next --subject X`. |
| "quiz me" while mid-teach | Leave teach progress; run the main flow. Chunk progress is preserved. |
| "quiz me on weak topics" | Off-rotation main-flow records (`weakness.md` → §6 of SKILL.md). Rotation untouched. |
| "start over" | `session new`. Keeps history, weaknesses, rotation, and chunks. |
| "reset everything" | Confirm twice, then `reset --yes`. Keeps notes, rough, topics. |

## Session boundaries

A session is a bookkeeping window, not a fresh brain. `session new` zeroes the
session counters and keeps rotation, history, weaknesses, and teach progress.
Use it when the learner says "new session" or after a long break, not between
questions.

If a new calendar day starts mid-flow, do not reset anything. The history
timestamps handle the rest.
