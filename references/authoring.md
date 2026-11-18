# Authoring a course: roadmap, topics, chunks

Teaching material has three levels:

```text
subject/course          rotation unit, e.g. "Generative and Agentic AI Basics"
└── ROADMAP.json        every topic, in order, with its chunk titles
    └── topic/          a major unit, e.g. "Prompting"
        └── chunk.md    one idea, one file, 10–20 minutes
```

A course is never one topic. A topic is never one lesson. If a plan has one
topic, or a topic has one chunk, the plan is wrong and the CLI rejects it.

## When to author

- The learner says `teach <subject>` and no roadmap exists.
- The learner supplied a URL, document, or notes and asked to be taught from it.
- A topic or chunk is stale or wrong and the learner asks to fix it.
- The learner reached a `chunk_missing` brief.

Do not author a roadmap just to fill space before a main-flow question. The main
flow can run with no `topics/` at all.

## Step 1 — plan the whole course first

Read the source material before naming anything. Then decide the course outcome
and the complete list of topics — not just the first one. Write
`topics/<subject>/ROADMAP.json`:

```json
{
  "title": "Generative and Agentic AI Basics",
  "outcome": "Understand how LLM applications work end to end.",
  "topics": [
    {
      "title": "How LLMs generate text",
      "outcome": "Explain next-token prediction and sampling.",
      "chunks": [
        "Next-token prediction",
        "Probability and sampling",
        "Temperature and top-p",
        "Context windows"
      ]
    },
    {
      "title": "Prompting",
      "outcome": "Write prompts that constrain the model.",
      "chunks": [
        "Anatomy of a prompt",
        "Instructions vs examples",
        "Failure modes"
      ]
    }
  ]
}
```

Rules:

- **At least 2 topics.** A course with one topic is a compressed course.
- **2–8 chunks per topic.** More than eight means the topic is really two topics.
- A topic title cannot repeat the course name; `SQL → topic SQL` is rejected.
- Topics are ordered; chunks are ordered. Lexical order is not used.
- Paths are `<topic-slug>/<chunk-slug>.md`, so you can add a topic or chunk
  anywhere without breaking completed progress. Use an explicit `"id"` if a
  title may change.
- Titles are learner-facing and concrete. "Prompting" is a topic;
  "Temperature and top-p" is a chunk.
- No duplicate topic titles, and no duplicate chunk titles inside a topic.
- `outcome` is optional but recommended: one sentence per course and per topic.
- Slugs and file paths are derived from titles. Give a topic or chunk an
  optional `"id"` when you need the path to survive a title change. Once
  teaching starts, do not rename a title without an id unless the learner
  agrees; a rename makes that chunk look uncovered again.

Then check the whole map: if finishing every chunk would not achieve the course
outcome, the roadmap is incomplete. Add the missing topics now, before teaching.

### Example: a DSA course is not one topic

A learner asking for "DSA problem solving" needs units like these, each with its
own chunks (adjust to their level and language):

| Topic | Example chunks |
| --- | --- |
| Arrays and strings | traversal, two pointers, sliding window, prefix sums, in-place edits |
| Hash maps and sets | frequency counting, membership, grouping, deduplication |
| Sorting and binary search | comparison sorts, custom keys, binary search, search space |
| Recursion and backtracking | base cases, call tree, subsets, permutations, pruning |
| Trees and graphs | traversals, BFS/DFS, topological sort, shortest path, union-find, grids |
| Dynamic programming | state, transition, base cases, 1D, 2D |

A single "DSA" topic with eight chunks is rejected: it hides every one of these
units and turns the course back into one compressed lesson.

Then validate and render:

```bash
python3 "$CLI" teach plan --subject <subject> --json
```

`teach plan` writes `topics/<subject>/ROADMAP.md` with a checkbox per chunk and
returns the full tree. Fix every error before teaching. Show the roadmap to the
learner and get approval; it is the contract for the course.

The CLI derives this layout from the JSON:

```text
topics/generative-and-agentic-ai-basics/
├── ROADMAP.json
├── ROADMAP.md
├── how-llms-generate-text/
│   ├── next-token-prediction.md
│   ├── probability-and-sampling.md
│   └── ...
└── prompting/
    ├── anatomy-of-a-prompt.md
    └── ...
```

Do not create the chunk files during planning. They are authored one at a time,
when `teach next` asks for them.

## Step 2 — author one chunk when asked

`teach next` returns `reason: "chunk_missing"` with an exact `path`, plus the
topic and chunk title. Write only that file, then call `teach next` again.

- One idea per chunk. If the title needs "and also", split it in the roadmap.
- 60–150 lines. Long enough to teach, short enough for one sitting.
- Ground every claim in the source.

## Grounding

Priority order:

1. `notes/` — the learner's own material. Read it first.
2. The supplied URL, file, or pasted text. Read the actual content; do not
   answer from the title.
3. General knowledge — only when no source was supplied, or the source does not
   cover the requested scope. Label it.

Rules:

- Every factual claim should be traceable to the source or be standard,
  uncontroversial knowledge.
- Quote short phrases when the learner's material uses specific terminology.
  Do not invent terminology they will not see in their source.
- If the source conflicts with standard practice, teach the source and flag the
  conflict once.
- If the source is too thin for the requested depth, say so and ask whether to
  supplement. Do not silently pad with invented specifics.
- Put the provenance in the frontmatter: a path, a URL, or `general knowledge`.

## Chunk template

```markdown
---
subject: sql
topic: joins
chunk: 02
title: LEFT JOIN and row preservation
prerequisites: [01-inner-joins]
concepts: [left-join, join-predicate, null-extension]
source: notes/sql-notes.md
---

# LEFT JOIN and row preservation

## Core idea

A join combines rows from two tables using a predicate. The join type decides
what happens to rows that find no match.

## Worked example

...schema, two small tables, one query, the result, and one sentence on why...

## Common mistakes

- Putting an outer-join filter in `WHERE`, which silently turns it into an inner
  join.
- Counting `*` instead of the joined column.
- Forgetting that a fan-out join multiplies rows before aggregation.

## Check yourself

1. Which rows survive a `LEFT JOIN` when the right side has no match?
2. Rewrite this query so customers with zero orders still appear.
3. Given these rows, what does `COUNT(o.id)` return for customer 3?

## Answer key

1. Every row from the left table, with NULLs on the right.
2. ...
3. 0 — `COUNT(column)` ignores NULL, `COUNT(*)` would return 1.
```

## Check design

- 2–4 checks per chunk. The last one must be application, not recall.
- One check per concept in `concepts:`.
- Include at least one "what breaks if…" check.
- Keep the answer key at the bottom. Never reveal it before the learner answers.
- If the learner answers all checks correctly twice, close the chunk. Do not
  keep quizzing a chunk they clearly own.

## Updating

- Revise one chunk in place when it is wrong or unclear.
- Do not delete a chunk the learner is mid-way through; edit and re-teach it.
- If a chunk must split, add a new chunk to the roadmap rather than renaming the
  current one. Completed progress is keyed by `topic-id/chunk-file`.
- Renaming a title changes its slug and path (unless the item has an explicit
  `id`) and makes the chunk look uncovered. Say so before doing it.
- Never write into `notes/`. If the learner's material needs correcting, tell
  them; do not edit it.

## Example: from a URL

1. Fetch the page. Extract headings and code blocks.
2. Group sections into 3–8 topics in teaching order, not page order if the page
   is reference-shaped.
3. Split each topic into 2–8 chunks, one idea each.
4. Put the URL in `source:`.
5. Teach only what the page supports. If the learner asks beyond it, answer, but
   mark the answer as supplementary and do not put it in the chunk as if the
   source said it.

## Example: from `notes/`

1. Read every file under `notes/` that matches the subject.
2. Map their headings onto topics, and their sub-points onto chunks.
3. Prefer the learner's own phrasing and examples.
4. If their notes contain an error, do not copy it into a chunk silently. Teach
   the correct version and mention the discrepancy once.
5. `source:` should name the files used.
