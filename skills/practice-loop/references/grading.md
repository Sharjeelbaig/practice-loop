# Grading

Correct is correct. Partial is partial. Wrong is wrong. "Close enough" is how
practice loops become useless.

## Verdicts

| Verdict | Meaning |
| --- | --- |
| `correct` | Does what was asked, on the stated cases, for the right reason. |
| `partial` | Right approach with a real defect, or right answer with defective reasoning. |
| `wrong` | Wrong result, or a misconception that would fail in practice. |
| `skipped` | Not attempted. Never counts as correct, never creates a weakness. |

Record exactly one. Never upgrade a partial to correct to be encouraging, and
never downgrade a correct answer because the style was ugly.

## Multiple choice

Compare the chosen option with the key. If they picked two, that is `partial`
only when multi-select was allowed and one pick is right; otherwise `wrong`.

Do not accept "B but I meant C" as correct. Do not accept a correct option with
an explanation that contradicts it — that is `partial` and reveals a fragile
grasp.

## SQL

### Prefer execution

If a matching engine is available, run it. Do not eyeball SQL you can execute.

1. Create a fixture under `rough/<subject>/<exercise>/`:
   `schema.sql`, `seed.sql`, and the learner's query as `answer.sql`.
2. Run against a scratch database, not the learner's real one:

```bash
sqlite3 /tmp/pl-check.db < schema.sql
sqlite3 /tmp/pl-check.db < seed.sql
sqlite3 -header -column /tmp/pl-check.db < answer.sql
```

3. Compare **result sets**, not query text. Row order matters only when the task
   asked for an order. Column names matter when the task named them.
4. Run one extra case the learner did not see: an empty table, a NULL foreign
   key, a duplicate row, a customer with two orders.

Dialect matters. Use SQLite only for SQLite-flavoured tasks. For PostgreSQL use
`psql` if present, for MySQL `mysql`, for SQL Server `sqlcmd`; if the right
engine is missing, say "graded by inspection" and use the checklist below.

### Static checklist when execution is impossible

- Correct `JOIN` type for the required row preservation.
- Join predicates in `ON`, filters in `WHERE`; outer-join filters not
  accidentally in `WHERE`.
- `COUNT(*)` vs `COUNT(column)` vs `COUNT(DISTINCT …)`.
- `GROUP BY` covers every non-aggregated column.
- `HAVING` for aggregate filters, `WHERE` for row filters.
- NULL semantics: `NOT IN` with NULLs, `<>` against NULL, `COALESCE` where the
  task needs a value.
- Duplicates: missing `DISTINCT` or a fan-out join that multiplies rows.
- Window function frame and `PARTITION BY` when used.
- Dialect-specific syntax.

### Partial credit

- Right shape, wrong join type → `partial` if the sample passes but the edge case
  fails, otherwise `wrong`.
- Right result by luck (e.g. `SELECT *` on a one-column table) → `partial` and
  say why.
- Right query, wrong column alias when aliases were specified → `partial`.
- Query runs but returns extra columns → `partial` if the data is right.

## Code

### Prefer execution

- Python: `python3 -I` in the exercise folder, 10-second timeout.
- JavaScript: `node`, 10-second timeout.
- C#: `dotnet run` if `dotnet` exists, otherwise compile check only.
- Java: `javac` + `java` if a JDK exists.
- Anything else: use the language's runner if present; otherwise static review.

Drive it with the sample cases first, then the edge cases you withheld. Paste the
actual output into your feedback. If it crashes, that is `wrong`, and the
traceback's first useful line is the feedback.

### Static checklist when execution is impossible

- Signature and types match the task.
- The sample produces the stated output by hand-trace.
- Empty input, single element, duplicates, negative numbers, overflow,
  Unicode — whichever apply.
- Loop bounds and off-by-one.
- Recursion base case and depth.
- Mutation of shared input where it should not happen.
- Complexity against the stated constraints, not against taste.

### Partial credit

- Correct logic, one failed edge case → `partial`.
- Correct output, quadratic where the constraints demand linear → `partial`
  with the complexity called out.
- Compiles but ignores a stated requirement → `wrong`.
- Correct approach, syntax error that a compiler would catch → `partial` at
  best; do not call it correct because the idea was right.

## Conceptual

Grade on four things:

1. **Claim** — did they assert the right mechanism?
2. **Reason** — did they say why, or only what?
3. **Example** — can they ground it?
4. **Boundary** — do they know when it stops being true?

All four → `correct`. Claim plus reason, missing boundary → `partial`. Right
vocabulary with the wrong mechanism → `wrong`, and name the reversal.

Accept paraphrase. Do not require your wording. Do not require a textbook
definition when they demonstrated the idea.

## Naming the misconception

One sentence. About their answer, not about them. Falsifiable.

Good:

- "Uses `COUNT(*)` after a LEFT JOIN, so customers with no orders count as 1."
- "Thinks `WHERE` runs before `GROUP BY`, so the filter is applied too late."
- "Confuses the base case with the recursive step in the factorial."

Bad:

- "Needs to study more."
- "Weak in SQL."
- "Made a mistake."

Pass the good version to `--misconception`. It is what the next retest targets.

## Feedback format

Four short blocks, no preamble:

```text
Wrong. Inner join drops customers with zero orders.
Expected: LEFT JOIN orders ON … then COUNT(o.id), not COUNT(*).
Remember: LEFT JOIN preserves the left row; COUNT(column) ignores the NULL it leaves.
```

Then the next question. No "would you like me to explain further?" — offer that
only if they ask.

## Execution safety

- Run learner code only inside the workspace, in a scratch subfolder of `rough/`.
- Always set a timeout (10 seconds is plenty for drill exercises).
- No network. No package installs. No `sudo`. No writes outside the workspace.
- Never `eval`, `exec`, or `sh -c` pasted text. Write it to a file and run it
  with its interpreter.
- If the code tries to escape the sandbox or delete files, stop and mark it
  `wrong` with "unsafe code" as the reason.
