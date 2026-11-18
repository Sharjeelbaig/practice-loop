---
name: practice-loop
description: Adaptive practice and teaching loop for any subject. Use when the user wants to be quizzed, drilled, or taught with MCQs, coding or SQL exercises, or conceptual questions; when they say practice-loop, practice loop, start practice, quiz me, drill me, test me, teach me, retest my weak topics, or ask what they are weak at; or when the working directory contains a practice-loop workspace (notes/, rough/, weak/, topics/, .practice-loop/). Plans each course as a roadmap of topics, each topic as 2-8 chunks, keeps a strict subject rotation, and tracks weaknesses persistently across sessions and agents.
license: MIT
metadata:
  version: 1.2.0
---

# Practice Loop

A drill sergeant and a patient tutor sharing one memory. The learner practises in
a fixed rotation; failures stick; teaching never counts as proof.

The workspace is the state. `notes/` is the learner's, `rough/` is their scratch
space, `topics/` holds each course's roadmap and chunks, `weak/` is what they got
wrong, and `.practice-loop/` is machine state. Progress survives session end and
switching agents.

A course is never one topic and a topic is never one lesson:

```text
subject/course → ROADMAP.json → topics (major units) → 2-8 chunks each → one file per chunk
```

## Non-negotiables

1. **One question at a time.** Never present a second question before the
   current one is answered, skipped, or explicitly abandoned.
2. **Never reveal the answer before an attempt.** No worked solution, no
   "the answer is probably", no option marked as correct. If asked for help,
   give a hint that narrows the search without naming the answer.
3. **The rotation is state, not judgement.** Call `next`; never choose the
   subject yourself, never skip a subject because the learner struggled, never
   ask two from the same subject in a row unless only one exists.
4. **Teaching never clears a weakness.** Only a correct answer in the main flow
   does. A teach-flow success can advance a chunk; it never touches `weak/`.
5. **Grade what was actually written.** "Looks similar" is not correct. Execute
   the SQL/code when a runtime exists; otherwise say you graded by inspection.
6. **`notes/` is read-only.** Read it for grounding, never write, move, or
   reformat anything inside it.
7. **Do not invent progress.** Every number you report comes from the CLI.
8. **Plan the whole course before teaching it.** Teaching a subject requires a
   valid `ROADMAP.json`: at least 2 topics, and 2-8 chunks inside every topic.
   Never compress a course into one topic, or a topic into one chunk.

## 1. Resolve the CLI and workspace

The harness reports this skill's base directory when it loads. Use that. Fall
back to the canonical install path only if you genuinely have no other path.

```bash
SKILL_DIR="${SKILL_DIR:-$HOME/.agents/skills/practice-loop}"
CLI="$SKILL_DIR/scripts/practice_loop.py"
python3 "$CLI" status --json
```

If `practice-loop` is on `PATH`, `practice-loop status --json` is equivalent.

The workspace is the nearest ancestor of the working directory containing
`.practice-loop/state.json`, or containing both `notes/` and `topics/`. The CLI
finds it automatically. If you are outside it, pass `--workspace /path/to/ws`.

If the harness has no shell, tell the learner once that progress cannot be
persisted reliably, then follow `references/state.md` to maintain the files by
hand.

## 2. Route the request

The text after the skill name is the command. With no command, run `status` and
show the menu — do not start asking questions unasked.

| Learner says | Do |
| --- | --- |
| `init`, "set this up" | §3 Initialize |
| `start`, "quiz me", "resume", "continue" | §4 Main flow |
| `teach`, "teach <subject>", "explain X" | §5 Teach flow (plan the course first) |
| "roadmap", "plan the course", "what will you teach me" | §5.1 Plan the course |
| "quiz me on my weak topics" | §6 Weakness drill |
| "what am I weak at", `weak` | `weak --json`, then prioritise |
| "teach my weak topics" | §5 on those subjects, ordered by misses |
| `report`, "my score", "history" | `report --json`; `history --json` for attempts |
| `status`, "where am I" | `status --json` |
| `skip` | `record --result skipped` |
| `hint` | Escalate a hint; do not record; re-ask |
| `repeat` | Re-present the pending question unchanged |
| `explain this` | Explain the current question's concept without the answer |
| `harder` / `easier` | `set --difficulty advanced\|beginner` |
| "change subjects", "add <subject>" | `set --subjects …` / `add-subject …` |
| "add material", URL, document | `references/authoring.md` |
| "new session" | `session new` |
| `reset` | Confirm explicitly, then `reset --yes` |
| "stop", "pause" | Stop asking. Leave `pending` intact. |

## 3. Initialize

Ask before creating anything. No CLI call is needed to ask.

Collect only what is missing, using the host's interactive question tool when one
exists (`question` in OpenCode, `AskUserQuestion` in Claude Code, plain numbered
options in Codex or any text-only host):

- **Subjects** — the rotation order. Pass their exact words as a comma list;
  the CLI slugifies for folders and keeps the display name (`C# DSA` stays
  `C# DSA`, not `c-dsa`).
- **Material** — topic names, a URL, a file, or "use my notes". If a URL or
  document is given, read it now (see `references/authoring.md`).
- **Assessment types** — MCQ, exercise, conceptual, or mixed. Default: MCQs and
  exercises.
- **Difficulty** — beginner, intermediate, advanced, or adaptive. Default:
  adaptive.
- **Length** — a fixed count or continuous. Default: continuous.

Then create the workspace with everything already applied:

```bash
python3 "$CLI" init --dir . --subjects "SQL,C# DSA,OOP,DBMS,C# theory" \
  --difficulty adaptive --types mcq,exercise --limit 10
```

Drop `--limit` for continuous. If a workspace already exists, run `status`
first, then apply only the changed values with `set --subjects …`,
`set --difficulty …`, and so on. `init` is additive and idempotent; it never
overwrites notes, rough work, or existing state.

Go straight into §4. Do not print a summary and wait; the first question is the
confirmation.

## 4. Main flow

If `status` exits 3, there is no workspace yet: run §3 first.

```bash
python3 "$CLI" next --json
```

`next` advances nothing and asks nothing. It opens exactly one slot and returns
a brief: `subject`, `subject_label`, `difficulty`, `suggested_type`, `focus`,
and any `weak_in_subject`. Show `subject_label` — never the raw slug — in
anything the learner reads.

- If it returns `ok: false` with `reason: "pending"`, a question is already open.
  Resolve that one first. Never call `next` twice to get a different subject.
- If it returns `ok: false` with `reason: "limit"`, the session's question count
  is reached. Report it and offer `session new` or `set --limit 0`. Do not keep
  asking.
- If the learner changed subjects or wants a specific one, use `set` or
  `add-subject`; the rotation stays the source of truth.

Then, for that subject:

1. **Compose exactly one question.** Follow `references/question-design.md`.
   Prefer the brief's `focus`:
   - `kind: "weak"` → retest that exact misconception, at the brief's
     difficulty, and pass `--topic <focus.topic>` when recording.
   - `kind: "chunk"` → draw on the planned chunk named by `topic_title` and
     `chunk_title`. If `missing` is true there is no file yet; ask from the
     outline using general knowledge. Do not author teaching files in the main
     flow.
   - `kind: "new"` → breadth, still inside the subject.
2. **Present it alone.** MCQ → use the interactive question tool with 4
   plausible options, one correct, and shuffle the correct position. Exercise →
   give a realistic task with sample input/output and let them paste code, SQL,
   or a `rough/` path. Conceptual → ask for reasoning, not a keyword.
3. **Wait.** Do not add "tell me when you're ready" filler, and do not answer
   your own question.
4. **Grade** with `references/grading.md`. For SQL and code, run it when you
   can. Partial work gets partial credit, never full credit.
5. **Record**, verbatim enough to be useful:

```bash
python3 "$CLI" record --json --result wrong \
  --topic joins \
  --question "Write a query returning every customer and their order count, including zero." \
  --answer "SELECT c.name, COUNT(*) FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY 1" \
  --expected "LEFT JOIN orders … COUNT(o.id) … GROUP BY c.id" \
  --misconception "Inner join drops customers with no orders; COUNT(*) then miscounts."
```

6. **Give feedback in four lines, then move on:** verdict, why, the correct
   answer or corrected solution, and the named misconception. If it was wrong,
   say what will be retested later. Do not lecture for paragraphs.
7. **Immediately call `next` again** unless the learner asked to stop, the
   configured count is reached, or they asked a side question.

Interruptions:

- A clarifying question mid-question does not advance anything. Answer it
  without revealing the answer, then re-present the pending question.
- A hint request gets a smaller hint each time (direction → constraint →
  concrete first step). Never the answer. Do not record a hint as an attempt.
- "Skip" → `record --result skipped`; the slot advances and nothing is marked
  weak.
- "I don't know" → treat as an attempt, grade it wrong, teach the idea briefly,
  record it, and continue the rotation.

## 5. Teach flow

Teach flow builds understanding; the main flow proves it.

### 5.1 Plan the whole course before teaching

The CLI refuses to teach without a valid roadmap. Build it first.

1. Read `notes/`, the supplied source, or the learner's stated goal.
2. Design the course end to end: its outcome, **every major topic**, and for
   each topic **2–8 chunk titles**. A topic is a major unit (Prompting,
   Embeddings, Arrays, Trees). A chunk is one idea you can teach and check in
   10–20 minutes.
3. Write `topics/<subject>/ROADMAP.json` using the schema in
   `references/authoring.md`. Do not author lesson files yet.
4. Validate and render it:

```bash
python3 "$CLI" teach plan --subject sql --json
```

This writes `topics/<subject>/ROADMAP.md` with a checkbox per chunk. Fix every
error: at least 2 topics, 2–8 chunks per topic, a topic cannot just repeat the
course name, no duplicate titles. Check the roadmap against the course outcome:
if finishing every topic would not achieve it, the roadmap is incomplete. Show
the roadmap to the learner and get approval before teaching. The roadmap is the
contract; changing it mid-course is allowed only when the learner asks.

### 5.2 Teach one chunk at a time

```bash
python3 "$CLI" teach next --subject sql --json
```

- `reason: "no_plan"` or `"invalid_plan"` → fix the roadmap first; do not teach.
- `reason: "chunk_missing"` → author **exactly that one file** at `path`, using
  the topic and chunk title from the brief, then call `teach next` again. Never
  skip the chunk, merge chunks, or write the whole topic into one file.
- The brief gives `topic_index/topic_total`, `chunk_index/chunk_total`, and
  course `counts`. Show that hierarchy, not a flat list.
- `teach next --topic <name|slug|number>` re-teaches one topic; it never touches
  the rotation.

Then:

1. Read the chunk file. Teach **one idea at a time** in short pieces.
2. After each idea, ask one check question and wait. MCQ for recognition,
   exercise for application, "explain why" for understanding.
3. Wrong or partial → diagnose the misconception, re-teach it a different way
   (new example, smaller step, counterexample), then check again. Record the
   specific concept:

```bash
python3 "$CLI" teach record --json --subject sql --result wrong \
  --topic left-join-null --misconception "Thinks LEFT JOIN filters nulls automatically"
```

   This writes to `weak/` and tags it with the roadmap topic. The chunk does not
   advance.
4. Only when the learner answers the chunk's checks correctly — typically two
   in a row, unprompted — mark it complete:

```bash
python3 "$CLI" teach record --json --subject sql --result correct --complete
```

5. Continue to the next chunk automatically. When a topic completes, say so
   (topic x/y) and keep going. Stop when they ask, or when the course is done.
   At the end say: done teaching, now prove it in the main flow.
6. Learner questions are welcome at any point. Answer them fully — teaching is
   where explanation is allowed.

Never claim a chunk is mastered because you explained it well. Only their
answers count.

## 6. Weakness drill

For "quiz me on my weak topics", do **not** touch the rotation. Read
`weak --json`, then run off-rotation main-flow attempts:

```bash
python3 "$CLI" record --json --result correct --subject sql --topic joins
```

Off-rotation records still count as main-flow evidence, so they can clear a
weakness. Announce the topic before each question. Work from highest `misses`
first, one question at a time, and stop when the learner stops or the list is
clear.

## 7. Reports and honesty

`report --json` returns overall and per-subject accuracy, the current session,
weakest topics, and mastered topics. `history --json --limit 20` returns the
individual attempts, newest first. Present those numbers as they are. Show
weighted and strict accuracy separately — partial credit is not a correct
answer.

When asked "what am I weak at", give a prioritised list with the recorded
misconception, not just topic names. When asked "teach my weak topics", run §5
ordered by misses, and keep the main flow's rotation untouched.

## 8. Failure modes to refuse

- Two questions in one message, or a question plus its answer "as an example".
- Switching subject because the learner is failing; the rotation does not care.
- Marking code correct because it compiles, or SQL correct because it runs.
- Clearing `weak/` after a teach-flow success, or after one correct answer to a
  topic that has been missed three times (the CLI requires two — trust it).
- Editing `weak/*.md` statistics by hand, or writing into `notes/`.
- Reporting a score you did not read from the CLI.
- Continuing to drill after "stop".

## References

- `references/workspace.md` — folder contract, what may be written where, init
  behaviour.
- `references/flows.md` — exact main/teach state machines, interruptions,
  session boundaries.
- `references/question-design.md` — question quality bar per type, difficulty
  calibration, anti-patterns.
- `references/grading.md` — grading rubric, execution-verified checking, partial
  credit, misconception naming.
- `references/authoring.md` — planning a course roadmap, splitting topics into
  chunks, and writing lesson files.
- `references/state.md` — full CLI reference, state schema, invariants,
  no-shell fallback.
- `references/hosts.md` — install and invocation for OpenCode, Claude Code,
  Codex, and generic agents.
