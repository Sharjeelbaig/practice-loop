# practice-loop

An agent skill that turns any course into a daily class and a Friday exam.
You bring a topic, a book, a URL, or your notes. The agent plans the whole
course, teaches one small chunk at a time, quizzes you, and remembers exactly
what you got wrong.

Works in **OpenCode**, **Claude Code**, **Codex**, and any host that reads
[agent skills](https://agentskills.io). Progress lives in your folder, so the
same workspace follows you across agents.

---

## Why it is different

- **Course → topics → chunks.** A course is never one topic, and a topic is
  never one lesson. Every course has a roadmap; every topic has 2–8 chunks.
- **A weekly journey.** Monday–Thursday are lessons, Friday is the exam. The
  CLI decides what today is; you just show up.
- **Weaknesses stick.** Teaching never clears a weakness. A correct answer in
  practice or on the Friday exam does. Failed concepts come back later.
- **One question at a time.** No walls of questions, no answer before your
  attempt, no skipping because a topic felt hard.

---

## Install

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Sharjeelbaig/practice-loop/main/install.sh | bash
```

Or clone it yourself:

```bash
git clone https://github.com/Sharjeelbaig/practice-loop.git ~/.agents/skills/practice-loop
mkdir -p ~/.claude/skills/practice-loop
cp -R ~/.agents/skills/practice-loop/{SKILL.md,references,scripts} ~/.claude/skills/practice-loop/
```

Windows PowerShell:

```powershell
.\install.ps1
```

Requires **Python 3.9+** and a host with shell access. Restart the host after
installing.

| Host | Invoke |
| --- | --- |
| OpenCode | `@practice-loop journey` |
| Claude Code | `/practice-loop journey` |
| Codex | `$practice-loop journey` |

The rest of this README uses `@practice-loop`. Substitute your host's prefix.
It is one skill with subcommands — `journey`, `list-topics`, `quick-teach`, and
so on — not a set of separate slash commands.

---

## Start in 60 seconds

```bash
mkdir -p ~/practice/ai && cd ~/practice/ai
```

```text
You:    @practice-loop init
Agent:  Subjects?          → Generative and Agentic AI Basics
        Difficulty?       → adaptive
        Types?            → mcq, exercise
        Workspace created.
```

Then ask it to plan the course:

```text
You:    @practice-loop teach
Agent:  Here is the roadmap: 8 topics, 27 chunks.
        1. How LLMs generate text (4 chunks)
        2. Prompting (3 chunks)
        ...
        Approve the roadmap?
```

Once the roadmap looks right, start the journey:

```text
You:    @practice-loop journey
Agent:  Week 1 · Thursday
        Teach: How LLMs generate text — Next-token prediction, Temperature
        (2 chunks, about 40 minutes)
```

Come back the next day and type the same thing. That is the whole habit.

---

## The weekly journey

```text
Monday     lesson 1
Tuesday    lesson 2
Wednesday  lesson 3
Thursday   lesson 4
Friday     exam on the week's material
Saturday   rest
Sunday     rest
```

- `@practice-loop journey` works out the date and gives you today's session.
- Every plan writes `topics/<course>/JOURNEY.md`: the full day-by-day outline
  with dates, topics, chunks, and checkboxes. Open it whenever you want to see
  what is coming.
- Each lesson is a small batch of chunks (default **2 chunks/day**).
- After the last chunk, the agent gives you **two assignments** and, for
  practical courses, **one lab task**. SQL, code, maths, and AI courses get a
  lab; theory courses such as history or law get analysis assignments and no
  lab. Submit work under `rough/`.
- Friday's exam defaults to **8 questions**, mixing **MCQ + exercise**, and
  covers the current week. `--exam-scope course` makes it cumulative.
- If you fall behind, the CLI serves the missed lesson first. Finish it, run
  `journey` again, and the Friday exam can still open the same day.
- If you finish a week early, `journey` tells you when the next session opens.
  It does not skip ahead.
- `@practice-loop quick-teach <topic>` is the only way to study off-schedule.

Customise the plan once:

```text
@practice-loop journey plan --start next-monday --chunks-per-day 2 \
  --exam-types mcq,exercise --exam-questions 8 --exam-scope week --labs auto
```

Re-planning resets exam dates, not your teaching progress.

---

## Commands that matter

| Say | What happens |
| --- | --- |
| `@practice-loop journey` | Today's lesson or Friday exam, decided by the CLI |
| `@practice-loop journey wrap` | End-of-day assignments and lab (the agent calls this) |
| `@practice-loop list-topics` | The roadmap: topics, chunks, and progress |
| `@practice-loop quick-teach Prompting` | Start one named topic now, off-schedule |
| `@practice-loop start` | Free practice: rotation quiz across all subjects |
| `@practice-loop teach` | Plan or continue a course, chunk by chunk |
| `@practice-loop weak` | What you keep getting wrong, with misconceptions |
| `@practice-loop report` | Accuracy, per-subject breakdown, exam-ready summary |
| `@practice-loop hint` | A smaller hint; never the answer |
| `@practice-loop skip` | Skip the current slot without marking it weak |
| `@practice-loop stop` | Pause; progress stays exactly where it is |

Useful extras:

```text
@practice-loop journey plan --start today --chunks-per-day 3
@practice-loop teach LangChain and LangGraph
@practice-loop list-topics --chunks
@practice-loop quick-teach "Retrieval" --subject "Generative and Agentic AI Basics"
```

---

## A real example

```text
You:    @practice-loop journey
Agent:  Week 2 · Monday — Prompting
        1. Anatomy of a prompt
        2. Instructions vs examples
        Teach both, then stop.

        Anatomy of a prompt

        A prompt has four jobs: role, task, constraints, output shape.
        Which of these is missing from this prompt?
        ...

You:    [answers]

Agent:  Correct. One check on examples next.
        ...
        End of day — assignments:
        1. Teach-back: explain anatomy of a prompt without notes.
        2. Apply: rewrite a weak prompt and justify each change.
        Lab: build a prompt template that handles three input shapes.
        Submit: rough/generative-and-agentic-ai-basics/2026-11-30-lab/
```

Friday:

```text
You:    @practice-loop journey
Agent:  Exam day · week 2 · 8 questions · mcq, exercise · week scope
        Topics: Prompting, Grounding and RAG

        Question 1/8 (MCQ)
        Which failure is fixed by retrieval rather than a better prompt?
        ...

You:    [answers all eight]

Agent:  Exam recorded: 6/8. Weak: citation-grounding, retrieval-recall.
        Next week starts Monday.
```

The exam is graded like real practice: wrong answers become weaknesses, and
correct answers count as evidence. Teaching alone never clears them.

---

## Make it stick

The skill handles the material; the habit is yours.

- **Put it on the calendar.** A recurring 45-minute block Monday–Thursday and a
  30-minute Friday exam block. Same time, same place. Treat `journey` as the
  first tab you open, not a decision you make.
- **One session a day.** Do not binge four lessons on Sunday. Spacing is what
  makes the Friday exam meaningful.
- **Close the book on Friday.** Answer from memory first. Only then review the
  explanations.
- **Read `weak` before the next lesson.** Five minutes on yesterday's misses is
  worth more than re-reading a chapter.
- **Do the wrap-up before you close the laptop.** The two assignments and the
  lab are 20–30 minutes; they are what make Friday's exam feel easy. Put the
  files in the `rough/` paths the agent gives you and ask for a review next day.
- **Keep your own notes in `notes/`.** The agent reads them for grounding and
  never writes there. Put explanations in your own words after each lesson.
- **Use `quick-teach` for curiosity, not avoidance.** If a topic from the
  roadmap is nagging you, learn it now; do not use it to dodge the day's work.
- **Protect the first 10 minutes.** Phone face down, one tab, one question.
- **Take rest days.** Saturday and Sunday are rest unless you are catching up.
  Sleep is part of the study plan.
- **Review monthly.** `report` shows the trajectory; `weak` shows what still
  needs a second pass.

A simple reminder setup:

| When | Reminder |
| --- | --- |
| Mon–Thu, 19:00 | "Journey — 45 min, phone away" |
| Friday, 18:00 | "Friday exam — 30 min, closed book" |
| Sunday, 20:00 | "Check `weak` and `report` for 10 min" |

---

## Where everything lives

```text
your-course/
├── notes/                 yours; the agent reads, never writes
├── rough/                 your scratch work
├── weak/                  concepts to retest (generated)
├── topics/<course>/
│   ├── ROADMAP.json       the plan: topics, chunk titles
│   ├── ROADMAP.md         the same plan with checkboxes
│   ├── JOURNEY.md         day-by-day outline: date, topic, chunks, done
│   └── <topic>/<chunk>.md one lesson per file
├── .practice-loop/        state, history, journey calendar
└── HOW-IT-WORKS.md        a short primer
```

`notes/` and `rough/` are never touched by `reset`. `weak/` is generated from
state; add personal notes only under its `## Notes` section. `ROADMAP.md` and
`JOURNEY.md` are generated views — edit `ROADMAP.json` and the journey settings,
not those two files.

---

## More detail

- [`references/authoring.md`](references/authoring.md) — how courses, topics,
  and chunks are designed.
- [`references/flows.md`](references/flows.md) — main, teach, journey, and exam
  state machines.
- [`references/question-design.md`](references/question-design.md) — question
  quality and difficulty.
- [`references/grading.md`](references/grading.md) — grading and partial credit.
- [`references/state.md`](references/state.md) — every CLI command and the state
  schema.
- [`references/hosts.md`](references/hosts.md) — install and invocation details.

MIT licensed. Issues and pull requests:
[github.com/Sharjeelbaig/practice-loop](https://github.com/Sharjeelbaig/practice-loop).
