#!/usr/bin/env python3
"""End-to-end tests for the practice-loop CLI."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "practice_loop.py"


class PracticeLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="practice-loop-test-"))
        self.ws = self.tmp / "workspace"
        self.ws.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, expect=0):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *args, "--workspace", str(self.ws), "--json"],
            capture_output=True,
            text=True,
            cwd=str(self.ws),
        )
        if expect is not None:
            self.assertEqual(proc.returncode, expect, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")
        if not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)

    def init(self, *extra):
        return self.run_cli("init", *extra)

    def next(self):
        return self.run_cli("next")

    def record(self, result, **kwargs):
        args = ["record", "--result", result]
        for key, value in kwargs.items():
            args += ["--" + key.replace("_", "-"), str(value)]
        return self.run_cli(*args)

    # ------------------------------------------------------------------ #

    def test_init_creates_folders_and_is_idempotent(self):
        first = self.init("--subjects", "sql,csharp-dsa", "--difficulty", "adaptive")
        self.assertTrue(first["created"])
        for name in ("notes", "rough", "weak", "topics", ".practice-loop"):
            self.assertTrue((self.ws / name).is_dir(), name)
        self.assertTrue((self.ws / "HOW-IT-WORKS.md").is_file())
        self.assertTrue((self.ws / ".practice-loop" / "state.json").is_file())

        second = self.init()
        self.assertFalse(second["created"])
        self.assertEqual(second["subjects"], ["sql", "csharp-dsa"])

    def test_subject_labels_keep_learner_wording(self):
        first = self.init("--subjects", "SQL,C# DSA,OOP,DBMS,C# theory")
        self.assertEqual(
            first["subjects"], ["sql", "csharp-dsa", "oop", "dbms", "csharp-theory"]
        )
        self.assertEqual(first["labels"]["csharp-dsa"], "C# DSA")
        self.assertTrue((self.ws / "topics" / "csharp-dsa").is_dir())

        brief = self.next()
        self.assertEqual(brief["subject"], "sql")
        self.assertEqual(brief["subject_label"], "SQL")
        self.record("correct", topic="general")

        second = self.next()
        self.assertEqual(second["subject"], "csharp-dsa")
        self.assertEqual(second["subject_label"], "C# DSA")
        self.assertEqual(self.run_cli("status")["labels"]["csharp-theory"], "C# theory")
        self.record("correct", topic="general")

        added = self.run_cli("add-subject", "C# LINQ")
        self.assertEqual(added["subject_label"], "C# LINQ")
        self.assertTrue((self.ws / "topics" / "csharp-linq").is_dir())

    def test_changing_subjects_prunes_untouched_leftovers(self):
        self.init("--subjects", "SQL,C# DSA,OOP")
        self.record("correct", subject="sql", topic="general")
        self.run_cli("set", "--subjects", "SQL,OOP")
        state = json.loads((self.ws / ".practice-loop" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["rotation"]["subjects"], ["sql", "oop"])
        self.assertNotIn("csharp-dsa", state["subjects"])
        self.assertIn("sql", state["subjects"])

    def test_init_does_not_touch_existing_notes(self):
        (self.ws / "notes").mkdir()
        (self.ws / "notes" / "mine.md").write_text("my own notes", encoding="utf-8")
        self.init()
        self.assertEqual((self.ws / "notes" / "mine.md").read_text(encoding="utf-8"), "my own notes")

    def test_rotation_cycles_in_order(self):
        self.init("--subjects", "sql,csharp-dsa,oop")
        seen = []
        for _ in range(6):
            brief = self.next()
            seen.append(brief["subject"])
            self.record("correct", topic="general")
        self.assertEqual(seen, ["sql", "csharp-dsa", "oop", "sql", "csharp-dsa", "oop"])
        for index in range(1, len(seen)):
            self.assertNotEqual(seen[index - 1], seen[index])

    def test_pending_blocks_second_question(self):
        self.init("--subjects", "sql,csharp")
        self.next()
        blocked = self.next()
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["reason"], "pending")
        self.record("skipped")
        self.assertTrue(self.next()["ok"])

    def test_weak_created_then_cleared_by_main_flow(self):
        self.init("--subjects", "sql")
        self.next()
        self.record("wrong", topic="joins", misconception="Confuses ON with WHERE")
        weak = self.run_cli("weak")
        self.assertEqual(weak["count"], 1)
        self.assertEqual(weak["topics"][0]["topic"], "joins")
        self.assertTrue((self.ws / "weak" / "sql" / "joins.md").is_file())

        brief = self.next()
        self.assertEqual(brief["focus"]["kind"], "weak")
        self.assertTrue(brief["focus"]["retest"])
        self.record("correct")
        weak = self.run_cli("weak")
        self.assertEqual(weak["count"], 0)
        latest = (self.ws / "weak" / "mastered" / "sql" / "joins.md")
        self.assertTrue(latest.is_file())

    def test_hardened_weakness_needs_two_clean_answers(self):
        self.init("--subjects", "sql")
        for _ in range(3):
            self.next()
            self.record("wrong", topic="joins")
        self.next()
        result = self.record("correct")
        self.assertEqual(result["weak"]["required_streak"], 2)
        self.assertFalse(result["weak"]["cleared"])
        self.next()
        result = self.record("correct")
        self.assertTrue(result["weak"]["cleared"])

    def test_partial_credit_keeps_weakness_open(self):
        self.init("--subjects", "sql")
        self.next()
        result = self.record("partial", topic="aggregation")
        self.assertEqual(result["weak"]["status"], "weak")
        self.assertEqual(result["weak"]["misses"], 0)
        self.assertEqual(self.run_cli("weak")["topics"][0]["partials"], 1)

    def test_teach_correct_never_clears_weakness(self):
        self.init("--subjects", "sql")
        (self.ws / "topics" / "sql").mkdir(parents=True, exist_ok=True)
        (self.ws / "topics" / "sql" / "01-joins.md").write_text(
            "---\ntitle: Joins\n---\n# Joins\n", encoding="utf-8"
        )
        self.next()
        self.record("wrong", topic="joins")

        check = self.run_cli("teach", "next", "--subject", "sql")
        self.assertEqual(check["chunk"], "01-joins.md")
        self.run_cli(
            "teach", "record", "--subject", "sql", "--result", "correct", "--complete"
        )
        self.assertEqual(self.run_cli("weak")["count"], 1, "teach flow must not clear weakness")

        self.next()
        self.record("correct")
        self.assertEqual(self.run_cli("weak")["count"], 0)

    def test_teach_wrong_saves_weakness_and_does_not_advance(self):
        self.init("--subjects", "sql")
        folder = self.ws / "topics" / "sql"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "01-joins.md").write_text("---\ntitle: Joins\n---\n", encoding="utf-8")
        (folder / "02-aggregation.md").write_text("---\ntitle: Aggregation\n---\n", encoding="utf-8")

        first = self.run_cli("teach", "next", "--subject", "sql")
        self.assertEqual(first["chunk"], "01-joins.md")
        failed = self.run_cli(
            "teach", "record", "--subject", "sql", "--result", "wrong", "--topic", "joins"
        )
        self.assertFalse(failed["chunk_complete"])
        still = self.run_cli("teach", "next", "--subject", "sql")
        self.assertEqual(still["chunk"], "01-joins.md")
        self.assertEqual(self.run_cli("weak")["count"], 1)

        self.run_cli("teach", "record", "--subject", "sql", "--result", "correct", "--complete")
        moved = self.run_cli("teach", "next", "--subject", "sql")
        self.assertEqual(moved["chunk"], "02-aggregation.md")

    def test_mastered_topic_reopens_after_a_miss(self):
        self.init("--subjects", "sql")
        self.next()
        self.record("wrong", topic="joins")
        self.next()
        self.record("correct")
        self.assertEqual(self.run_cli("weak")["count"], 0)

        self.next()
        result = self.record("wrong", topic="joins")
        self.assertEqual(result["weak"]["status"], "weak")
        self.assertEqual(self.run_cli("weak")["count"], 1)
        self.assertTrue((self.ws / "weak" / "sql" / "joins.md").is_file())
        self.assertFalse((self.ws / "weak" / "mastered" / "sql" / "joins.md").exists())

    def test_report_accuracy_and_per_subject(self):
        self.init("--subjects", "sql,csharp")
        self.next()
        self.record("correct", topic="general")
        self.next()
        self.record("wrong", topic="recursion")
        self.next()
        self.record("partial", topic="joins")
        self.next()
        self.record("skipped")

        report = self.run_cli("report")
        overall = report["overall"]
        self.assertEqual(overall["correct"], 1)
        self.assertEqual(overall["wrong"], 1)
        self.assertEqual(overall["partial"], 1)
        self.assertEqual(overall["skipped"], 1)
        self.assertAlmostEqual(overall["accuracy_weighted"], 0.5, places=3)
        self.assertAlmostEqual(overall["accuracy_strict"], 1 / 3, places=3)
        self.assertEqual(report["by_subject"]["sql"]["attempts"], 2)
        self.assertEqual(report["by_subject"]["csharp"]["attempts"], 2)

    def test_off_rotation_record_does_not_advance(self):
        self.init("--subjects", "sql,csharp")
        self.next()
        self.record("correct", topic="general")
        before = self.run_cli("status")
        self.record("correct", subject="sql", topic="joins")
        after = self.run_cli("status")
        self.assertEqual(before["position"], after["position"])
        self.assertIsNone(after["pending"])

    def test_subject_mismatch_is_rejected(self):
        self.init("--subjects", "sql,csharp")
        self.next()
        failure = self.run_cli(
            "record", "--result", "correct", "--subject", "csharp", expect=9
        )
        self.assertFalse(failure["ok"])

    def test_set_subjects_resets_pending(self):
        self.init("--subjects", "sql,csharp")
        self.next()
        changed = self.run_cli("set", "--subjects", "oop,dbms")
        self.assertEqual(changed["rotation"]["subjects"], ["oop", "dbms"])
        self.assertTrue((self.ws / "topics" / "oop").is_dir())
        self.assertTrue(self.next()["ok"])

    def test_adaptive_difficulty_drops_after_failures(self):
        self.init("--subjects", "sql")
        for _ in range(3):
            self.next()
            self.record("wrong", topic="joins")
        status = self.run_cli("status")
        self.assertEqual(status["difficulty"], "adaptive")
        brief = self.next()
        self.assertEqual(brief["difficulty"], "beginner")

    def test_reset_requires_confirmation(self):
        self.init("--subjects", "sql")
        self.next()
        self.record("wrong", topic="joins")
        self.run_cli("reset", expect=8)
        self.assertTrue((self.ws / ".practice-loop" / "state.json").is_file())
        done = self.run_cli("reset", "--yes")
        self.assertTrue(done["ok"])
        self.assertFalse((self.ws / ".practice-loop" / "state.json").exists())
        self.assertTrue((self.ws / "notes").is_dir())

    def test_session_limit_stops_the_loop(self):
        self.init("--subjects", "sql", "--limit", "2")
        self.next()
        self.record("correct", topic="general")
        self.next()
        self.record("correct", topic="general")
        blocked = self.next()
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["reason"], "limit")
        self.run_cli("session", "new")
        self.assertTrue(self.next()["ok"])

    def test_history_is_newest_first(self):
        self.init("--subjects", "sql")
        self.next()
        self.record("wrong", topic="joins", misconception="Counts the NULL row")
        self.next()
        self.record("correct", topic="select")
        history = self.run_cli("history", "--limit", "5")
        self.assertEqual(history["count"], 2)
        self.assertEqual(history["attempts"][0]["result"], "correct")
        self.assertEqual(history["attempts"][1]["misconception"], "Counts the NULL row")

    def test_topic_labels_are_normalised(self):
        self.init("--subjects", "sql")
        self.next()
        self.record("wrong", topic="LEFT JOIN NULL")
        self.assertTrue((self.ws / "weak" / "sql" / "left-join-null.md").is_file())
        self.assertEqual(self.run_cli("weak")["topics"][0]["topic"], "left-join-null")

    def test_one_bad_answer_does_not_change_difficulty(self):
        self.init("--subjects", "sql")
        self.next()
        self.record("wrong", topic="joins")
        brief = self.next()
        self.assertEqual(brief["difficulty"], "intermediate")

    def test_session_new_keeps_history_and_weakness(self):
        self.init("--subjects", "sql")
        self.next()
        self.record("wrong", topic="joins")
        self.run_cli("session", "new")
        status = self.run_cli("status")
        self.assertEqual(status["session"]["asked"], 0)
        self.assertEqual(status["weak_active"], 1)

    def test_quiet_default_human_output(self):
        self.init("--subjects", "sql")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "status", "--workspace", str(self.ws)],
            capture_output=True,
            text=True,
            cwd=str(self.ws),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("rotation: sql", proc.stdout)

    def test_no_workspace_errors(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "next", "--workspace", str(self.tmp / "nope"), "--json"],
            capture_output=True,
            text=True,
            cwd=str(self.tmp),
        )
        self.assertEqual(proc.returncode, 3)
        self.assertFalse(json.loads(proc.stdout)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
