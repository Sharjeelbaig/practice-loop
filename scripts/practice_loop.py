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
from datetime import datetime, timezone
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

Each course is a roadmap of topics; each topic is several small chunks. One
topic is never one lesson.

Correct answers in the teach flow never clear a weakness. Only a correct answer
in the main flow does. Teaching proves you followed an explanation; the main
flow proves you can retrieve it cold.

## Commands

`start`, `teach`, `status`, `weak`, `report`, `hint`, `skip`, `easier`,
`harder`, `new session`, `reset`.

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
        "weak": {},
    }


def load_state(ws: Path) -> Dict[str, Any]:
    raw = read_json(state_path(ws))
    if not raw:
        return default_state()
    state = default_state()
    state.update(raw)
    for key in ("config", "rotation", "session", "teach", "weak", "subjects"):
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
    labels: Dict[str, str] = {}
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
        if upcoming is not None:
            lines.append(
                f"next: {upcoming['topic_title']} — chunk {upcoming['index_in_topic']}/{upcoming['chunk_total']} "
                f"{upcoming['title']}"
            )
    else:
        lines = [f"teach check passed: {where} — pass --complete when the chunk is mastered"]
    return emit(ctx, payload, "\n".join(lines))


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
