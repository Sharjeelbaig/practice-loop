#!/usr/bin/env python3
"""practice-loop state manager.

Single source of truth for a practice-loop workspace: subject rotation,
pending question, attempt history, weakness lifecycle, and teach progress.

Pure standard library. Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = 1
STATE_DIR = ".practice-loop"
STATE_FILE = "state.json"
HISTORY_FILE = "history.jsonl"
DIFFICULTIES = ("beginner", "intermediate", "advanced")
TYPES = ("mcq", "exercise", "conceptual")
RESULTS = ("correct", "partial", "wrong", "skipped")
WEIGHT = {"correct": 1.0, "partial": 0.5, "wrong": 0.0, "skipped": None}
MAX_TEXT = 4000
ROADMAP_FILE = "ROADMAP.json"
ROADMAP_MD = "ROADMAP.md"
ROADMAP_MIN_TOPICS = 2
ROADMAP_MIN_CHUNKS = 2
ROADMAP_MAX_CHUNKS = 8

PRIMER = """# practice-loop workspace

This folder is a practice workspace. The agent reads it, quizzes you from it,
and remembers what you get wrong.

| Folder | Owner | Purpose |
| --- | --- | --- |
| `notes/` | you | Your own material. The agent reads it, never writes it. |
| `rough/` | you | Scratch space for solving exercises. The agent may add scaffolds here. |
| `topics/` | agent | One folder per subject: a `ROADMAP.json` plan, then one folder per topic, one `.md` per chunk. |
| `weak/` | agent | Concepts you got wrong. Taught and retested until you clear them. |
| `.practice-loop/` | agent | Machine state: rotation, pending question, history. Do not hand-edit. |

## Flows

- `start` — main flow. One question at a time, rotating subjects in a fixed
  order, mixing MCQs and exercises. Wrong answers create or strengthen a
  weakness.
- `teach` — teach flow. The agent first writes a complete roadmap of topics,
  then teaches one chunk at a time inside each topic and checks understanding.
- `journey` — the weekly path. Monday–Thursday are lessons, Friday is an exam.
  The CLI decides today's session; missed days become catch-up, not skips. Each
  lesson day ends with assignments and, when the course allows it, a lab task.

Each course is a roadmap of topics; each topic is several small chunks. One
topic is never one lesson.

Correct answers in the teach flow never clear a weakness. Only a correct answer
in the main flow does. Teaching proves you followed an explanation; the main
flow proves you can retrieve it cold.

## Commands

`start`, `teach`, `journey`, `list-topics`, `quick-teach`, `status`, `weak`,
`report`, `hint`, `skip`, `easier`, `harder`, `new session`, `reset`.

Progress lives in this folder, so the same workspace works in OpenCode, Claude
Code, Codex, or any other agent.
"""


# --------------------------------------------------------------------------- #
# utilities
# --------------------------------------------------------------------------- #


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = value.replace("#", "sharp").replace("++", "pp")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "general"


def trim(value: Optional[str], limit: int = MAX_TEXT) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".swp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# workspace + state
# --------------------------------------------------------------------------- #


def find_workspace(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    cwd = Path.cwd().resolve()
    for directory in (cwd, *cwd.parents):
        if (directory / STATE_DIR / STATE_FILE).is_file():
            return directory
    for directory in (cwd, *cwd.parents):
        if (directory / "notes").is_dir() and (directory / "topics").is_dir():
            return directory
    return cwd


def state_path(ws: Path) -> Path:
    return ws / STATE_DIR / STATE_FILE


def history_path(ws: Path) -> Path:
    return ws / STATE_DIR / HISTORY_FILE


def default_subject() -> Dict[str, Any]:
    return {
        "asked": 0,
        "correct": 0,
        "partial": 0,
        "wrong": 0,
        "skipped": 0,
        "level": 1,
        "correct_streak": 0,
        "recent": [],
        "last_seen": None,
    }


def default_state() -> Dict[str, Any]:
    stamp = now_iso()
    return {
        "version": VERSION,
        "created_at": stamp,
        "updated_at": stamp,
        "config": {
            "difficulty": "adaptive",
            "types": ["mcq", "exercise"],
            "continuous": True,
            "mastery_streak": 1,
            "limit": 0,
        },
        "rotation": {"subjects": [], "labels": {}, "index": 0, "cycle": 1},
        "subjects": {},
        "pending": None,
        "session": {
            "id": stamp,
            "started_at": stamp,
            "asked": 0,
            "correct": 0,
            "partial": 0,
            "wrong": 0,
            "skipped": 0,
        },
        "teach": {},
        "journey": {},
        "weak": {},
    }


def load_state(ws: Path) -> Dict[str, Any]:
    raw = read_json(state_path(ws))
    if not raw:
        return default_state()
    state = default_state()
    state.update(raw)
    for key in ("config", "rotation", "session", "teach", "weak", "subjects", "journey"):
        if not isinstance(state.get(key), dict):
            state[key] = default_state()[key]
    state.setdefault("pending", None)
    state["version"] = VERSION
    return state


def save_state(ws: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    atomic_write(state_path(ws), json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def ensure_subject(state: Dict[str, Any], slug: str) -> Dict[str, Any]:
    state["subjects"].setdefault(slug, default_subject())
    state["rotation"].setdefault("labels", {}).setdefault(slug, slug)
    return state["subjects"][slug]


def subject_label(state: Dict[str, Any], slug: str) -> str:
    """Display name for a subject slug; falls back to the slug itself."""
    return (state.get("rotation", {}).get("labels") or {}).get(slug, slug)


def parse_subjects(value: str) -> "tuple[List[str], Dict[str, str]]":
    """Split a comma list into slugs and a slug -> learner's wording map."""
    slugs: List[str] = []
    labels: Dict[str, str] = {}
    for part in str(value).split(","):
        raw = part.strip()
        if not raw:
            continue
        slug = slugify(raw)
        if not slug:
            continue
        if slug not in slugs:
            slugs.append(slug)
        labels[slug] = raw
    return slugs, labels


def apply_subjects(state: Dict[str, Any], value: str) -> "tuple[List[str], Dict[str, str]]":
    """Replace the rotation, preserving order and display names."""
    slugs, labels = parse_subjects(value)
    state["rotation"]["subjects"] = slugs
    state["rotation"]["labels"] = labels
    state["rotation"]["index"] = 0
    state["rotation"]["cycle"] = 1
    state["pending"] = None
    # Drop untouched leftovers from an earlier subject list; real progress stays.
    for slug in [item for item in state.get("subjects", {}) if item not in slugs]:
        stats = state["subjects"][slug]
        touched = any(int(stats.get(key) or 0) for key in ("asked", "correct", "partial", "wrong", "skipped"))
        if not touched and not state.get("weak", {}).get(slug):
            del state["subjects"][slug]
    return slugs, labels


def read_history(ws: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    path = history_path(ws)
    if not path.is_file():
        return rows
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def append_history(ws: Path, row: Dict[str, Any]) -> None:
    path = history_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# weakness rendering
# --------------------------------------------------------------------------- #


def weak_dir(ws: Path) -> Path:
    return ws / "weak"


def mastered_dir(ws: Path) -> Path:
    return weak_dir(ws) / "mastered"


def weak_file(ws: Path, subject: str, topic: str) -> Path:
    return weak_dir(ws) / slugify(subject) / (slugify(topic) + ".md")


def mastered_file(ws: Path, subject: str, topic: str) -> Path:
    return mastered_dir(ws) / slugify(subject) / (slugify(topic) + ".md")


def read_notes_block(path: Path) -> str:
    """Preserve a hand-written '## Notes' section across regeneration."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    marker = "\n## Notes\n"
    if marker not in text:
        return ""
    notes = text.split(marker, 1)[1].strip()
    return notes


def render_weak(ws: Path, subject: str, topic: str, record: Dict[str, Any]) -> None:
    status = record.get("status", "weak")
    target = mastered_file(ws, subject, topic) if status == "mastered" else weak_file(ws, subject, topic)
    stale = weak_file(ws, subject, topic) if status == "mastered" else mastered_file(ws, subject, topic)
    notes = read_notes_block(stale) or read_notes_block(target)

    lines = [
        "---",
        f"subject: {subject}",
        f"topic: {topic}",
        *([f"unit: {record.get('unit')}"] if record.get("unit") else []),
        f"status: {status}",
        f"misses: {record.get('misses', 0)}",
        f"partials: {record.get('partials', 0)}",
        f"hits: {record.get('hits', 0)}",
        f"streak: {record.get('streak', 0)}",
        f"required_streak: {record.get('required_streak', 1)}",
        f"regressions: {record.get('regressions', 0)}",
        f"first_seen: {record.get('first_seen')}",
        f"last_seen: {record.get('last_seen')}",
        f"last_result: {record.get('last_result')}",
        "---",
        "",
        f"# {subject} / {topic}",
        "",
    ]
    if status == "mastered":
        lines += [
            f"Cleared on {record.get('mastered_at')} after {record.get('hits', 0)} correct "
            f"main-flow answer(s). It reopens if it is missed again.",
            "",
        ]
    else:
        lines += [
            f"Missed {record.get('misses', 0)} time(s), partial {record.get('partials', 0)} "
            f"time(s). Needs {record.get('required_streak', 1)} clean main-flow answer(s) in a row.",
            "",
        ]

    misconceptions = record.get("misconceptions") or []
    if misconceptions:
        lines.append("## Misconceptions")
        for item in misconceptions[-8:]:
            lines.append(f"- {item}")
        lines.append("")

    retest = record.get("retest")
    if retest:
        lines += ["## Retest notes", retest, ""]

    lines += ["## Notes", notes or "_Add your own notes here._", ""]
    atomic_write(target, "\n".join(lines))
    if stale.exists() and stale != target:
        try:
            stale.unlink()
            parent = stale.parent
            if parent.is_dir() and not any(parent.iterdir()) and parent.name != "mastered":
                parent.rmdir()
        except OSError:
            pass


def required_streak(state: Dict[str, Any], record: Dict[str, Any]) -> int:
    base = max(1, int(state["config"].get("mastery_streak", 1)))
    if int(record.get("misses", 0)) >= 3 or int(record.get("regressions", 0)) > 0:
        return max(2, base)
    return base


def get_weak(state: Dict[str, Any], subject: str, topic: str) -> Optional[Dict[str, Any]]:
    return state.get("weak", {}).get(slugify(subject), {}).get(slugify(topic))


def put_weak(state: Dict[str, Any], subject: str, topic: str, record: Dict[str, Any]) -> None:
    state.setdefault("weak", {}).setdefault(slugify(subject), {})[slugify(topic)] = record


def active_weak(state: Dict[str, Any], subject: str) -> List[Dict[str, Any]]:
    items = []
    for topic, record in state.get("weak", {}).get(slugify(subject), {}).items():
        if record.get("status") != "mastered":
            item = dict(record)
            item["topic"] = topic
            items.append(item)
    items.sort(key=lambda item: (-int(item.get("misses", 0)), str(item.get("last_seen") or "")))
    return items


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #


class Ctx:
    def __init__(self, workspace: Path, as_json: bool) -> None:
        self.ws = workspace
        self.json = as_json


def emit(ctx: Ctx, payload: Dict[str, Any], human: Optional[str] = None) -> int:
    if ctx.json:
        payload.setdefault("ok", True)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(human if human is not None else json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def fail(ctx: Ctx, message: str, code: int = 2, **extra: Any) -> int:
    if ctx.json:
        payload = {"ok": False, "error": message}
        payload.update(extra)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"error: {message}", file=sys.stderr)
    return code


def pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{round(value * 100)}%"


def accuracy(correct: float, partial: float, wrong: float) -> Optional[float]:
    total = correct + partial + wrong
    if total <= 0:
        return None
    return (correct + 0.5 * partial) / total


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #


def cmd_init(args, ctx: Ctx) -> int:
    target = Path(args.dir).expanduser().resolve() if args.dir else (ctx.ws if ctx.ws else Path.cwd())
    target.mkdir(parents=True, exist_ok=True)

    for name in ("notes", "rough", "weak", "topics"):
        (target / name).mkdir(exist_ok=True)
    (target / STATE_DIR).mkdir(exist_ok=True)

    existing = read_json(state_path(target))
    state = existing or default_state()
    created = existing is None

    subjects: List[str] = []
    if args.subjects:
        subjects, _ = apply_subjects(state, str(args.subjects))
    if subjects:
        for slug in subjects:
            ensure_subject(state, slug)
            (target / "topics" / slug).mkdir(parents=True, exist_ok=True)
    if args.difficulty:
        if args.difficulty not in DIFFICULTIES and args.difficulty != "adaptive":
            return fail(ctx, f"difficulty must be one of: adaptive, {', '.join(DIFFICULTIES)}")
        state["config"]["difficulty"] = args.difficulty
    if args.limit is not None:
        if args.limit < 0:
            return fail(ctx, "limit must be 0 (continuous) or a positive number")
        state["config"]["limit"] = args.limit
    if args.types:
        types = [part.strip() for part in str(args.types).split(",") if part.strip()]
        bad = [item for item in types if item not in TYPES]
        if bad:
            return fail(ctx, f"unknown type(s): {', '.join(bad)}; allowed: {', '.join(TYPES)}")
        state["config"]["types"] = types or list(TYPES)

    primer = target / "HOW-IT-WORKS.md"
    primer_created = False
    if not primer.exists() and not (target / "how it works.txt").exists():
        atomic_write(primer, PRIMER)
        primer_created = True

    save_state(target, state)

    payload = {
        "ok": True,
        "workspace": str(target),
        "created": created,
        "directories": ["notes", "rough", "weak", "topics", STATE_DIR],
        "subjects": state["rotation"]["subjects"],
        "labels": state["rotation"].get("labels", {}),
        "difficulty": state["config"]["difficulty"],
        "types": state["config"]["types"],
        "limit": state["config"].get("limit", 0),
        "primer_created": primer_created,
    }
    if created:
        human = f"workspace ready: {target}\n"
    else:
        human = f"workspace already initialized: {target}\n"
    human += (
        "folders: notes/ rough/ weak/ topics/ " + STATE_DIR + "/\n"
        f"subjects: {', '.join(subject_label(state, s) for s in state['rotation']['subjects']) or '(none yet)'}\n"
        f"difficulty: {state['config']['difficulty']}  types: {', '.join(state['config']['types'])}\n"
        f"limit: {state['config'].get('limit', 0) or 'continuous'}\n"
        "next: add subjects, then run start"
    )
    return emit(ctx, payload, human)


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #


def cmd_status(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)

    rotation = state["rotation"]
    subjects = rotation["subjects"]
    session = state["session"]
    weak_total = sum(len(active_weak(state, sub)) for sub in subjects)

    pending = state.get("pending")
    limit = int(state["config"].get("limit", 0) or 0)
    teach_summary: Dict[str, Any] = {}
    for sub in subjects:
        plan, plan_errors = load_roadmap(ctx.ws, sub)
        progress = teach_progress(state, sub)
        if plan is None or plan_errors:
            teach_summary[sub] = {
                "ready": False,
                "reason": "no_plan" if plan is None else "invalid_plan",
                "completed": len(progress["completed"]),
                "current": progress.get("current"),
                "chunks_total": 0,
                "chunks_done": 0,
                "topics_total": 0,
                "topics_done": 0,
            }
        else:
            counts = roadmap_counts(plan, set(progress["completed"]))
            teach_summary[sub] = {
                "ready": True,
                "completed": counts["chunks_done"],
                "current": progress.get("current"),
                **counts,
            }
    payload = {
        "ok": True,
        "workspace": str(ctx.ws),
        "subjects": subjects,
        "labels": {sub: subject_label(state, sub) for sub in subjects},
        "position": (rotation["index"] + 1) if subjects else 0,
        "of": len(subjects),
        "cycle": rotation["cycle"],
        "difficulty": state["config"]["difficulty"],
        "types": state["config"]["types"],
        "limit": limit or None,
        "session_remaining": None if limit <= 0 else max(0, limit - int(session.get("asked", 0))),
        "pending": pending,
        "session": session,
        "weak_active": weak_total,
        "teach": teach_summary,
    }

    lines = [f"workspace: {ctx.ws}"]
    if subjects:
        current = subjects[rotation["index"] % len(subjects)]
        lines.append(
            f"rotation: {subject_label(state, current)} ({rotation['index'] + 1}/{len(subjects)}), cycle {rotation['cycle']}"
        )
        lines.append("order: " + " → ".join(subject_label(state, sub) for sub in subjects))
    else:
        lines.append("rotation: no subjects yet")
    lines.append(f"difficulty: {state['config']['difficulty']}  types: {', '.join(state['config']['types'])}")
    limit = int(state["config"].get("limit", 0) or 0)
    if limit:
        lines.append(f"session limit: {limit} ({max(0, limit - int(session.get('asked', 0)))} left)")
    asked = session["asked"]
    acc = accuracy(session["correct"], session["partial"], session["wrong"])
    lines.append(
        f"session: {asked} asked, {session['correct']} correct, {session['partial']} partial, "
        f"{session['wrong']} wrong ({pct(acc)})"
    )
    lines.append(f"weak topics: {weak_total}")
    if pending:
        lines.append(
            f"pending: {subject_label(state, pending.get('subject'))} / {(pending.get('focus') or {}).get('topic') or 'new material'} "
            f"— record or skip it before asking another"
        )
    if payload["teach"]:
        bits = []
        for sub, info in payload["teach"].items():
            if not info.get("ready"):
                continue
            bits.append(
                f"{subject_label(state, sub)} {info['chunks_done']}/{info['chunks_total']} chunks · "
                f"{info['topics_done']}/{info['topics_total']} topics"
            )
        if bits:
            lines.append("teach: " + ", ".join(bits))
    return emit(ctx, payload, "\n".join(lines))


# --------------------------------------------------------------------------- #
# next
# --------------------------------------------------------------------------- #


def chunk_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return path.stem
    match = re.search(r"^title:\s*(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip().strip("\"'")
    return path.stem


# --------------------------------------------------------------------------- #
# roadmap: subject -> topics -> chunks
# --------------------------------------------------------------------------- #


def roadmap_json_path(ws: Path, subject: str) -> Path:
    return ws / "topics" / slugify(subject) / ROADMAP_FILE


def roadmap_md_path(ws: Path, subject: str) -> Path:
    return ws / "topics" / slugify(subject) / ROADMAP_MD


def teach_progress(state: Dict[str, Any], subject: str) -> Dict[str, Any]:
    progress = state.setdefault("teach", {}).setdefault(
        slugify(subject), {"completed": [], "current": None, "checks": 0, "attempts": {}}
    )
    progress.setdefault("completed", [])
    progress.setdefault("attempts", {})
    progress.setdefault("current", None)
    progress["completed"] = list(dict.fromkeys(str(item) for item in progress["completed"]))
    return progress


def load_roadmap(ws: Path, subject: str) -> "tuple[Optional[Dict[str, Any]], List[str]]":
    """Read and validate topics/<subject>/ROADMAP.json.

    Returns (plan, errors). The plan is present but incomplete when errors are
    returned, so callers can still show the agent what is wrong.
    """
    subject = slugify(subject)
    path = roadmap_json_path(ws, subject)
    rel = f"topics/{subject}/{ROADMAP_FILE}"
    if not path.is_file():
        return None, [f"{rel} is missing"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"{rel} is not valid JSON: {exc}"]
    if not isinstance(raw, dict):
        return None, [f"{rel} must contain a JSON object"]

    errors: List[str] = []
    raw_topics = raw.get("topics")
    if not isinstance(raw_topics, list) or not raw_topics:
        errors.append("topics must be a non-empty array")
        raw_topics = []
    if raw_topics and len(raw_topics) < ROADMAP_MIN_TOPICS:
        errors.append(
            f"a roadmap needs at least {ROADMAP_MIN_TOPICS} topics; one topic is not a course. "
            "Split it into its major units."
        )

    subject_dir = path.parent
    course_title = str(raw.get("title") or subject).strip()
    topics: List[Dict[str, Any]] = []
    all_chunks: List[Dict[str, Any]] = []
    seen_topics: Dict[str, str] = {}

    for topic_index, item in enumerate(raw_topics, 1):
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            errors.append(f"topic {topic_index} must be an object or a title string")
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            errors.append(f"topic {topic_index} has no title")
            continue
        title_slug = slugify(title)
        if title_slug == subject or title_slug == slugify(course_title):
            errors.append(
                f"topic '{title}' just repeats the course name; a topic must be one unit "
                "inside the course, not the whole course"
            )
            continue
        topic_id = slugify(str(item.get("id") or title))
        if topic_id in seen_topics:
            errors.append(f"duplicate topic id '{topic_id}' (also used by '{seen_topics[topic_id]}')")
            continue
        seen_topics[topic_id] = title
        topic_dir = topic_id
        outcome = str(item.get("outcome") or "").strip()

        raw_chunks = item.get("chunks")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            errors.append(f"topic '{title}' needs a non-empty chunks array")
            raw_chunks = []
        elif len(raw_chunks) < ROADMAP_MIN_CHUNKS:
            errors.append(
                f"topic '{title}' has {len(raw_chunks)} chunk; a topic must have at least "
                f"{ROADMAP_MIN_CHUNKS} chunks. Split the topic into teachable pieces."
            )
        elif len(raw_chunks) > ROADMAP_MAX_CHUNKS:
            errors.append(
                f"topic '{title}' has {len(raw_chunks)} chunks; keep topics to at most "
                f"{ROADMAP_MAX_CHUNKS} chunks and split the topic."
            )

        chunks: List[Dict[str, Any]] = []
        seen_chunks: Dict[str, str] = {}
        for chunk_index, raw_chunk in enumerate(raw_chunks, 1):
            if isinstance(raw_chunk, str):
                raw_chunk = {"title": raw_chunk}
            if not isinstance(raw_chunk, dict):
                errors.append(f"topic '{title}' chunk {chunk_index} must be an object or a title string")
                continue
            chunk_name = str(raw_chunk.get("title") or "").strip()
            if not chunk_name:
                errors.append(f"topic '{title}' chunk {chunk_index} has no title")
                continue
            chunk_id = slugify(str(raw_chunk.get("id") or chunk_name))
            if chunk_id in seen_chunks:
                errors.append(
                    f"duplicate chunk '{chunk_name}' in topic '{title}' "
                    f"(also used by '{seen_chunks[chunk_id]}')"
                )
                continue
            seen_chunks[chunk_id] = chunk_name
            file_name = f"{chunk_id}.md"
            key = f"{topic_dir}/{file_name}"
            chunk = {
                "index": len(all_chunks) + 1,
                "index_in_topic": chunk_index,
                "id": chunk_id,
                "file": file_name,
                "key": key,
                "title": chunk_name,
                "path": str(subject_dir / topic_dir / file_name),
                "topic_index": topic_index,
                "topic_id": topic_id,
                "topic_title": title,
                "topic_dir": topic_dir,
                "topic_outcome": outcome,
            }
            chunks.append(chunk)
            all_chunks.append(chunk)

        topics.append(
            {
                "index": topic_index,
                "id": topic_id,
                "dir": topic_dir,
                "title": title,
                "outcome": outcome,
                "path": str(subject_dir / topic_dir),
                "chunks": chunks,
            }
        )

    plan = {
        "subject": subject,
        "title": str(raw.get("title") or "").strip(),
        "outcome": str(raw.get("outcome") or "").strip(),
        "path": str(path),
        "markdown": str(roadmap_md_path(ws, subject)),
        "subject_dir": str(subject_dir),
        "topics": topics,
        "chunks": all_chunks,
    }
    return plan, errors


def roadmap_counts(plan: Dict[str, Any], completed: set) -> Dict[str, int]:
    chunks_done = sum(1 for chunk in plan["chunks"] if chunk["key"] in completed)
    topics_done = sum(
        1
        for topic in plan["topics"]
        if topic["chunks"] and all(chunk["key"] in completed for chunk in topic["chunks"])
    )
    return {
        "chunks_done": chunks_done,
        "chunks_total": len(plan["chunks"]),
        "topics_done": topics_done,
        "topics_total": len(plan["topics"]),
    }


def next_plan_chunk(
    plan: Dict[str, Any], completed: set, topic_filter: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    for topic in plan["topics"]:
        if topic_filter is not None and topic["id"] != topic_filter["id"]:
            continue
        for chunk in topic["chunks"]:
            if chunk["key"] not in completed:
                item = dict(chunk)
                item["chunk_total"] = len(topic["chunks"])
                return item
    return None


def match_topic(plan: Dict[str, Any], value: str) -> Optional[Dict[str, Any]]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        position = int(raw)
        if 1 <= position <= len(plan["topics"]):
            return plan["topics"][position - 1]
    wanted = slugify(raw)
    for topic in plan["topics"]:
        if wanted in (topic["id"], slugify(topic["dir"]), slugify(topic["title"])):
            return topic
    for topic in plan["topics"]:
        if wanted and wanted in topic["id"]:
            return topic
    return None


def resolve_chunk(plan: Dict[str, Any], value: str) -> Optional[Dict[str, Any]]:
    """Resolve a chunk key, filename, or path against the plan."""
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return None
    for chunk in plan["chunks"]:
        if raw == chunk["key"]:
            return chunk
    matches = [
        chunk
        for chunk in plan["chunks"]
        if raw == chunk["file"] or raw.endswith("/" + chunk["key"]) or raw.endswith("/" + chunk["file"])
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def render_roadmap_md(ws: Path, state: Dict[str, Any], subject: str, plan: Dict[str, Any]) -> str:
    completed = set(teach_progress(state, subject)["completed"])
    counts = roadmap_counts(plan, completed)
    title = plan["title"] or subject_label(state, subject)
    lines = [f"# {title} — Roadmap", ""]
    if plan["outcome"]:
        lines += [plan["outcome"], ""]
    lines.append(
        f"**Progress:** {counts['chunks_done']}/{counts['chunks_total']} chunks · "
        f"{counts['topics_done']}/{counts['topics_total']} topics complete"
    )
    lines.append("")
    for topic in plan["topics"]:
        lines.append(f"## {topic['index']}. {topic['title']}")
        if topic["outcome"]:
            lines.append(topic["outcome"])
        lines.append("")
        for chunk in topic["chunks"]:
            box = "x" if chunk["key"] in completed else " "
            lines.append(f"- [{box}] {chunk['index_in_topic']}. {chunk['title']}")
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    atomic_write(roadmap_md_path(ws, subject), text)
    return plan["markdown"]


WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
JOURNEY_TYPES = ("mcq", "exercise", "conceptual")


def current_subject(state: Dict[str, Any]) -> Optional[str]:
    subjects = state.get("rotation", {}).get("subjects") or []
    if not subjects:
        return None
    return subjects[int(state["rotation"].get("index", 0)) % len(subjects)]


def count_label(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def default_journey_start(today: date) -> date:
    """Start today Mon-Thu, otherwise the coming Monday."""
    if today.weekday() <= 3:
        return today
    return today + timedelta(days=7 - today.weekday())


def parse_journey_start(value: Optional[str], today: date) -> date:
    if not value:
        return default_journey_start(today)
    raw = str(value).strip().lower()
    if raw in ("today", "now"):
        start = today
    elif raw in ("next-monday", "monday"):
        start = today + timedelta(days=(0 - today.weekday()) % 7)
    else:
        try:
            start = date.fromisoformat(str(value).strip())
        except ValueError:
            raise ValueError("start must be today, next-monday, or YYYY-MM-DD")
    if start.weekday() >= 5:
        start = start + timedelta(days=7 - start.weekday())
    return start


def default_journey_config(state: Dict[str, Any], today: date) -> Dict[str, Any]:
    types = [item for item in state["config"].get("types", []) if item in JOURNEY_TYPES]
    return {
        "start": default_journey_start(today).isoformat(),
        "chunks_per_day": 2,
        "exam_types": types or ["mcq", "exercise"],
        "exam_questions": 8,
        "exam_scope": "week",
        "labs": "auto",
        "created_at": now_iso(),
        "exams": {},
        "wrapped": [],
    }


def build_journey_sessions(plan: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn roadmap chunks into Mon-Thu teaching days and Friday exams."""
    chunks = plan["chunks"]
    chunk_map = {chunk["key"]: chunk for chunk in chunks}
    try:
        day = date.fromisoformat(config["start"])
    except (KeyError, ValueError):
        day = default_journey_start(date.today())
    per_day = max(1, min(6, int(config.get("chunks_per_day", 2) or 2)))
    scope = config.get("exam_scope", "week")
    sessions: List[Dict[str, Any]] = []
    index = 0
    week = 1
    day_in_week = 0
    week_teaching = False
    week_keys: List[str] = []
    all_keys: List[str] = []

    for _ in range(4000):
        if index >= len(chunks) and not week_teaching:
            break
        weekday = day.weekday()
        if weekday >= 5:
            day += timedelta(days=1)
            continue
        if weekday <= 3:
            if index < len(chunks):
                batch = chunks[index : index + per_day]
                index += len(batch)
                keys = [chunk["key"] for chunk in batch]
                week_keys.extend(keys)
                all_keys.extend(keys)
                day_in_week += 1
                week_teaching = True
                sessions.append(
                    {
                        "id": f"w{week}d{day_in_week}",
                        "kind": "teach",
                        "week": week,
                        "day": day_in_week,
                        "date": day.isoformat(),
                        "weekday": WEEKDAY_NAMES[weekday],
                        "chunks": keys,
                    }
                )
        else:
            if week_teaching:
                scope_keys = all_keys if scope == "course" else week_keys
                topics: List[str] = []
                for key in scope_keys:
                    title = chunk_map[key]["topic_title"]
                    if title not in topics:
                        topics.append(title)
                sessions.append(
                    {
                        "id": f"w{week}exam",
                        "kind": "exam",
                        "week": week,
                        "date": day.isoformat(),
                        "weekday": "Fri",
                        "chunks": list(scope_keys),
                        "topics": topics,
                        "question_count": max(1, min(30, int(config.get("exam_questions", 8) or 8))),
                        "types": list(config.get("exam_types") or ["mcq"]),
                        "scope": scope,
                    }
                )
                week += 1
                day_in_week = 0
                week_teaching = False
                week_keys = []
        day += timedelta(days=1)
    return sessions


def journey_session_done(
    session: Dict[str, Any], completed: set, exams: Dict[str, Any]
) -> bool:
    if session["kind"] == "teach":
        return bool(session["chunks"]) and all(key in completed for key in session["chunks"])
    return str(session["week"]) in exams


PRACTICAL_TERMS = (
    "sql", "database", "dbms", "query", "queries", "schema", "index", "join",
    "code", "coding", "programming", "program", "algorithm", "algorithms",
    "data structure", "data structures", "dsa", "javascript", "typescript",
    "python", "java", "c#", "csharp", "c++", "cpp", "react", "nestjs", "node",
    "api", "http", "web", "html", "css", "git", "linux", "terminal", "bash",
    "security", "testing", "refactoring", "design pattern", "architecture",
    "domain-driven", "ddd", "langchain", "langgraph", "machine learning",
    "deep learning", "llm", "llms", "ai", "rag", "prompting", "prompt",
    "embeddings", "retrieval", "excel", "spreadsheet", "math", "statistics",
    "probability", "physics", "chemistry", "biology", "engineering", "finance",
    "accounting", "mathematics", "calculus", "algebra",
)
THEORY_TERMS = (
    "history", "historical", "law", "legal", "literature", "philosophy",
    "ethics", "poetry", "political science", "politics", "sociology",
    "anthropology", "art history", "music theory", "religion", "theology",
)


def term_present(text: str, term: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def course_text(plan: Dict[str, Any], subject: str) -> str:
    parts = [subject, plan.get("title") or "", plan.get("outcome") or ""]
    for topic in plan["topics"]:
        parts.extend([topic["title"], topic.get("outcome") or ""])
        parts.extend(chunk["title"] for chunk in topic["chunks"])
    return " ".join(parts).lower()


def course_is_practical(plan: Dict[str, Any], subject: str) -> bool:
    text = course_text(plan, subject)
    if any(term_present(text, term) for term in PRACTICAL_TERMS):
        return True
    if any(term_present(text, term) for term in THEORY_TERMS):
        return False
    return True


def lab_kind_for(plan: Dict[str, Any], subject: str) -> str:
    text = course_text(plan, subject)
    if any(term_present(text, term) for term in ("sql", "database", "dbms", "query", "queries", "schema", "index", "join")):
        return "sql"
    if any(term_present(text, term) for term in ("math", "mathematics", "calculus", "algebra", "statistics", "probability", "physics", "chemistry", "calculation")):
        return "calculation"
    if any(term_present(text, term) for term in PRACTICAL_TERMS):
        return "code"
    return "exercise"


def assignments_payload(
    session: Dict[str, Any],
    plan: Dict[str, Any],
    config: Dict[str, Any],
    subject: str,
) -> "tuple[Dict[str, Any], Dict[str, Any]]":
    chunk_map = {chunk["key"]: chunk for chunk in plan["chunks"]}
    chunks = [chunk_map[key] for key in session["chunks"] if key in chunk_map]
    topics: List[str] = []
    for chunk in chunks:
        if chunk["topic_title"] not in topics:
            topics.append(chunk["topic_title"])
    focus = "; ".join(f"{chunk['topic_title']} / {chunk['title']}" for chunk in chunks)
    subject_dir = f"rough/{slugify(subject)}"
    practical = course_is_practical(plan, subject)
    if practical:
        apply_item = {
            "kind": "apply",
            "brief": (
                f"Create and solve one new problem that uses {focus}. "
                "Show your steps, not just the final answer."
            ),
        }
    else:
        apply_item = {
            "kind": "analysis",
            "brief": (
                f"Write a short evidence-based answer on {focus}: compare the ideas, "
                "then name one cause and one consequence in your own words."
            ),
        }
    assignments = {
        "count": 2,
        "items": [
            {
                "kind": "teach-back",
                "brief": (
                    f"Close the lesson notes and explain {focus} in your own words. "
                    "Give one example that was not in the lesson."
                ),
            },
            apply_item,
        ],
        "submit": f"{subject_dir}/{session['date']}-assignments.md",
    }

    mode = config.get("labs", "auto")
    enabled = mode == "on" or (mode == "auto" and practical)
    if not enabled:
        lab = {
            "required": False,
            "reason": "This is a theory-only course, so there is no lab task.",
            "mode": mode,
        }
        return assignments, lab

    kind = lab_kind_for(plan, subject)
    if kind == "sql":
        brief = f"Write and run 2-3 SQL queries that use {focus}. Save the SQL and the result tables."
    elif kind == "calculation":
        brief = f"Solve three new calculation problems that use {focus}. Show every step and check one answer."
    elif kind == "code":
        brief = f"Build a small working program that uses {focus}. Save the source, the run command, and the output."
    else:
        brief = f"Make a small applied artifact that uses {focus}. Write one paragraph on what it demonstrates."
    lab = {
        "required": True,
        "kind": kind,
        "brief": brief,
        "submit": f"{subject_dir}/{session['date']}-lab/",
        "mode": mode,
    }
    return assignments, lab


def journey_outline_path(ws: Path, subject: str) -> Path:
    return ws / "topics" / slugify(subject) / "JOURNEY.md"


def render_journey_md(
    ws: Path,
    state: Dict[str, Any],
    subject: str,
    plan: Dict[str, Any],
    config: Dict[str, Any],
) -> str:
    """Render the day-by-day course outline next to the roadmap."""
    sessions = build_journey_sessions(plan, config)
    completed = set(teach_progress(state, subject)["completed"])
    exams = config.get("exams") or {}
    counts = journey_counts(sessions, completed, exams)
    chunk_map = {chunk["key"]: chunk for chunk in plan["chunks"]}
    title = plan["title"] or subject_label(state, subject)

    lines = [f"# {title} — Journey outline", ""]
    lines.append(
        f"Start **{config.get('start')}** · {config.get('chunks_per_day', 2)} chunks/day · "
        f"{config.get('exam_questions', 8)} questions/exam · {config.get('exam_scope', 'week')} scope"
    )
    lines.append(
        f"Progress: **{counts['teaching_done']}/{counts['teaching_total']}** teaching days · "
        f"**{counts['exams_done']}/{counts['exams_total']}** exams · "
        f"**{counts['chunks_done']}/{counts['chunks_total']}** chunks"
    )
    lines.append("")

    current_week = None
    for session in sessions:
        if session["week"] != current_week:
            current_week = session["week"]
            lines += [f"## Week {current_week}", ""]
        planned = date.fromisoformat(session["date"])
        day_label = planned.strftime("%a %d %b")
        if session["kind"] == "teach":
            done = journey_session_done(session, completed, exams)
            topics: List[str] = []
            for key in session["chunks"]:
                topic_title = chunk_map[key]["topic_title"]
                if topic_title not in topics:
                    topics.append(topic_title)
            heading = topics[0] if len(topics) == 1 else f"{len(topics)} topics"
            mark = "x" if done else " "
            lines.append(f"### {day_label} · Lesson {session['day']} — {heading} [{mark}]")
            for key in session["chunks"]:
                chunk = chunk_map[key]
                box = "x" if key in completed else " "
                lines.append(f"- [{box}] {chunk['topic_title']} / {chunk['title']}")
            lines.append("")
        else:
            done = str(session["week"]) in exams
            mark = "x" if done else " "
            lines.append(
                f"### {day_label} · Week {session['week']} exam — "
                f"{session['question_count']} questions ({', '.join(session['types'])}) [{mark}]"
            )
            lines.append(f"Covers: {'; '.join(session['topics'])}")
            if done:
                score = exams[str(session["week"])].get("score")
                lines.append(f"Result: {score or 'recorded'}")
            lines.append("")

    lines.append("_Generated from ROADMAP.json and the journey settings. Edit those, not this file._")
    text = "\n".join(lines).rstrip() + "\n"
    path = journey_outline_path(ws, subject)
    atomic_write(path, text)
    return str(path)


def first_open_session(
    sessions: List[Dict[str, Any]], completed: set, exams: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    for session in sessions:
        if not journey_session_done(session, completed, exams):
            return session
    return None


def journey_counts(
    sessions: List[Dict[str, Any]], completed: set, exams: Dict[str, Any]
) -> Dict[str, int]:
    teaching = [item for item in sessions if item["kind"] == "teach"]
    exam_sessions = [item for item in sessions if item["kind"] == "exam"]
    return {
        "weeks": max((item["week"] for item in sessions), default=0),
        "teaching_total": len(teaching),
        "teaching_done": sum(1 for item in teaching if journey_session_done(item, completed, exams)),
        "exams_total": len(exam_sessions),
        "exams_done": sum(1 for item in exam_sessions if journey_session_done(item, completed, exams)),
        "chunks_total": sum(len(item["chunks"]) for item in teaching),
        "chunks_done": sum(
            1 for item in teaching for key in item["chunks"] if key in completed
        ),
    }


def journey_chunk_payload(
    keys: List[str], plan: Dict[str, Any], completed: set
) -> List[Dict[str, Any]]:
    chunk_map = {chunk["key"]: chunk for chunk in plan["chunks"]}
    rows = []
    for key in keys:
        chunk = chunk_map.get(key)
        if not chunk:
            continue
        path = Path(chunk["path"])
        rows.append(
            {
                "key": key,
                "title": chunk["title"],
                "topic": chunk["topic_id"],
                "topic_title": chunk["topic_title"],
                "path": chunk["path"],
                "exists": path.is_file(),
                "done": key in completed,
            }
        )
    return rows


def session_payload(
    session: Dict[str, Any], plan: Dict[str, Any], completed: set, today: date
) -> Dict[str, Any]:
    planned = date.fromisoformat(session["date"])
    payload: Dict[str, Any] = {
        "id": session["id"],
        "kind": session["kind"],
        "week": session["week"],
        "date": session["date"],
        "weekday": session["weekday"],
        "late_days": max(0, (today - planned).days),
        "overdue": planned < today,
        "scheduled_today": planned == today,
    }
    if session["kind"] == "teach":
        payload["day"] = session["day"]
        payload["chunks"] = journey_chunk_payload(session["chunks"], plan, completed)
        payload["chunk_count"] = len(payload["chunks"])
        topics: List[str] = []
        for chunk in payload["chunks"]:
            if chunk["topic_title"] not in topics:
                topics.append(chunk["topic_title"])
        payload["topics"] = topics
    else:
        payload["chunks"] = journey_chunk_payload(session["chunks"], plan, completed)
        payload["chunk_count"] = len(payload["chunks"])
        payload["topics"] = session["topics"]
        payload["question_count"] = session["question_count"]
        payload["types"] = session["types"]
        payload["scope"] = session["scope"]
    return payload


def pick_focus(ws: Path, state: Dict[str, Any], subject: str) -> Dict[str, Any]:
    stats = ensure_subject(state, subject)
    plan, errors = load_roadmap(ws, subject)
    ready = plan is not None and not errors
    weak = active_weak(state, subject)
    if weak and (stats["asked"] % 2 == 1 or not ready):
        first = weak[0]
        return {
            "kind": "weak",
            "topic": first["topic"],
            "misses": int(first.get("misses", 0)),
            "last_seen": first.get("last_seen"),
            "retest": True,
        }
    if ready:
        progress = teach_progress(state, subject)
        chunk = next_plan_chunk(plan, set(progress["completed"]))
        if chunk:
            path = Path(chunk["path"])
            return {
                "kind": "chunk",
                "topic": chunk["topic_id"],
                "topic_title": chunk["topic_title"],
                "topic_index": chunk["topic_index"],
                "topic_total": len(plan["topics"]),
                "chunk": chunk["key"],
                "chunk_title": chunk["title"],
                "concept": chunk["id"],
                "chunk_index": chunk["index_in_topic"],
                "chunk_total": chunk["chunk_total"],
                "title": chunk["title"],
                "path": str(path) if path.is_file() else None,
                "missing": not path.is_file(),
            }
    return {"kind": "new", "topic": None}


def target_difficulty(state: Dict[str, Any], subject: str) -> str:
    configured = state["config"].get("difficulty", "adaptive")
    if configured in DIFFICULTIES:
        return configured
    stats = ensure_subject(state, subject)
    return DIFFICULTIES[max(0, min(2, int(stats.get("level", 1))))]


def cmd_next(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)
    subjects = state["rotation"]["subjects"]
    if not subjects:
        return fail(ctx, "no subjects in the rotation; add one with: add-subject <name>", code=4)

    pending = state.get("pending")
    if pending:
        payload = {
            "ok": False,
            "reason": "pending",
            "message": "A question is already pending. Answer it and record the result, or skip it.",
            "pending": pending,
        }
        human = (
            f"pending question already open: {subject_label(state, pending.get('subject'))} / "
            f"{(pending.get('focus') or {}).get('topic') or 'new material'}\n"
            "record it (record --result ...) or skip (record --result skipped) first."
        )
        if ctx.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(human)
        return 0

    index = int(state["rotation"]["index"]) % len(subjects)
    subject = subjects[index]
    stats = ensure_subject(state, subject)
    limit = int(state["config"].get("limit", 0) or 0)
    remaining = None if limit <= 0 else max(0, limit - int(state["session"].get("asked", 0)))
    if remaining == 0:
        payload = {
            "ok": False,
            "reason": "limit",
            "message": f"Session limit reached ({limit} questions). Start a new session or raise the limit.",
            "limit": limit,
            "session": state["session"],
        }
        if ctx.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"session limit reached: {limit} questions. run: session new  (or set --limit 0)")
        return 0
    focus = pick_focus(ctx.ws, state, subject)
    types = state["config"]["types"] or list(TYPES)
    suggested = types[stats["asked"] % len(types)]
    difficulty = target_difficulty(state, subject)
    recent = stats.get("recent") or []
    recent_acc = accuracy(
        sum(1 for item in recent if item == "correct"),
        sum(1 for item in recent if item == "partial"),
        sum(1 for item in recent if item == "wrong"),
    )

    pending = {
        "subject": subject,
        "asked_at": now_iso(),
        "focus": focus,
        "type": suggested,
        "difficulty": difficulty,
        "position": index + 1,
        "of": len(subjects),
        "cycle": state["rotation"]["cycle"],
    }
    state["pending"] = pending
    ensure_subject(state, subject)
    save_state(ctx.ws, state)

    payload = {
        "ok": True,
        "subject": subject,
        "subject_label": subject_label(state, subject),
        "position": index + 1,
        "of": len(subjects),
        "cycle": state["rotation"]["cycle"],
        "difficulty": difficulty,
        "suggested_type": suggested,
        "allowed_types": types,
        "focus": focus,
        "recent_accuracy": recent_acc,
        "limit": limit or None,
        "session_remaining": remaining,
        "weak_in_subject": [
            {"topic": item["topic"], "misses": item.get("misses", 0), "required_streak": item.get("required_streak", 1)}
            for item in active_weak(state, subject)
        ],
        "teach": state.get("teach", {}).get(subject),
        "pending": pending,
    }

    lines = [
        f"ask: {subject_label(state, subject)} ({index + 1}/{len(subjects)}, cycle {state['rotation']['cycle']})",
        f"difficulty: {difficulty}  type: {suggested}",
    ]
    if focus["kind"] == "weak":
        lines.append(f"focus: weak topic '{focus['topic']}' ({focus['misses']} miss) — retest it")
    elif focus["kind"] == "chunk":
        where = f"{focus['topic_title']} / {focus['chunk_title']} ({focus['chunk_index']}/{focus['chunk_total']})"
        suffix = " — no chunk file yet; ask from the outline" if focus.get("missing") else ""
        lines.append(f"focus: uncovered chunk {where}{suffix}")
    else:
        lines.append("focus: new material")
    if recent_acc is not None:
        lines.append(f"recent accuracy in subject: {pct(recent_acc)}")
    lines.append("now write exactly one question for this subject, then stop and wait.")
    return emit(ctx, payload, "\n".join(lines))


# --------------------------------------------------------------------------- #
# record
# --------------------------------------------------------------------------- #


def bump_weak(
    ws: Path,
    state: Dict[str, Any],
    subject: str,
    topic: str,
    flow: str,
    result: str,
    misconception: Optional[str],
    retest: Optional[str],
    unit: Optional[str] = None,
) -> Dict[str, Any]:
    stamp = now_iso()
    record = get_weak(state, subject, topic)
    if record is None:
        record = {
            "status": "weak",
            "misses": 0,
            "partials": 0,
            "hits": 0,
            "streak": 0,
            "regressions": 0,
            "first_seen": stamp,
            "last_seen": stamp,
            "last_result": result,
            "misconceptions": [],
            "retest": None,
            "mastered_at": None,
        }
    was_mastered = record.get("status") == "mastered"

    if result in ("wrong", "partial"):
        if result == "wrong":
            record["misses"] = int(record.get("misses", 0)) + 1
        else:
            record["partials"] = int(record.get("partials", 0)) + 1
        if was_mastered:
            record["regressions"] = int(record.get("regressions", 0)) + 1
            record["mastered_at"] = None
        record["streak"] = 0
        record["status"] = "weak"
    elif result == "correct":
        record["hits"] = int(record.get("hits", 0)) + 1
        if flow == "main" and record.get("status") != "mastered":
            record["streak"] = int(record.get("streak", 0)) + 1
            if record["streak"] >= required_streak(state, record):
                record["status"] = "mastered"
                record["mastered_at"] = stamp
            else:
                record["status"] = "improving"

    record["last_seen"] = stamp
    record["last_result"] = result
    record["required_streak"] = required_streak(state, record)
    if misconception:
        text = trim(misconception, 400)
        if text and text not in record["misconceptions"]:
            record["misconceptions"].append(text)
            record["misconceptions"] = record["misconceptions"][-8:]
    if retest:
        record["retest"] = trim(retest, 600)
    if unit:
        record["unit"] = trim(unit, 200)

    put_weak(state, subject, topic, record)
    render_weak(ws, subject, topic, record)
    return record


def cmd_record(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)
    if args.result not in RESULTS:
        return fail(ctx, f"result must be one of: {', '.join(RESULTS)}")

    pending = state.get("pending")
    if pending is None and not args.subject:
        return fail(ctx, "no question is pending; pass --subject to record an off-rotation attempt", code=5)

    subject = slugify(args.subject or pending["subject"])
    if pending and args.subject and slugify(args.subject) != slugify(pending["subject"]):
        return fail(
            ctx,
            f"pending subject is '{pending['subject']}', not '{args.subject}'; "
            "record it or skip it before switching",
            code=9,
        )
    focus = (pending or {}).get("focus") or {}
    topic = args.topic or focus.get("concept") or focus.get("topic")
    topic = slugify(topic) if topic else None
    if args.result in ("wrong", "partial") and not topic:
        return fail(ctx, "a wrong or partial answer needs --topic (the specific concept that failed)", code=6)

    on_rotation = pending is not None
    flow = "main"
    stats = ensure_subject(state, subject)
    stamp = now_iso()

    weak_record = None
    if topic:
        weak_record = bump_weak(
            ctx.ws,
            state,
            subject,
            topic,
            flow,
            args.result,
            args.misconception,
            args.retest,
        )

    if flow == "main":
        session = state["session"]
        session["asked"] = int(session.get("asked", 0)) + 1
        if args.result in ("correct", "partial", "wrong", "skipped"):
            session[args.result] = int(session.get(args.result, 0)) + 1
        stats["asked"] = int(stats.get("asked", 0)) + 1
        stats[args.result] = int(stats.get(args.result, 0)) + 1
        stats["last_seen"] = stamp
        recent = list(stats.get("recent") or [])
        if args.result != "skipped":
            recent.append(args.result)
            stats["recent"] = recent[-5:]

        if args.result == "correct":
            stats["correct_streak"] = int(stats.get("correct_streak", 0)) + 1
        else:
            stats["correct_streak"] = 0

        configured = state["config"].get("difficulty", "adaptive")
        if configured == "adaptive":
            recent_rows = stats.get("recent") or []
            recent_acc = accuracy(
                sum(1 for item in recent_rows if item == "correct"),
                sum(1 for item in recent_rows if item == "partial"),
                sum(1 for item in recent_rows if item == "wrong"),
            )
            level = int(stats.get("level", 1))
            if (
                len(recent_rows) >= 3
                and args.result == "correct"
                and int(stats.get("correct_streak", 0)) >= 2
                and recent_acc is not None
                and recent_acc >= 0.85
                and level < 2
            ):
                stats["level"] = level + 1
                stats["correct_streak"] = 0
            elif (
                len(recent_rows) >= 3
                and args.result in ("wrong", "partial")
                and recent_acc is not None
                and recent_acc <= 0.4
                and level > 0
            ):
                stats["level"] = level - 1

        rotation = state["rotation"]
        subjects = rotation["subjects"]
        if on_rotation and subjects:
            rotation["index"] = (int(rotation["index"]) + 1) % len(subjects)
            if rotation["index"] == 0:
                rotation["cycle"] = int(rotation.get("cycle", 1)) + 1
            state["pending"] = None
        elif on_rotation:
            state["pending"] = None

    append_history(
        ctx.ws,
        {
            "ts": stamp,
            "session": state["session"]["id"],
            "flow": flow,
            "subject": subject,
            "topic": topic,
            "type": args.type or (pending or {}).get("type"),
            "difficulty": (pending or {}).get("difficulty") or target_difficulty(state, subject),
            "result": args.result,
            "retest": bool((pending or {}).get("focus", {}).get("retest")) or bool(args.retest),
            "question": trim(args.question),
            "answer": trim(args.answer),
            "expected": trim(args.expected),
            "misconception": trim(args.misconception),
            "concept": trim(args.concept),
        },
    )
    save_state(ctx.ws, state)

    active = active_weak(state, subject)
    payload = {
        "ok": True,
        "flow": flow,
        "subject": subject,
        "subject_label": subject_label(state, subject),
        "topic": topic,
        "result": args.result,
        "weak": None
        if weak_record is None
        else {
            "topic": topic,
            "status": weak_record.get("status"),
            "misses": weak_record.get("misses"),
            "streak": weak_record.get("streak"),
            "required_streak": weak_record.get("required_streak"),
            "cleared": weak_record.get("status") == "mastered",
        },
        "subject_stats": {key: stats.get(key) for key in ("asked", "correct", "partial", "wrong", "skipped", "level")},
        "session": state["session"],
        "next_subject": state["rotation"]["subjects"][int(state["rotation"]["index"]) % len(state["rotation"]["subjects"])]
        if state["rotation"]["subjects"]
        else None,
        "next_subject_label": subject_label(
            state,
            state["rotation"]["subjects"][int(state["rotation"]["index"]) % len(state["rotation"]["subjects"])],
        )
        if state["rotation"]["subjects"]
        else None,
        "weak_remaining_in_subject": [item["topic"] for item in active],
    }

    lines = [f"recorded: {args.result} — {subject_label(state, subject)} / {topic or 'general'}"]
    acc = accuracy(
        stats.get("correct", 0), stats.get("partial", 0), stats.get("wrong", 0)
    )
    lines.append(
        f"subject: {stats.get('asked', 0)} asked, {stats.get('correct', 0)} correct, "
        f"{stats.get('partial', 0)} partial, {stats.get('wrong', 0)} wrong ({pct(acc)})"
    )
    if weak_record:
        if weak_record.get("status") == "mastered":
            lines.append(f"weak: cleared '{topic}' after {weak_record.get('hits')} correct main-flow answer(s)")
        else:
            lines.append(
                f"weak: '{topic}' {weak_record.get('misses')} miss, "
                f"needs {weak_record.get('required_streak')} clean main-flow answer(s) in a row"
            )
    elif args.result in ("wrong", "partial"):
        lines.append("weak: not recorded (no topic)")
    if payload["next_subject"]:
        lines.append(f"next subject: {subject_label(state, payload['next_subject'])}")
    if flow == "main":
        lines.append("now call next for the following question.")
    return emit(ctx, payload, "\n".join(lines))


# --------------------------------------------------------------------------- #
# weak
# --------------------------------------------------------------------------- #


def cmd_weak(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    rows = []
    for subject in sorted(state.get("weak", {})):
        for topic, record in sorted(state["weak"][subject].items()):
            if record.get("status") == "mastered" and not args.all:
                continue
            rows.append(
                {
                    "subject": subject,
                    "subject_label": subject_label(state, subject),
                    "topic": topic,
                    "status": record.get("status"),
                    "misses": record.get("misses", 0),
                    "partials": record.get("partials", 0),
                    "streak": record.get("streak", 0),
                    "required_streak": record.get("required_streak", 1),
                    "last_seen": record.get("last_seen"),
                    "misconceptions": record.get("misconceptions", []),
                    "file": str(
                        (mastered_file(ctx.ws, subject, topic) if record.get("status") == "mastered" else weak_file(ctx.ws, subject, topic))
                    ),
                }
            )
    rows.sort(key=lambda row: (row["status"] == "mastered", -int(row["misses"])))
    payload = {"ok": True, "count": len(rows), "topics": rows}
    if not rows:
        return emit(ctx, payload, "no weak topics" + ("" if args.all else " — nothing to retest"))
    lines = []
    for row in rows:
        mark = "mastered" if row["status"] == "mastered" else f"{row['misses']} miss"
        lines.append(f"{row['subject_label']} / {row['topic']}: {mark}, needs {row['required_streak']} clean")
        for item in row["misconceptions"][-2:]:
            lines.append(f"  - {item}")
    return emit(ctx, payload, "\n".join(lines))


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #


def cmd_report(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    history = read_history(ctx.ws)
    main = [row for row in history if row.get("flow") == "main"]
    teach_rows = [row for row in history if row.get("flow") != "main"]

    def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        counts = {key: sum(1 for row in rows if row.get("result") == key) for key in RESULTS}
        total = sum(counts[key] for key in ("correct", "partial", "wrong"))
        return {
            "attempts": len(rows),
            "correct": counts["correct"],
            "partial": counts["partial"],
            "wrong": counts["wrong"],
            "skipped": counts["skipped"],
            "accuracy_strict": (counts["correct"] / total) if total else None,
            "accuracy_weighted": accuracy(counts["correct"], counts["partial"], counts["wrong"]),
        }

    by_subject: Dict[str, Any] = {}
    for row in main:
        key = slugify(row.get("subject") or "general")
        bucket = by_subject.setdefault(
            key, {"attempts": 0, "correct": 0, "partial": 0, "wrong": 0, "skipped": 0}
        )
        bucket["attempts"] += 1
        result = row.get("result")
        if result in bucket:
            bucket[result] += 1

    for bucket in by_subject.values():
        bucket["accuracy_weighted"] = accuracy(bucket["correct"], bucket["partial"], bucket["wrong"])

    mastered = []
    for subject, topics in state.get("weak", {}).items():
        for topic, record in topics.items():
            if record.get("status") == "mastered":
                mastered.append(
                    {"subject": subject, "topic": topic, "mastered_at": record.get("mastered_at")}
                )

    payload = {
        "ok": True,
        "overall": summarize(main),
        "session": summarize(
            [
                row
                for row in main
                if row.get("session") == state["session"]["id"]
            ]
        ),
        "by_subject": by_subject,
        "labels": {sub: subject_label(state, sub) for sub in state["rotation"]["subjects"]},
        "teach_checks": len(teach_rows),
        "weak": [
            {"subject": subject, "topic": topic, "misses": item.get("misses", 0)}
            for subject in state.get("weak", {})
            for topic, item in sorted(
                state["weak"][subject].items(),
                key=lambda pair: -int(pair[1].get("misses", 0)),
            )
            if item.get("status") != "mastered"
        ][:10],
        "mastered": mastered,
        "rotation": state["rotation"],
    }

    overall = payload["overall"]
    lines = [
        f"overall: {overall['attempts']} attempts, {overall['correct']} correct, "
        f"{overall['partial']} partial, {overall['wrong']} wrong, {overall['skipped']} skipped",
        f"accuracy: {pct(overall['accuracy_weighted'])} weighted, {pct(overall['accuracy_strict'])} strict",
    ]
    session = payload["session"]
    if session["attempts"]:
        lines.append(
            f"this session: {session['attempts']} attempts, {pct(session['accuracy_weighted'])} weighted"
        )
    if by_subject:
        lines.append("by subject:")
        for subject, bucket in sorted(by_subject.items()):
            lines.append(
                f"  {subject_label(state, subject)}: {bucket['attempts']} attempts, {pct(bucket['accuracy_weighted'])} weighted "
                f"({bucket['correct']}c/{bucket['partial']}p/{bucket['wrong']}w)"
            )
    if payload["weak"]:
        lines.append(
            "weakest: "
            + ", ".join(
                f"{subject_label(state, item['subject'])}/{item['topic']} ({item['misses']})"
                for item in payload["weak"][:5]
            )
        )
    if mastered:
        lines.append(
            "mastered: "
            + ", ".join(f"{subject_label(state, item['subject'])}/{item['topic']}" for item in mastered)
        )
    if teach_rows:
        lines.append(f"teach-flow checks: {len(teach_rows)}")
    return emit(ctx, payload, "\n".join(lines))


# --------------------------------------------------------------------------- #
# teach
# --------------------------------------------------------------------------- #


def plan_summary(plan: Dict[str, Any], completed: set) -> "tuple[Dict[str, int], List[Dict[str, Any]]]":
    counts = roadmap_counts(plan, completed)
    topics = []
    for topic in plan["topics"]:
        topics.append(
            {
                "index": topic["index"],
                "id": topic["id"],
                "title": topic["title"],
                "outcome": topic["outcome"],
                "path": topic["path"],
                "chunks": [
                    {
                        "index": chunk["index_in_topic"],
                        "id": chunk["id"],
                        "title": chunk["title"],
                        "key": chunk["key"],
                        "path": chunk["path"],
                        "exists": Path(chunk["path"]).is_file(),
                        "done": chunk["key"] in completed,
                    }
                    for chunk in topic["chunks"]
                ],
            }
        )
    return counts, topics


def teach_blocked(
    ctx: Ctx,
    subject: str,
    label: str,
    plan: Optional[Dict[str, Any]],
    errors: List[str],
) -> int:
    path = roadmap_json_path(ctx.ws, subject)
    missing = plan is None and all("is missing" in item for item in errors)
    if missing:
        payload = {
            "ok": False,
            "reason": "no_plan",
            "subject": subject,
            "subject_label": label,
            "plan": str(path),
            "message": (
                "No course roadmap yet. Author topics/<subject>/ROADMAP.json with every "
                "topic and its chunk titles before teaching. A topic needs 2-8 chunks."
            ),
        }
        human = (
            f"no roadmap for {label}: {path} is missing\n"
            "author ROADMAP.json first: at least 2 topics, each with 2-8 chunk titles.\n"
            "then run: teach plan --subject " + subject
        )
    else:
        payload = {
            "ok": False,
            "reason": "invalid_plan",
            "subject": subject,
            "subject_label": label,
            "plan": str(path),
            "errors": errors,
            "message": "Fix ROADMAP.json, then run teach plan again.",
        }
        human = "roadmap invalid for " + label + ":\n" + "\n".join(f"- {item}" for item in errors)
        human += "\nfix " + str(path) + ", then run: teach plan --subject " + subject
    return emit(ctx, payload, human)


def cmd_teach(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)

    subject = slugify(args.subject)
    label = subject_label(state, subject)
    progress = teach_progress(state, subject)
    plan, errors = load_roadmap(ctx.ws, subject)

    if args.action == "plan":
        if plan is None or errors:
            return teach_blocked(ctx, subject, label, plan, errors)
        render_roadmap_md(ctx.ws, state, subject, plan)
        completed = set(progress["completed"])
        counts, topics = plan_summary(plan, completed)
        upcoming = next_plan_chunk(plan, completed)
        payload = {
            "ok": True,
            "subject": subject,
            "subject_label": label,
            "title": plan["title"] or label,
            "outcome": plan["outcome"],
            "plan": plan["path"],
            "markdown": plan["markdown"],
            "counts": counts,
            "topics": topics,
            "next": None
            if upcoming is None
            else {
                "topic": upcoming["topic_id"],
                "topic_title": upcoming["topic_title"],
                "chunk": upcoming["key"],
                "chunk_title": upcoming["title"],
                "path": upcoming["path"],
                "exists": Path(upcoming["path"]).is_file(),
            },
            "valid": True,
        }
        lines = [
            f"roadmap: {payload['title']} — {counts['topics_total']} topics, "
            f"{counts['chunks_total']} chunks ({counts['chunks_done']} done)"
        ]
        if plan["outcome"]:
            lines.append(f"outcome: {plan['outcome']}")
        lines.append(f"plan: {plan['path']}")
        lines.append(f"rendered: {plan['markdown']}")
        for topic in topics:
            lines.append(f"{topic['index']}. {topic['title']} ({len(topic['chunks'])} chunks)")
            for chunk in topic["chunks"]:
                box = "x" if chunk["done"] else " "
                lines.append(f"   [{box}] {chunk['index']}. {chunk['title']}")
        if upcoming is not None:
            exists = Path(upcoming["path"]).is_file()
            lines.append("")
            lines.append(
                f"next: topic {upcoming['topic_index']}/{len(plan['topics'])} "
                f"{upcoming['topic_title']} — chunk {upcoming['index_in_topic']}/{upcoming['chunk_total']} "
                f"{upcoming['title']}"
            )
            lines.append(f"chunk file: {upcoming['path']}" + ("" if exists else " (missing — author it first)"))
        return emit(ctx, payload, "\n".join(lines))

    if plan is None or errors:
        return teach_blocked(ctx, subject, label, plan, errors)

    completed = set(progress["completed"])
    counts = roadmap_counts(plan, completed)

    if args.action == "next":
        topic_filter = None
        if getattr(args, "topic", None):
            topic_filter = match_topic(plan, args.topic)
            if topic_filter is None:
                return fail(
                    ctx,
                    f"no topic '{args.topic}' in the roadmap; run teach plan to see the topics",
                    code=11,
                    topics=[topic["title"] for topic in plan["topics"]],
                )
        chunk = next_plan_chunk(plan, completed, topic_filter)
        if chunk is None:
            render_roadmap_md(ctx.ws, state, subject, plan)
            scoped = f"topic '{topic_filter['title']}'" if topic_filter else "the course"
            payload = {
                "ok": True,
                "done": True,
                "subject": subject,
                "subject_label": label,
                "scope": topic_filter["id"] if topic_filter else "course",
                "counts": counts,
                "message": f"All chunks in {scoped} are complete. Move to the main flow to prove retention.",
            }
            return emit(
                ctx,
                payload,
                f"teach: {label} — {scoped} complete "
                f"({counts['chunks_done']}/{counts['chunks_total']} chunks, "
                f"{counts['topics_done']}/{counts['topics_total']} topics) — prove it in the main flow",
            )

        path = Path(chunk["path"])
        if not path.is_file():
            payload = {
                "ok": False,
                "reason": "chunk_missing",
                "subject": subject,
                "subject_label": label,
                "topic": chunk["topic_id"],
                "topic_title": chunk["topic_title"],
                "topic_index": chunk["topic_index"],
                "topic_total": len(plan["topics"]),
                "chunk": chunk["key"],
                "chunk_title": chunk["title"],
                "chunk_index": chunk["index_in_topic"],
                "chunk_total": chunk["chunk_total"],
                "path": chunk["path"],
                "message": (
                    "Author this one chunk at the given path, then run teach next again. "
                    "Do not skip it and do not write the whole topic in one file."
                ),
            }
            return emit(
                ctx,
                payload,
                f"chunk not written yet: {chunk['path']}\n"
                f"author exactly this chunk ({chunk['topic_title']} / {chunk['title']}), then rerun teach next",
            )

        progress["current"] = chunk["key"]
        save_state(ctx.ws, state)
        render_roadmap_md(ctx.ws, state, subject, plan)
        payload = {
            "ok": True,
            "done": False,
            "subject": subject,
            "subject_label": label,
            "topic": chunk["topic_id"],
            "topic_title": chunk["topic_title"],
            "topic_index": chunk["topic_index"],
            "topic_total": len(plan["topics"]),
            "chunk": chunk["key"],
            "chunk_title": chunk["title"],
            "chunk_index": chunk["index_in_topic"],
            "chunk_total": chunk["chunk_total"],
            "index": chunk["index"],
            "total": len(plan["chunks"]),
            "path": chunk["path"],
            "counts": counts,
            "completed": progress["completed"],
            "remaining": len(plan["chunks"]) - counts["chunks_done"],
        }
        return emit(
            ctx,
            payload,
            f"teach: {label} — topic {chunk['topic_index']}/{len(plan['topics'])} "
            f"{chunk['topic_title']}, chunk {chunk['index_in_topic']}/{chunk['chunk_total']} {chunk['title']}\n"
            f"course progress: {counts['chunks_done']}/{counts['chunks_total']} chunks, "
            f"{counts['topics_done']}/{counts['topics_total']} topics\n"
            f"read: {chunk['path']}",
        )

    # action == "record"
    if args.result not in RESULTS:
        return fail(ctx, f"result must be one of: {', '.join(RESULTS)}")

    candidate = args.chunk or progress.get("current")
    chunk = resolve_chunk(plan, candidate) if candidate else None
    if chunk is None:
        if args.chunk:
            return fail(
                ctx,
                f"no chunk '{args.chunk}' in this roadmap; run teach next to see the current chunk",
                code=7,
            )
        return fail(ctx, "no chunk in progress; run teach next first", code=7)

    topic = slugify(args.topic) if args.topic else chunk["id"]
    progress["checks"] = int(progress.get("checks", 0)) + 1
    attempts = progress["attempts"].setdefault(chunk["key"], {"correct": 0, "partial": 0, "wrong": 0})
    attempts[args.result] = int(attempts.get(args.result, 0)) + 1

    weak_record = None
    if args.result in ("wrong", "partial"):
        weak_record = bump_weak(
            ctx.ws,
            state,
            subject,
            topic,
            "teach",
            args.result,
            args.misconception,
            args.retest,
            unit=chunk["topic_title"],
        )
    elif args.result == "correct" and args.complete:
        if chunk["key"] not in progress["completed"]:
            progress["completed"].append(chunk["key"])
        if progress.get("current") == chunk["key"]:
            progress["current"] = None

    append_history(
        ctx.ws,
        {
            "ts": now_iso(),
            "session": state["session"]["id"],
            "flow": "teach",
            "subject": subject,
            "subject_label": label,
            "unit": chunk["topic_id"],
            "unit_title": chunk["topic_title"],
            "topic": topic,
            "chunk": chunk["key"],
            "chunk_title": chunk["title"],
            "type": args.type or "check",
            "result": args.result,
            "question": trim(args.question),
            "answer": trim(args.answer),
            "expected": trim(args.expected),
            "misconception": trim(args.misconception),
            "concept": trim(args.concept),
        },
    )

    completed = set(progress["completed"])
    topic_done = all(item["key"] in completed for item in plan["topics"][chunk["topic_index"] - 1]["chunks"])
    counts = roadmap_counts(plan, completed)
    upcoming = next_plan_chunk(plan, completed)
    save_state(ctx.ws, state)
    render_roadmap_md(ctx.ws, state, subject, plan)
    journey_config = state.get("journey", {}).get(subject)
    journey_day = None
    if journey_config:
        render_journey_md(ctx.ws, state, subject, plan, journey_config)
        exams = journey_config.get("exams") or {}
        wrapped_ids = set(journey_config.get("wrapped") or [])
        for session in build_journey_sessions(plan, journey_config):
            if session["kind"] != "teach" or chunk["key"] not in session["chunks"]:
                continue
            if journey_session_done(session, completed, exams):
                is_wrapped = session["id"] in wrapped_ids
                journey_day = {
                    "id": session["id"],
                    "date": session["date"],
                    "wrapped": is_wrapped,
                    "action": None
                    if is_wrapped
                    else f"journey wrap --subject {subject}",
                }
            break

    payload = {
        "ok": True,
        "subject": subject,
        "subject_label": label,
        "unit": chunk["topic_id"],
        "unit_title": chunk["topic_title"],
        "topic": topic,
        "chunk": chunk["key"],
        "chunk_title": chunk["title"],
        "result": args.result,
        "chunk_complete": chunk["key"] in completed,
        "topic_complete": topic_done,
        "counts": counts,
        "completed": progress["completed"],
        "next": None
        if upcoming is None
        else {
            "topic": upcoming["topic_id"],
            "topic_title": upcoming["topic_title"],
            "chunk": upcoming["key"],
            "chunk_title": upcoming["title"],
            "index": upcoming["index"],
        },
        "weak": None
        if weak_record is None
        else {"topic": topic, "status": weak_record.get("status"), "misses": weak_record.get("misses")},
    }
    if journey_day:
        payload["journey_day"] = journey_day

    where = f"{label} / {chunk['topic_title']} / {chunk['title']}"
    if weak_record:
        lines = [f"teach check failed: {where} ({weak_record.get('misses')} miss) — saved to weak/"]
        lines.append("teach this idea again differently, then re-check. No chunk advance.")
    elif chunk["key"] in completed:
        lines = [f"teach check passed: {where} — chunk complete"]
        if topic_done:
            lines.append(f"topic complete: {chunk['topic_title']} "
                         f"({counts['topics_done']}/{counts['topics_total']} topics)")
        lines.append(f"course progress: {counts['chunks_done']}/{counts['chunks_total']} chunks, "
                     f"{counts['topics_done']}/{counts['topics_total']} topics")
        if journey_day and journey_day.get("action"):
            lines.append("end of day: call journey wrap for assignments and the lab task")
        if upcoming is not None:
            lines.append(
                f"next: {upcoming['topic_title']} — chunk {upcoming['index_in_topic']}/{upcoming['chunk_total']} "
                f"{upcoming['title']}"
            )
    else:
        lines = [f"teach check passed: {where} — pass --complete when the chunk is mastered"]
    return emit(ctx, payload, "\n".join(lines))


# --------------------------------------------------------------------------- #
# journey
# --------------------------------------------------------------------------- #


def journey_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "start": config.get("start"),
        "chunks_per_day": int(config.get("chunks_per_day", 2) or 2),
        "exam_types": list(config.get("exam_types") or ["mcq"]),
        "exam_questions": int(config.get("exam_questions", 8) or 8),
        "exam_scope": config.get("exam_scope", "week"),
        "labs": config.get("labs", "auto"),
        "exams_done": len(config.get("exams") or {}),
    }


def next_open_after(
    sessions: List[Dict[str, Any]],
    target: Optional[Dict[str, Any]],
    completed: set,
    exams: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if target is None:
        return None
    start = sessions.index(target) + 1
    for session in sessions[start:]:
        if not journey_session_done(session, completed, exams):
            return session
    return None


def cmd_journey(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)

    chosen = getattr(args, "subject", None) or current_subject(state)
    if not chosen:
        return fail(ctx, "no subjects in the rotation; add one with: add-subject <name>", code=4)
    subject = slugify(chosen)
    label = subject_label(state, subject)
    plan, errors = load_roadmap(ctx.ws, subject)
    if plan is None or errors:
        return teach_blocked(ctx, subject, label, plan, errors)

    today = date.today()
    preview = getattr(args, "today", None)
    if preview:
        try:
            today = date.fromisoformat(str(preview))
        except ValueError:
            return fail(ctx, "--today must be YYYY-MM-DD", code=2)

    action = getattr(args, "action", None)
    journeys = state.setdefault("journey", {})
    config = journeys.get(subject)

    if action == "plan":
        try:
            start = parse_journey_start(getattr(args, "start", None), today)
        except ValueError as exc:
            return fail(ctx, str(exc), code=2)

        existing = config or {}
        per_day = getattr(args, "chunks_per_day", None)
        if per_day is None:
            per_day = existing.get("chunks_per_day", 2)
        if not 1 <= int(per_day) <= 6:
            return fail(ctx, "--chunks-per-day must be between 1 and 6", code=2)

        raw_types = getattr(args, "exam_types", None)
        if raw_types:
            exam_types = [item.strip() for item in str(raw_types).split(",") if item.strip()]
        else:
            exam_types = existing.get("exam_types") or [
                item for item in state["config"].get("types", []) if item in JOURNEY_TYPES
            ] or ["mcq", "exercise"]
        bad = [item for item in exam_types if item not in JOURNEY_TYPES]
        if bad or not exam_types:
            return fail(
                ctx,
                f"unknown exam type(s): {', '.join(bad) or '(none)'}; allowed: {', '.join(JOURNEY_TYPES)}",
                code=2,
            )

        questions = getattr(args, "exam_questions", None)
        if questions is None:
            questions = existing.get("exam_questions", 8)
        if not 1 <= int(questions) <= 30:
            return fail(ctx, "--exam-questions must be between 1 and 30", code=2)

        scope = getattr(args, "exam_scope", None) or existing.get("exam_scope", "week")
        if scope not in ("week", "course"):
            return fail(ctx, "--exam-scope must be week or course", code=2)

        labs_mode = getattr(args, "labs", None) or existing.get("labs", "auto")
        if labs_mode not in ("auto", "on", "off"):
            return fail(ctx, "--labs must be auto, on, or off", code=2)

        had_exams = bool(existing.get("exams"))
        config = {
            "start": start.isoformat(),
            "chunks_per_day": int(per_day),
            "exam_types": exam_types,
            "exam_questions": int(questions),
            "exam_scope": scope,
            "labs": labs_mode,
            "created_at": now_iso(),
            "exams": {},
            "wrapped": [],
        }
        journeys[subject] = config
        save_state(ctx.ws, state)
        sessions = build_journey_sessions(plan, config)
        completed = set(teach_progress(state, subject)["completed"])
        counts = journey_counts(sessions, completed, {})
        first = sessions[0] if sessions else None
        outline = render_journey_md(ctx.ws, state, subject, plan, config)
        lab_enabled = labs_mode == "on" or (
            labs_mode == "auto" and course_is_practical(plan, subject)
        )
        lab_kind = lab_kind_for(plan, subject) if lab_enabled else None
        payload = {
            "ok": True,
            "action": "plan",
            "subject": subject,
            "subject_label": label,
            "journey": journey_settings(config),
            "outline": outline,
            "labs": {"mode": labs_mode, "enabled": lab_enabled, "kind": lab_kind},
            "counts": counts,
            "exams_reset": had_exams,
            "first": session_payload(first, plan, completed, today) if first else None,
            "sessions": [
                {
                    "id": item["id"],
                    "kind": item["kind"],
                    "week": item["week"],
                    "date": item["date"],
                    "weekday": item["weekday"],
                    "chunks": len(item["chunks"]),
                    **({"day": item["day"]} if item["kind"] == "teach" else {"topics": item["topics"]}),
                }
                for item in sessions
            ],
        }
        lines = [
            f"journey planned: {label} — {count_label(counts['weeks'], 'week')}, "
            f"{count_label(counts['teaching_total'], 'teaching day')}, "
            f"{count_label(counts['exams_total'], 'exam')}",
            f"start: {config['start']} ({WEEKDAY_NAMES[start.weekday()]})  "
            f"pace: {config['chunks_per_day']} chunks/day",
            f"exam: {config['exam_questions']} questions, {', '.join(config['exam_types'])}, "
            f"{config['exam_scope']} scope",
            "labs: "
            + ("off (theory-only course)" if not lab_enabled else lab_kind),
            f"outline: {outline}",
        ]
        if had_exams:
            lines.append("exam history was reset by this plan")
        if first:
            lines.append(
                f"first: {first['weekday']} {first['date']} — "
                f"{len(first['chunks'])} chunks"
            )
            lines.append(f"open: journey --subject {subject}")
        return emit(ctx, payload, "\n".join(lines))

    if action == "wrap":
        if config is None:
            return fail(ctx, "no journey plan for this subject; run journey first", code=12)
        sessions = build_journey_sessions(plan, config)
        completed = set(teach_progress(state, subject)["completed"])
        exams = config.setdefault("exams", {})
        done_sessions = [
            session
            for session in sessions
            if session["kind"] == "teach" and journey_session_done(session, completed, exams)
        ]
        if not done_sessions:
            return fail(
                ctx,
                "no teaching day is complete yet; finish today's chunks before asking for assignments",
                code=12,
            )
        wrapped = config.setdefault("wrapped", [])
        unwrapped = [session for session in done_sessions if session["id"] not in wrapped]
        repeat = not unwrapped
        session = unwrapped[0] if unwrapped else done_sessions[-1]
        if not repeat:
            wrapped.append(session["id"])
            save_state(ctx.ws, state)
        assignments, lab = assignments_payload(session, plan, config, subject)
        outline = render_journey_md(ctx.ws, state, subject, plan, config)
        payload = {
            "ok": True,
            "action": "wrap",
            "subject": subject,
            "subject_label": label,
            "repeat": repeat,
            "session": session_payload(session, plan, completed, today),
            "assignments": assignments,
            "lab": lab,
            "outline": outline,
        }
        lines = [
            f"end of day: {label} — week {session['week']} · lesson {session['day']} "
            f"({session['weekday']} {session['date']})"
        ]
        if repeat:
            lines.append("assignments were already shown for this day; here they are again")
        lines.append(f"assignments ({assignments['count']}):")
        for index, item in enumerate(assignments["items"], 1):
            lines.append(f"  {index}. [{item['kind']}] {item['brief']}")
        lines.append(f"  submit: {assignments['submit']}")
        if lab["required"]:
            lines.append(f"lab ({lab['kind']}): {lab['brief']}")
            lines.append(f"  submit: {lab['submit']}")
        else:
            lines.append(f"lab: none — {lab['reason']}")
        lines.append(f"outline: {outline}")
        return emit(ctx, payload, "\n".join(lines))

    if action == "exam-done":
        if config is None:
            return fail(ctx, "no journey plan for this subject; run journey plan first", code=12)
        sessions = build_journey_sessions(plan, config)
        completed = set(teach_progress(state, subject)["completed"])
        exams = config.setdefault("exams", {})
        target = first_open_session(sessions, completed, exams)
        if target is None:
            return fail(ctx, "the journey is already complete; nothing to record", code=12)
        if target["kind"] != "exam":
            return fail(
                ctx,
                f"the next journey session is teaching, not an exam: {target['date']} "
                f"({len(target['chunks'])} chunks)",
                code=12,
            )
        exams[str(target["week"])] = {
            "completed_at": now_iso(),
            "date": today.isoformat(),
            "score": trim(getattr(args, "score", None), 200),
            "notes": trim(getattr(args, "notes", None), 2000),
        }
        save_state(ctx.ws, state)
        counts = journey_counts(sessions, completed, exams)
        upcoming = next_open_after(sessions, target, completed, exams)
        outline = render_journey_md(ctx.ws, state, subject, plan, config)
        payload = {
            "ok": True,
            "action": "exam-done",
            "outline": outline,
            "subject": subject,
            "subject_label": label,
            "exam": {
                "week": target["week"],
                "date": target["date"],
                "score": exams[str(target["week"])]["score"],
                "types": target["types"],
                "question_count": target["question_count"],
            },
            "counts": counts,
            "next": session_payload(upcoming, plan, completed, today) if upcoming else None,
        }
        lines = [
            f"exam recorded: {label} week {target['week']} — "
            f"{exams[str(target['week'])]['score'] or 'no score given'}"
        ]
        lines.append(
            f"journey: {counts['teaching_done']}/{counts['teaching_total']} teaching days, "
            f"{counts['exams_done']}/{counts['exams_total']} exams"
        )
        if upcoming is None:
            lines.append("course complete — use weak/report to keep it warm")
        else:
            lines.append(
                f"next: {upcoming['weekday']} {upcoming['date']} — {upcoming['kind']}"
            )
        return emit(ctx, payload, "\n".join(lines))

    # default action: today's status
    created = False
    if config is None:
        config = default_journey_config(state, today)
        journeys[subject] = config
        save_state(ctx.ws, state)
        created = True

    sessions = build_journey_sessions(plan, config)
    completed = set(teach_progress(state, subject)["completed"])
    exams = config.setdefault("exams", {})
    counts = journey_counts(sessions, completed, exams)
    outline = render_journey_md(ctx.ws, state, subject, plan, config)
    target = first_open_session(sessions, completed, exams)
    pending = state.get("pending")

    if target is None:
        payload = {
            "ok": True,
            "action": "status",
            "status": "complete",
            "subject": subject,
            "subject_label": label,
            "today": today.isoformat(),
            "weekday": WEEKDAY_NAMES[today.weekday()],
            "journey": journey_settings(config),
            "counts": counts,
            "outline": outline,
            "session": None,
            "next": None,
        }
        return emit(
            ctx,
            payload,
            f"journey complete: {label} — every teaching day and exam is done\noutline: {outline}",
        )

    first_date = date.fromisoformat(sessions[0]["date"]) if sessions else today
    planned = date.fromisoformat(target["date"])
    overdue = planned < today
    weekend = today.weekday() >= 5

    if today < first_date:
        status = "before_start"
    elif target["kind"] == "teach" and weekend and not overdue:
        status = "rest"
    elif planned > today:
        status = "ahead"
    else:
        status = target["kind"]

    upcoming = next_open_after(sessions, target, completed, exams)
    payload = {
        "ok": True,
        "action": "status",
        "status": status,
        "subject": subject,
        "subject_label": label,
        "today": today.isoformat(),
        "weekday": WEEKDAY_NAMES[today.weekday()],
        "journey": journey_settings(config),
        "counts": counts,
        "outline": outline,
        "session": session_payload(target, plan, completed, today),
        "next": session_payload(upcoming, plan, completed, today) if upcoming else None,
        "created": created,
    }
    if pending is not None:
        payload["pending_open"] = True
        if status == "exam":
            payload["blocked_by_pending"] = True

    session = payload["session"]
    lines = [f"journey: {label} — week {session['week']} · {session['weekday']} {session['date']}"]
    if session["overdue"]:
        lines.append(f"late by {session['late_days']} day(s) — catch up from here")
    if status == "before_start":
        lines.append(f"the journey starts {session['weekday']} {session['date']}; come back then")
    elif status == "rest":
        lines.append("rest day — no lesson scheduled today")
        lines.append(f"next: {session['weekday']} {session['date']} — {session['kind']}")
    elif status == "ahead":
        lines.append("you are ahead of the calendar")
        lines.append(f"next: {session['weekday']} {session['date']} — {session['kind']}")
    elif status == "teach":
        lines.append(
            f"teach day {session.get('day', '?')}/4 · {session['chunk_count']} chunks · "
            f"{', '.join(session['topics'])}"
        )
        for index, chunk in enumerate(session["chunks"], 1):
            mark = "done" if chunk["done"] else ("missing" if not chunk["exists"] else "ready")
            lines.append(f"  {index}. {chunk['topic_title']} / {chunk['title']} [{mark}]")
        lines.append("teach these chunks with teach next, then stop; journey advances by itself")
    elif status == "exam":
        lines.append(
            f"exam day · week {session['week']} · {session['question_count']} questions · "
            f"{', '.join(session['types'])} · {session['scope']} scope"
        )
        lines.append(f"topics: {', '.join(session['topics'])}")
        lines.append(
            f"ask one question at a time, record each with record --subject {subject} "
            f"--topic <concept>, then journey exam-done --score <n>/<m>"
        )
    lines.append(
        f"progress: {counts['teaching_done']}/{counts['teaching_total']} teaching days, "
        f"{counts['exams_done']}/{counts['exams_total']} exams"
    )
    lines.append(f"outline: {outline}")
    if pending is not None:
        lines.append("note: a main-flow question is still pending; resolve it before an exam")
    return emit(ctx, payload, "\n".join(lines))


def cmd_topics(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)
    if args.subject:
        subjects = [slugify(args.subject)]
    else:
        subjects = list(state["rotation"]["subjects"])
    if not subjects:
        return fail(ctx, "no subjects in the rotation; add one with: add-subject <name>", code=4)

    rows = []
    for subject in subjects:
        plan, errors = load_roadmap(ctx.ws, subject)
        row: Dict[str, Any] = {
            "subject": subject,
            "subject_label": subject_label(state, subject),
            "ready": plan is not None and not errors,
            "errors": errors,
        }
        if state.get("journey", {}).get(subject):
            row["outline"] = str(journey_outline_path(ctx.ws, subject))
        if row["ready"]:
            completed = set(teach_progress(state, subject)["completed"])
            counts, topics = plan_summary(plan, completed)
            row["counts"] = counts
            row["topics"] = topics
            row["plan"] = plan["path"]
            row["markdown"] = plan["markdown"]
        rows.append(row)

    payload = {
        "ok": True,
        "current": current_subject(state),
        "subjects": rows,
        "show_chunks": bool(args.chunks),
    }
    lines = []
    for row in rows:
        if not row["ready"]:
            lines.append(f"{row['subject_label']}: no roadmap yet")
            if row["errors"]:
                lines.extend(f"  - {item}" for item in row["errors"])
            continue
        counts = row["counts"]
        lines.append(
            f"{row['subject_label']} — {counts['chunks_done']}/{counts['chunks_total']} chunks · "
            f"{counts['topics_done']}/{counts['topics_total']} topics"
        )
        for topic in row["topics"]:
            done = sum(1 for chunk in topic["chunks"] if chunk["done"])
            lines.append(f"  {topic['index']}. {topic['title']} ({done}/{len(topic['chunks'])})")
            if args.chunks:
                for chunk in topic["chunks"]:
                    mark = "x" if chunk["done"] else " "
                    lines.append(f"     [{mark}] {chunk['index']}. {chunk['title']}")
        lines.append(f"  roadmap: {row['markdown']}")
        if row.get("outline"):
            lines.append(f"  journey: {row['outline']}")
    return emit(ctx, payload, "\n".join(lines))


def cmd_quick_teach(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)
    topic = str(args.topic).strip()
    if not topic:
        return fail(ctx, "quick-teach needs a topic name", code=2)

    subjects = list(state["rotation"]["subjects"])
    preferred = slugify(args.subject) if args.subject else current_subject(state)
    ordered = ([preferred] if preferred else []) + [s for s in subjects if s != preferred]

    matches = []
    for subject in ordered:
        plan, errors = load_roadmap(ctx.ws, subject)
        if plan is None or errors:
            continue
        if match_topic(plan, topic):
            matches.append(subject)

    if not matches:
        return fail(
            ctx,
            f"no topic '{topic}' in any course roadmap; run list-topics to see what exists",
            code=11,
        )
    if args.subject:
        subject = slugify(args.subject)
        plan, errors = load_roadmap(ctx.ws, subject)
        if plan is None or errors:
            return teach_blocked(ctx, subject, subject_label(state, subject), plan, errors)
        if not match_topic(plan, topic):
            return fail(
                ctx,
                f"no topic '{topic}' in {subject_label(state, subject)}; run list-topics --subject {subject}",
                code=11,
            )
    elif preferred in matches:
        subject = preferred
    elif len(matches) == 1:
        subject = matches[0]
    else:
        return fail(
            ctx,
            f"topic '{topic}' exists in several courses; pass --subject",
            code=11,
            subjects=[subject_label(state, item) for item in matches],
        )

    forwarded = argparse.Namespace(action="next", subject=subject, topic=topic)
    return cmd_teach(forwarded, ctx)


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #


def cmd_history(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    rows = read_history(ctx.ws)
    if args.subject:
        wanted = slugify(args.subject)
        rows = [row for row in rows if slugify(row.get("subject") or "") == wanted]
    if args.flow:
        rows = [row for row in rows if row.get("flow") == args.flow]
    limit = max(1, int(args.limit))
    recent = rows[-limit:][::-1]
    payload = {"ok": True, "count": len(recent), "total": len(rows), "attempts": recent}
    if not recent:
        return emit(ctx, payload, "no attempts recorded yet")
    lines = []
    for row in recent:
        stamp = str(row.get("ts") or "")[:16].replace("T", " ")
        lines.append(
            f"{stamp}  {row.get('flow', 'main')[:5]:<5}  {subject_label(state, slugify(row.get('subject') or ''))}/{row.get('topic') or '-'}  "
            f"{row.get('result')}"
        )
        if row.get("misconception"):
            lines.append(f"          ↳ {row['misconception']}")
    return emit(ctx, payload, "\n".join(lines))


# --------------------------------------------------------------------------- #
# config / session / reset
# --------------------------------------------------------------------------- #


def cmd_set(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)
    changed: Dict[str, Any] = {}

    if args.difficulty:
        if args.difficulty not in DIFFICULTIES and args.difficulty != "adaptive":
            return fail(ctx, f"difficulty must be one of: adaptive, {', '.join(DIFFICULTIES)}")
        state["config"]["difficulty"] = args.difficulty
        changed["difficulty"] = args.difficulty
    if args.limit is not None:
        if args.limit < 0:
            return fail(ctx, "limit must be 0 (continuous) or a positive number")
        state["config"]["limit"] = args.limit
        changed["limit"] = args.limit
    if args.types:
        types = [part.strip() for part in args.types.split(",") if part.strip()]
        bad = [item for item in types if item not in TYPES]
        if bad:
            return fail(ctx, f"unknown type(s): {', '.join(bad)}")
        state["config"]["types"] = types
        changed["types"] = types
    if args.mastery_streak is not None:
        if args.mastery_streak < 1:
            return fail(ctx, "mastery-streak must be at least 1")
        state["config"]["mastery_streak"] = args.mastery_streak
        changed["mastery_streak"] = args.mastery_streak
    if args.continuous is not None:
        state["config"]["continuous"] = args.continuous.lower() in ("1", "true", "yes", "on")
        changed["continuous"] = state["config"]["continuous"]
    if args.subjects:
        subjects, _ = apply_subjects(state, args.subjects)
        if not subjects:
            return fail(ctx, "at least one subject is required")
        for slug in subjects:
            ensure_subject(state, slug)
            (ctx.ws / "topics" / slug).mkdir(parents=True, exist_ok=True)
        changed["subjects"] = subjects

    save_state(ctx.ws, state)
    payload = {"ok": True, "changed": changed, "config": state["config"], "rotation": state["rotation"]}
    lines = [f"updated: {', '.join(changed) or 'nothing'}"]
    lines.append(
        f"rotation: {' → '.join(subject_label(state, sub) for sub in state['rotation']['subjects']) or '(none)'}"
    )
    lines.append(f"difficulty: {state['config']['difficulty']}  types: {', '.join(state['config']['types'])}")
    return emit(ctx, payload, "\n".join(lines))


def cmd_add_subject(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)
    slug = slugify(args.name)
    created = not (ctx.ws / "topics" / slug).is_dir()
    (ctx.ws / "topics" / slug).mkdir(parents=True, exist_ok=True)
    ensure_subject(state, slug)
    state["rotation"].setdefault("labels", {})[slug] = args.title or args.name.strip() or slug
    if slug not in state["rotation"]["subjects"]:
        state["rotation"]["subjects"].append(slug)
    save_state(ctx.ws, state)
    payload = {
        "ok": True,
        "subject": slug,
        "subject_label": subject_label(state, slug),
        "title": args.title or slug,
        "topics_dir": str(ctx.ws / "topics" / slug),
        "rotation": state["rotation"]["subjects"],
        "created": created,
    }
    return emit(
        ctx,
        payload,
        f"added: {subject_label(state, slug)} (position {state['rotation']['subjects'].index(slug) + 1}/{len(state['rotation']['subjects'])})\n"
        f"topics: {ctx.ws / 'topics' / slug}",
    )


def cmd_session(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)
    if args.action != "new":
        return fail(ctx, "unknown session action")
    previous = state["session"]
    state.setdefault("sessions", [])
    state["sessions"] = (state["sessions"] + [previous])[-50:]
    stamp = now_iso()
    state["session"] = {
        "id": stamp,
        "started_at": stamp,
        "asked": 0,
        "correct": 0,
        "partial": 0,
        "wrong": 0,
        "skipped": 0,
    }
    state["pending"] = None
    save_state(ctx.ws, state)
    payload = {"ok": True, "session": state["session"], "previous": previous}
    return emit(
        ctx,
        payload,
        f"new session started: {stamp}\nhistory and weaknesses are kept; rotation continues at "
        f"{state['rotation']['subjects'][int(state['rotation']['index']) % max(1, len(state['rotation']['subjects']))] if state['rotation']['subjects'] else '(none)'}",
    )


def cmd_reset(args, ctx: Ctx) -> int:
    if not args.yes:
        return fail(ctx, "reset deletes progress; re-run with --yes to confirm", code=8)
    removed: List[str] = []
    for path in (state_path(ctx.ws), history_path(ctx.ws)):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    for folder in (weak_dir(ctx.ws),):
        if folder.is_dir():
            children = sorted(folder.rglob("*"), key=lambda path: len(path.parts), reverse=True)
            for child in children:
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    try:
                        child.rmdir()
                    except OSError:
                        pass
            removed.append(str(folder))
    payload = {
        "ok": True,
        "removed": removed,
        "kept": ["notes/", "rough/", "topics/"],
        "message": "Progress reset. Teaching material and your notes were kept.",
    }
    return emit(ctx, payload, "progress reset. kept: notes/, rough/, topics/")


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="practice-loop",
        description="Adaptive practice and teaching state for a practice-loop workspace.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the workspace folders and state")
    init.add_argument("--dir", help="target directory (default: current directory)")
    init.add_argument("--subjects", help="comma-separated subject slugs, e.g. sql,csharp-dsa,oop")
    init.add_argument("--difficulty", help="adaptive | beginner | intermediate | advanced")
    init.add_argument("--types", help="comma-separated: mcq,exercise,conceptual")
    init.add_argument("--limit", type=int, help="questions per session; 0 = continuous")
    init.set_defaults(func=cmd_init)

    status = sub.add_parser("status", help="show workspace, rotation, and session state")
    status.set_defaults(func=cmd_status)

    nxt = sub.add_parser("next", help="open the next question slot and return a brief")
    nxt.set_defaults(func=cmd_next)

    record = sub.add_parser("record", help="record the result of the pending question")
    record.add_argument("--result", required=True, choices=list(RESULTS))
    record.add_argument("--topic", help="specific concept (required for wrong/partial without a focus)")
    record.add_argument("--subject", help="record off-rotation against this subject")
    record.add_argument("--type", help="mcq | exercise | conceptual")
    record.add_argument("--question", help="the question as asked")
    record.add_argument("--answer", help="what the learner answered")
    record.add_argument("--expected", help="the correct answer or corrected solution")
    record.add_argument("--misconception", help="the exact misconception to remember")
    record.add_argument("--concept", help="free-text concept note")
    record.add_argument("--retest", help="what to retest next time")
    record.set_defaults(func=cmd_record)

    weak = sub.add_parser("weak", help="list weak topics")
    weak.add_argument("--all", action="store_true", help="include mastered topics")
    weak.set_defaults(func=cmd_weak)

    report = sub.add_parser("report", help="accuracy overall, per subject, and weakest topics")
    report.set_defaults(func=cmd_report)

    history = sub.add_parser("history", help="recent attempts, newest first")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--subject")
    history.add_argument("--flow", choices=["main", "teach"])
    history.set_defaults(func=cmd_history)

    teach = sub.add_parser("teach", help="teach-flow progress")
    teach_sub = teach.add_subparsers(dest="action", required=True)
    teach_plan = teach_sub.add_parser("plan", help="validate the course roadmap and render ROADMAP.md")
    teach_plan.add_argument("--subject", required=True)
    teach_plan.set_defaults(func=cmd_teach)
    teach_next = teach_sub.add_parser("next", help="next chunk to teach")
    teach_next.add_argument("--subject", required=True)
    teach_next.add_argument("--topic", help="teach one roadmap topic by name, slug, or number")
    teach_next.set_defaults(func=cmd_teach)
    teach_record = teach_sub.add_parser("record", help="record a teach-flow check")
    teach_record.add_argument("--subject", required=True)
    teach_record.add_argument("--result", required=True, choices=list(RESULTS))
    teach_record.add_argument("--chunk")
    teach_record.add_argument("--topic")
    teach_record.add_argument("--type")
    teach_record.add_argument("--question")
    teach_record.add_argument("--answer")
    teach_record.add_argument("--expected")
    teach_record.add_argument("--misconception")
    teach_record.add_argument("--concept")
    teach_record.add_argument("--retest")
    teach_record.add_argument("--complete", action="store_true", help="mark the chunk complete")
    teach_record.set_defaults(func=cmd_teach)

    journey = sub.add_parser("journey", help="weekly journey: Mon-Thu lessons, Friday exam")
    journey.add_argument("--subject")
    journey.add_argument("--today", help="preview a date as YYYY-MM-DD")
    journey_sub = journey.add_subparsers(dest="action")
    journey_plan = journey_sub.add_parser("plan", help="divide the roadmap into weeks and days")
    journey_plan.add_argument("--subject")
    journey_plan.add_argument("--start", help="today, next-monday, or YYYY-MM-DD")
    journey_plan.add_argument("--chunks-per-day", type=int)
    journey_plan.add_argument("--exam-types", help="mcq,exercise,conceptual")
    journey_plan.add_argument("--exam-questions", type=int)
    journey_plan.add_argument("--exam-scope", choices=["week", "course"])
    journey_plan.add_argument("--labs", choices=["auto", "on", "off"])
    journey_plan.set_defaults(func=cmd_journey)
    journey_wrap = journey_sub.add_parser("wrap", help="end-of-day assignments and lab")
    journey_wrap.add_argument("--subject")
    journey_wrap.add_argument("--today")
    journey_wrap.set_defaults(func=cmd_journey)
    journey_exam = journey_sub.add_parser("exam-done", help="record the current Friday exam")
    journey_exam.add_argument("--subject")
    journey_exam.add_argument("--score")
    journey_exam.add_argument("--notes")
    journey_exam.set_defaults(func=cmd_journey)
    journey.set_defaults(func=cmd_journey)

    topics = sub.add_parser("topics", aliases=["list-topics"], help="list course roadmaps and topics")
    topics.add_argument("--subject")
    topics.add_argument("--chunks", action="store_true", help="show every chunk")
    topics.set_defaults(func=cmd_topics)

    quick = sub.add_parser("quick-teach", help="start teaching one topic directly")
    quick.add_argument("topic")
    quick.add_argument("--subject")
    quick.set_defaults(func=cmd_quick_teach)

    set_cmd = sub.add_parser("set", help="change difficulty, types, mastery streak, or subjects")
    set_cmd.add_argument("--difficulty")
    set_cmd.add_argument("--types")
    set_cmd.add_argument("--mastery-streak", type=int)
    set_cmd.add_argument("--continuous")
    set_cmd.add_argument("--limit", type=int)
    set_cmd.add_argument("--subjects")
    set_cmd.set_defaults(func=cmd_set)

    add = sub.add_parser("add-subject", help="add a subject to the rotation")
    add.add_argument("name")
    add.add_argument("--title")
    add.set_defaults(func=cmd_add_subject)

    session = sub.add_parser("session", help="session control")
    session.add_argument("action", choices=["new"])
    session.set_defaults(func=cmd_session)

    reset = sub.add_parser("reset", help="delete progress (keeps notes, rough, topics)")
    reset.add_argument("--yes", action="store_true")
    reset.set_defaults(func=cmd_reset)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [item for item in argv if item != "--json"]

    workspace_arg = None
    cleaned: List[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--workspace" and index + 1 < len(argv):
            workspace_arg = argv[index + 1]
            index += 2
            continue
        if item.startswith("--workspace="):
            workspace_arg = item.split("=", 1)[1]
            index += 1
            continue
        cleaned.append(item)
        index += 1

    parser = build_parser()
    args = parser.parse_args(cleaned)

    if args.command == "init":
        ctx = Ctx(Path(workspace_arg).expanduser().resolve() if workspace_arg else Path.cwd(), as_json)
        return args.func(args, ctx)

    ctx = Ctx(find_workspace(workspace_arg), as_json)
    return args.func(args, ctx)


if __name__ == "__main__":
    sys.exit(main())
