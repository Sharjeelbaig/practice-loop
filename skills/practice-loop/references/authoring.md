# Authoring teaching chunks

Chunks are the teach flow's material. They are also the main flow's source of
truth for coverage. Write them small, concrete, and checkable.

## When to author

- `teach next` returned `reason: "no_chunks"`.
- The learner added a subject and wants to be taught it.
- The learner supplied a URL, document, or notes and asked to be taught from it.
- A chunk is stale or wrong and the learner asks to fix it.

Do not author chunks just to fill space before a main-flow question. The main
flow can run with no `topics/` at all.

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

## Shape

```text
topics/<subject>/
├── 01-select-basics.md
├── 02-joins.md
├── 03-aggregation.md
└── 04-subqueries.md
```

- Zero-pad the prefix so lexical sort equals teaching order.
- One idea per chunk. If a chunk needs two "and also" sentences in its title,
  split it.
- 4–8 chunks for a focused topic, 8–15 for a broad subject. More than that and
  the main flow will take weeks to cover it.
- 60–150 lines each. Long enough to teach, short enough to finish in one sitting.

## Template

```markdown
---
subject: sql
chunk: 02
title: Joins and row preservation
prerequisites: [01-select-basics]
concepts: [inner-join, left-join, join-predicate, null-extension]
source: notes/sql-notes.md
---

# Joins and row preservation

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

- Revise a chunk in place when it is wrong or unclear.
- Do not delete a chunk the learner is mid-way through; edit and re-teach it.
- If you split a chunk, keep the old filename as a short pointer or rename
  consistently and tell the learner. `teach` tracks completed files by name, so
  a rename will make it look uncovered again — that is acceptable, but say so.
- Never write into `notes/`. If the learner's material needs correcting, tell
  them; do not edit it.

## Example: from a URL

1. Fetch the page. Extract headings and code blocks.
2. Map the page's sections onto 4–8 chunks in teaching order, not page order if
   the page is reference-shaped.
3. Put the URL in `source:`.
4. Teach only what the page supports. If the learner asks beyond it, answer, but
   mark the answer as supplementary and do not put it in the chunk as if the
   source said it.

## Example: from `notes/`

1. Read every file under `notes/` that matches the subject.
2. Prefer the learner's own phrasing and examples.
3. If their notes contain an error, do not copy it into a chunk silently. Teach
   the correct version and mention the discrepancy once.
4. `source:` should name the files used.
