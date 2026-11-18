# Workspace contract

A practice-loop workspace is a normal folder. Nothing is hidden except
`.practice-loop/`. The learner can open it in an editor, commit it to git, or
move it between machines and agents.

```text
my-practice/
├── notes/                  learner-owned source material (read-only to you)
├── rough/                  learner's scratch space for solving exercises
├── weak/                   generated: active weaknesses
│   ├── sql/
│   │   └── joins.md
│   └── mastered/           cleared weaknesses, kept so they can reopen
│       └── sql/
│           └── aggregation.md
├── topics/                 teaching material, one folder per subject
│   └── sql/
│       ├── ROADMAP.json    course plan: topics, then chunk titles
│       ├── ROADMAP.md      rendered roadmap with progress checkboxes
│       ├── select-basics/
│       │   ├── anatomy-of-a-select.md
│       │   └── filtering-rows.md
│       └── joins/
│           ├── inner-joins.md
│           └── left-join-nulls.md
├── .practice-loop/
│   ├── state.json          rotation, pending question, teach progress
│   └── history.jsonl       append-only attempt log
└── HOW-IT-WORKS.md         generated primer, never overwritten
```

## Ownership

| Path | You may | You must not |
| --- | --- | --- |
| `notes/` | read for grounding | write, rename, reformat, delete |
| `rough/` | read submissions; create exercise scaffolds under a new subfolder | delete or rewrite the learner's files |
| `weak/` | create/update through the CLI | hand-edit counters or status |
| `topics/` | create/update the roadmap and chunks through `teach plan` and the paths it names | delete a chunk the learner is mid-way through, or flatten a topic into one file |
| `.practice-loop/` | write through the CLI | edit by hand while the CLI is available |
| `HOW-IT-WORKS.md` | read | overwrite an existing copy |

`weak/*.md` is a rendered view of `.practice-loop/state.json`. If you edit the
counters by hand, the next `record` overwrites them. You may edit the
`## Notes` section — it is preserved across regeneration. Put durable
observations there ("mixes up `HAVING` and `WHERE` when aggregates are
involved") and keep the frontmatter alone.

## Discovery

The CLI walks up from the current directory looking for
`.practice-loop/state.json`, then for a directory containing both `notes/` and
`topics/`. If neither exists, it uses the current directory and refuses
commands that need state.

This means one shell `cd` is enough:

```bash
cd ~/practice-loops/sql-and-csharp
python3 "$CLI" next --json
```

Pass `--workspace /path` only when you cannot change directory.

## Initialize

```bash
python3 "$CLI" init --dir . --subjects sql,csharp-dsa,oop
```

`init` creates `notes/ rough/ weak/ topics/ .practice-loop/`, writes
`HOW-IT-WORKS.md` if absent, and creates `state.json` with an empty rotation.
It also creates `topics/<subject>/` for each subject given.

Teaching material is planned separately: write `topics/<subject>/ROADMAP.json`
and run `teach plan --subject <slug>`. See `authoring.md`.

It is idempotent and additive:

- existing folders are left alone;
- an existing `state.json` is loaded, not reset;
- `notes/` and `rough/` contents are never touched;
- `HOW-IT-WORKS.md` is not overwritten, and is skipped when a
  `how it works.txt` already exists.

Never "fix" a workspace by deleting `.practice-loop/`. Use `reset --yes` if the
learner explicitly wants a clean slate; it keeps `notes/`, `rough/`, and
`topics/`.

## Subject slugs

Subjects are lowercase kebab-case: `sql`, `csharp-dsa`, `oop`, `dbms`,
`csharp-theory`, `system-design`. Slugs are derived from the learner's words,
so "C# DSA" becomes `csharp-dsa` and "OOP" becomes `oop`. Keep the slug stable —
`weak/` and `topics/` are keyed by it.

Titles are for display only; the slug is the identity. `rotation.labels` keeps
the learner's wording (`C# DSA`) so screens and reports never show `c-dsa`. Do
not rename a subject mid-workspace unless the learner asks; add a new one
instead.

## Multiple workspaces

One workspace per goal (`~/practice-loops/interview-prep`,
`~/practice-loops/university/dbms`). They are independent. Do not merge state
between them or copy `weak/` across; the CLI has no merge command.
