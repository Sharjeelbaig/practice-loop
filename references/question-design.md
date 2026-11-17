# Question design

One question. Unambiguous. One defensible correct answer. At the right
difficulty. Different from the last time unless you are deliberately retesting.

## Calibrate to the requested difficulty

| Level | What it looks like |
| --- | --- |
| Beginner | One concept per question, familiar surface, worked pattern still visible. Tests recall and single-step application. |
| Intermediate | Two concepts combined, realistic framing, no pattern hint. Tests application and debugging. |
| Advanced | Trade-offs, edge cases, performance, correctness under constraints. Tests judgement, not recall. |

`adaptive` means the CLI already chose the level from recent accuracy. Do not
second-guess it upward because the learner seems confident.

## Multiple choice

- Exactly four options, exactly one correct, unless the learner asked for
  multi-select.
- Distractors must come from real misconceptions, not filler. "None of the
  above" and joke options are banned.
- Keep option lengths similar. The correct answer must not be the longest or the
  most hedged.
- Randomise the correct position. Do not let it be B or C by habit.
- No giveaway stems ("Which of the following is the LEFT JOIN…").
- Avoid negative phrasing unless the point is precision; if you use it, bold
  **NOT**.
- Do not reuse a stem with new options. Write a new question.
- Use the host's interactive question tool when available. If not, print A–D and
  ask for a letter.

## Exercises

- Give a realistic task, not a puzzle. It should sound like work someone would
  actually do.
- State the language, dialect, function signature, and constraints.
- Include one sample input and expected output, plus one edge case the learner
  must think about but that you do not solve for them.
- Target 2–15 minutes. If it needs more, split it.
- Never include the solution, a partial skeleton that gives it away, or hidden
  requirements revealed only at grading time.
- For code, name the language version and how it will be run.
- For SQL, always include the schema (columns and types) and a few sample rows.
  State the dialect: SQLite, PostgreSQL, MySQL, SQL Server, Oracle. Do not grade
  T-SQL against SQLite and call it wrong.
- Ask them to put the work in `rough/<subject>/<short-name>/` or paste it. Both
  are fine; read the file if they give a path.

### SQL exercise shape

```text
Dialect: PostgreSQL
Schema:
  customers(id int pk, name text, created_at date)
  orders(id int pk, customer_id int fk, total numeric, created_at date)
Sample rows: ...
Task: Return each customer's name and order count, including customers with
zero orders. Order by count descending, then name.
Expected columns: name, order_count
```

### Code exercise shape

```text
Language: C# 12 (.NET 8)
Task: Implement `int LongestRun(string s)` returning the length of the longest
run of identical characters. Empty string → 0.
Examples: "aabbb" → 3, "" → 0, "ab" → 1
Constraints: 0 ≤ s.Length ≤ 10^5, ASCII letters only.
Put it in rough/csharp-dsa/longest-run/ or paste it.
```

## Conceptual

- Ask for a mechanism, a prediction, or a comparison: "why does …", "what
  happens if …", "when would you choose … over …".
- Do not accept a definition recited from the chunk. Follow up with "why" or
  "give an example where that breaks".
- Pure trivia ("who invented…", "what year…") is allowed only if the learner's
  material explicitly requires it.
- One question may have multiple defensible answers. If so, grade the reasoning,
  not the conclusion, and say so.

## Retesting a weakness

When `focus.kind` is `weak`, the point is retrieval, not recognition.

- Change the surface: new domain, new table, new numbers, reversed direction.
- Keep the same underlying misconception in the trap.
- Do not reuse the exact question they failed. That tests memory of the question.
- After two clean answers, move on. Do not grind a cleared topic.
- If they fail again, do not re-ask immediately. The rotation carries them to
  another subject first; the next pass will retest.

## Coverage

`focus.kind == "chunk"` means that chunk has not been covered. Draw the question
from its `concepts:` list, not from material outside the subject. `focus.kind ==
"new"` means no chunks exist or all are covered; use breadth inside the subject
and stay at the requested level.

## Anti-patterns

- A question whose answer appears in the question.
- Two correct options, or a "best answer" with no defensible ranking.
- Testing a detail you never taught and the learner cannot derive.
- "Trick" questions with no transfer value.
- Asking the same question twice because it is easy to grade.
- Mixing two subjects in one question when the rotation says one.
- Turning a coding exercise into an MCQ because it is easier to grade.
- Letting the learner's confidence choose the difficulty.
