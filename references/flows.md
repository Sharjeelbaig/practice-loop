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
teach plan ──► valid ROADMAP.json? ──no──► fix topics/chunks
                    │ yes
                    ▼
teach next ──► chunk file exists? ──no──► author exactly one chunk
                    │ yes
                    ▼
         read chunk ──► teach one idea ──► check ──► pass? ──► next idea
                              ▲                │
                              └── re-teach ◄───┘ fail (record to weak/)
                                                   │
                                        chunk checks passed
                                                   ▼
                                teach record --complete ──► next chunk
                                                   │
                                        topic's last chunk?
                                                   ▼
                                        say topic complete, continue
```

### The course hierarchy

```text
subject/course
└── ROADMAP.json           all topics, all chunk titles, ordered
    └── topic/             major unit, e.g. "Prompting"
        └── chunk.md       one idea, one file
```

The roadmap is mandatory. `teach next` returns `no_plan` or `invalid_plan`
until `ROADMAP.json` has at least 2 topics and 2–8 chunks per topic.

### Step by step

1. Plan the whole course first (`authoring.md`), write
   `topics/<subject>/ROADMAP.json`, then run `teach plan --subject <slug>`.
   Fix every validation error and show the rendered `ROADMAP.md` to the learner.
2. `teach next --subject <slug> --json`.
   - `reason: "chunk_missing"` → write exactly the file at `path`, then call
     `teach next` again. Never merge chunks or write a whole topic at once.
   - `reason: "done"` → the course (or `--topic` scope) is complete.
3. Read the returned `path` in full before teaching from it. The brief names the
   topic (`topic_title`, `topic_index/topic_total`) and chunk
   (`chunk_title`, `chunk_index/chunk_total`).
4. Teach one idea. Short. Concrete example. Then one check question.
5. On a wrong or partial check:

```bash
python3 "$CLI" teach record --json --subject sql --result wrong \
  --topic left-join-null \
  --misconception "Believes LEFT JOIN removes unmatched rows"
```

   The chunk does not advance. Re-teach the same idea with a different
   explanation, example, or counterexample, then check again. Do not simply
   repeat the same wording louder. The concept `topic` is saved under the
   roadmap topic in `weak/`.
6. On correct checks — two in a row is the default bar — close the chunk:

```bash
python3 "$CLI" teach record --json --subject sql --result correct --complete
```

7. Continue into the next chunk automatically unless the learner stops. When a
   topic's last chunk closes, say `topic complete` and keep going. When
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
- `teach next --topic <name|slug|number>` starts the first incomplete chunk of
  one topic. It does not change the rotation or course progress elsewhere.

## Switching between flows

| Learner says | Action |
| --- | --- |
| "teach me X" while mid-main-flow | Finish or skip the pending question first, then plan the course (§5.1) and `teach next --subject X`. |
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
