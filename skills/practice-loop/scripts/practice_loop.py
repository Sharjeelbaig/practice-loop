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

PRIMER = """# practice-loop workspace

This folder is a practice workspace. The agent reads it, quizzes you from it,
and remembers what you get wrong.

| Folder | Owner | Purpose |
| --- | --- | --- |
| `notes/` | you | Your own material. The agent reads it, never writes it. |
| `rough/` | you | Scratch space for solving exercises. The agent may add scaffolds here. |
| `topics/` | agent | Small teaching chunks, one folder per subject, one `.md` per chunk. |
| `weak/` | agent | Topics you got wrong. Taught and retested until you clear them. |
| `.practice-loop/` | agent | Machine state: rotation, pending question, history. Do not hand-edit. |

## Flows

- `start` — main flow. One question at a time, rotating subjects in a fixed
  order, mixing MCQs and exercises. Wrong answers create or strengthen a
  weakness.
- `teach` — teach flow. The agent writes `topics/<subject>/*.md` chunks, teaches
  one chunk, checks understanding, and only moves on when you answer correctly.

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
        "rotation": {"subjects": [], "index": 0, "cycle": 1},
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
    return state["subjects"][slug]


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
        subjects = [slugify(part) for part in str(args.subjects).split(",") if part.strip()]
    if subjects:
        state["rotation"]["subjects"] = subjects
        state["rotation"]["index"] = 0
        state["rotation"]["cycle"] = 1
        state["pending"] = None
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
        f"subjects: {', '.join(state['rotation']['subjects']) or '(none yet)'}\n"
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
    payload = {
        "ok": True,
        "workspace": str(ctx.ws),
        "subjects": subjects,
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
        "teach": {
            sub: {
                "completed": len(state.get("teach", {}).get(sub, {}).get("completed", [])),
                "current": state.get("teach", {}).get(sub, {}).get("current"),
            }
            for sub in subjects
        },
    }

    lines = [f"workspace: {ctx.ws}"]
    if subjects:
        current = subjects[rotation["index"] % len(subjects)]
        lines.append(f"rotation: {current} ({rotation['index'] + 1}/{len(subjects)}), cycle {rotation['cycle']}")
        lines.append("order: " + " → ".join(subjects))
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
            f"pending: {pending.get('subject')} / {(pending.get('focus') or {}).get('topic') or 'new material'} "
            f"— record or skip it before asking another"
        )
    if payload["teach"]:
        bits = [f"{sub} {info['completed']} done" for sub, info in payload["teach"].items() if info["completed"]]
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


def subject_chunks(ws: Path, subject: str) -> List[Path]:
    folder = ws / "topics" / slugify(subject)
    if not folder.is_dir():
        return []
    return sorted([p for p in folder.glob("*.md") if p.is_file()], key=lambda p: p.name.lower())


def pick_focus(ws: Path, state: Dict[str, Any], subject: str) -> Dict[str, Any]:
    stats = ensure_subject(state, subject)
    weak = active_weak(state, subject)
    if weak and (stats["asked"] % 2 == 1 or not subject_chunks(ws, subject)):
        first = weak[0]
        return {
            "kind": "weak",
            "topic": first["topic"],
            "misses": int(first.get("misses", 0)),
            "last_seen": first.get("last_seen"),
            "retest": True,
        }
    completed = set(state.get("teach", {}).get(slugify(subject), {}).get("completed", []))
    for path in subject_chunks(ws, subject):
        if path.name not in completed:
            return {"kind": "chunk", "topic": slugify(path.stem), "chunk": path.name, "title": chunk_title(path)}
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
            f"pending question already open: {pending.get('subject')} / "
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
        f"ask: {subject} ({index + 1}/{len(subjects)}, cycle {state['rotation']['cycle']})",
        f"difficulty: {difficulty}  type: {suggested}",
    ]
    if focus["kind"] == "weak":
        lines.append(f"focus: weak topic '{focus['topic']}' ({focus['misses']} miss) — retest it")
    elif focus["kind"] == "chunk":
        lines.append(f"focus: uncovered chunk {focus['chunk']} — {focus['title']}")
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
    topic = args.topic or focus.get("topic")
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
        "weak_remaining_in_subject": [item["topic"] for item in active],
    }

    lines = [f"recorded: {args.result} — {subject} / {topic or 'general'}"]
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
        lines.append(f"next subject: {payload['next_subject']}")
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
        lines.append(f"{row['subject']} / {row['topic']}: {mark}, needs {row['required_streak']} clean")
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
                f"  {subject}: {bucket['attempts']} attempts, {pct(bucket['accuracy_weighted'])} weighted "
                f"({bucket['correct']}c/{bucket['partial']}p/{bucket['wrong']}w)"
            )
    if payload["weak"]:
        lines.append("weakest: " + ", ".join(f"{item['subject']}/{item['topic']} ({item['misses']})" for item in payload["weak"][:5]))
    if mastered:
        lines.append("mastered: " + ", ".join(f"{item['subject']}/{item['topic']}" for item in mastered))
    if teach_rows:
        lines.append(f"teach-flow checks: {len(teach_rows)}")
    return emit(ctx, payload, "\n".join(lines))


# --------------------------------------------------------------------------- #
# teach
# --------------------------------------------------------------------------- #


def cmd_teach(args, ctx: Ctx) -> int:
    state = load_state(ctx.ws)
    if not state_path(ctx.ws).is_file():
        return fail(ctx, f"no practice-loop workspace at {ctx.ws}; run init first", code=3)
    subject = slugify(args.subject)
    chunks = subject_chunks(ctx.ws, subject)
    progress = state.setdefault("teach", {}).setdefault(
        subject, {"completed": [], "current": None, "checks": 0, "attempts": {}}
    )
    progress.setdefault("completed", [])
    progress.setdefault("attempts", {})

    if args.action == "next":
        remaining = [path for path in chunks if path.name not in progress["completed"]]
        if not chunks:
            payload = {
                "ok": False,
                "reason": "no_chunks",
                "subject": subject,
                "topics_dir": str(ctx.ws / "topics" / subject),
                "message": "No teaching chunks yet. Author topics/<subject>/*.md first.",
            }
            if ctx.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(f"no chunks in topics/{subject}/ — write 01-*.md, 02-*.md, … first")
            return 0
        if not remaining:
            payload = {
                "ok": True,
                "done": True,
                "subject": subject,
                "completed": progress["completed"],
                "message": "All chunks completed. Move to the main flow to prove retention.",
            }
            return emit(ctx, payload, f"teach: {subject} complete ({len(chunks)} chunks) — prove it in the main flow")
        current = remaining[0]
        progress["current"] = current.name
        save_state(ctx.ws, state)
        index = chunks.index(current) + 1
        payload = {
            "ok": True,
            "done": False,
            "subject": subject,
            "chunk": current.name,
            "path": str(current),
            "title": chunk_title(current),
            "index": index,
            "total": len(chunks),
            "completed": progress["completed"],
            "remaining": [path.name for path in remaining],
        }
        return emit(
            ctx,
            payload,
            f"teach: {subject} chunk {index}/{len(chunks)} — {current.name} ({chunk_title(current)})\n"
            f"read: {current}",
        )

    # action == "record"
    chunk = args.chunk or progress.get("current")
    if not chunk:
        return fail(ctx, "no chunk in progress; run teach next first", code=7)
    if args.result not in RESULTS:
        return fail(ctx, f"result must be one of: {', '.join(RESULTS)}")

    progress["checks"] = int(progress.get("checks", 0)) + 1
    attempts = progress["attempts"].setdefault(chunk, {"correct": 0, "partial": 0, "wrong": 0})
    attempts[args.result] = int(attempts.get(args.result, 0)) + 1

    topic = args.topic or slugify(Path(chunk).stem)
    topic = slugify(topic)
    weak_record = None
    if args.result in ("wrong", "partial"):
        weak_record = bump_weak(
            ctx.ws, state, subject, topic, "teach", args.result, args.misconception, args.retest
        )
    elif args.result == "correct" and args.complete:
        if chunk not in progress["completed"]:
            progress["completed"].append(chunk)
        progress["current"] = None

    append_history(
        ctx.ws,
        {
            "ts": now_iso(),
            "session": state["session"]["id"],
            "flow": "teach",
            "subject": subject,
            "topic": topic,
            "chunk": chunk,
            "type": args.type or "check",
            "result": args.result,
            "question": trim(args.question),
            "answer": trim(args.answer),
            "expected": trim(args.expected),
            "misconception": trim(args.misconception),
            "concept": trim(args.concept),
        },
    )
    save_state(ctx.ws, state)

    remaining = [path.name for path in chunks if path.name not in progress["completed"]]
    payload = {
        "ok": True,
        "subject": subject,
        "chunk": chunk,
        "result": args.result,
        "completed": progress["completed"],
        "remaining": remaining,
        "chunk_complete": chunk in progress["completed"],
        "weak": None
        if weak_record is None
        else {"topic": topic, "status": weak_record.get("status"), "misses": weak_record.get("misses")},
    }
    if weak_record:
        lines = [f"teach check failed: {subject} / {topic} ({weak_record.get('misses')} miss) — saved to weak/"]
        lines.append("teach this idea again differently, then re-check. No chunk advance.")
    elif chunk in progress["completed"]:
        lines = [f"teach check passed: {subject} / {chunk} — chunk complete"]
        lines.append(f"remaining: {len(remaining)}")
    else:
        lines = [f"teach check passed: {subject} / {chunk} — pass --complete when the chunk is mastered"]
    return emit(ctx, payload, "\n".join(lines))


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #


def cmd_history(args, ctx: Ctx) -> int:
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
            f"{stamp}  {row.get('flow', 'main')[:5]:<5}  {row.get('subject')}/{row.get('topic') or '-'}  "
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
        subjects = [slugify(part) for part in args.subjects.split(",") if part.strip()]
        if not subjects:
            return fail(ctx, "at least one subject is required")
        state["rotation"]["subjects"] = subjects
        state["rotation"]["index"] = 0
        state["rotation"]["cycle"] = 1
        state["pending"] = None
        for slug in subjects:
            ensure_subject(state, slug)
            (ctx.ws / "topics" / slug).mkdir(parents=True, exist_ok=True)
        changed["subjects"] = subjects

    save_state(ctx.ws, state)
    payload = {"ok": True, "changed": changed, "config": state["config"], "rotation": state["rotation"]}
    lines = [f"updated: {', '.join(changed) or 'nothing'}"]
    lines.append(f"rotation: {' → '.join(state['rotation']['subjects']) or '(none)'}")
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
    if slug not in state["rotation"]["subjects"]:
        state["rotation"]["subjects"].append(slug)
    save_state(ctx.ws, state)
    payload = {
        "ok": True,
        "subject": slug,
        "title": args.title or slug,
        "topics_dir": str(ctx.ws / "topics" / slug),
        "rotation": state["rotation"]["subjects"],
        "created": created,
    }
    return emit(
        ctx,
        payload,
        f"added: {slug} (position {state['rotation']['subjects'].index(slug) + 1}/{len(state['rotation']['subjects'])})\n"
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
    teach_next = teach_sub.add_parser("next", help="next chunk to teach")
    teach_next.add_argument("--subject", required=True)
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
