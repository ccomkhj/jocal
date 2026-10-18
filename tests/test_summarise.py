"""`jocal summarise <file> "<question>"`: map-reduce over a long document, straight to the runtime's /v1/messages."""

import json
import re
import unittest

from harness import JocalTest

QUESTION = "What is the filing deadline?"


def prompt(request):
    return "\n".join(m["content"] for m in request["messages"])


class Summarise(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf()

    def document(self, pages, chars=6000, name="doc.txt"):
        """A text of `pages` form-feed-separated pages, each `chars` long and marked at both ends."""
        body = "\f".join(f"<p{i}>" + "x" * (chars - 10) + f"</p{i}>" for i in range(1, pages + 1))
        path = self.project / name
        path.write_text(body)
        return path

    def test_maps_each_chunk_with_the_question_then_answers_from_the_notes_alone(self):
        doc = self.document(10)
        r = self.jocal("summarise", str(doc), QUESTION)
        self.assertEqual(r.returncode, 0, r.stderr)
        *maps, reduce = self.messages()
        self.assertGreater(len(maps), 1)
        for m in maps:
            self.assertIn(QUESTION, prompt(m))
        self.assertIn(QUESTION, prompt(reduce))
        for n in range(1, len(maps) + 1):
            self.assertIn(f"fake reply {n}", prompt(reduce))
        self.assertNotIn("<p1>", prompt(reduce))
        self.assertNotIn("xxxx", prompt(reduce))
        self.assertEqual(r.stdout.strip(), f"fake reply {len(maps) + 1}")

    def test_chunks_hold_whole_pages_packed_near_5k_tokens(self):
        doc = self.document(10)   # 10 pages of ~1.5K tokens
        self.jocal("summarise", str(doc), QUESTION)
        *maps, _ = self.messages()
        seen = []
        for m in maps:
            text = prompt(m)
            pages = [int(i) for i in re.findall(r"<p(\d+)>", text)]
            self.assertEqual(pages, [int(i) for i in re.findall(r"</p(\d+)>", text)], "a page was split")
            self.assertLessEqual(sum(len(p) for p in text.split("\n")) / 4, 5000 + 200)
            seen += pages
        self.assertEqual(seen, list(range(1, 11)))
        self.assertEqual([len(re.findall(r"<p\d+>", prompt(m))) for m in maps], [3, 3, 3, 1])

    def test_a_text_without_page_breaks_is_cut_on_lines_near_5k_tokens(self):
        doc = self.project / "notes.md"
        doc.write_text("".join(f"line {i} " + "y" * 90 + "\n" for i in range(600)))   # ~15K tokens
        self.jocal("summarise", str(doc), QUESTION)
        *maps, _ = self.messages()
        self.assertEqual(len(maps), 3)
        lines = [l for m in maps for l in prompt(m).splitlines() if l.startswith("line ")]
        self.assertEqual(lines, [f"line {i} " + "y" * 90 for i in range(600)])

    def test_the_notes_are_kept_with_the_question_and_the_answer(self):
        r = self.jocal("summarise", str(self.document(1)), QUESTION)
        [kept] = (self.state / "summaries").iterdir()
        notes = kept.read_text()
        for text in (QUESTION, "fake reply 1", "fake reply 2"):   # one map's notes, then the answer
            self.assertIn(text, notes)
        self.assertIn(str(kept), r.stderr)

    def test_a_pdf_is_converted_with_pdftotext_layout(self):
        pdf = self.project / "form.pdf"
        pdf.write_bytes(b"%PDF-1.7 fake")
        r = self.jocal("summarise", str(pdf), QUESTION)
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = json.loads((self.record / "pdftotext.json").read_text())
        self.assertEqual(argv[:2], ["-layout", str(pdf)])
        [m, _] = self.messages()
        self.assertIn("FILED BY 31 MARCH", prompt(m))

    def test_runs_on_the_model_picked_by_its_key(self):
        self.jocal("summarise", "--9b", str(self.document(1)), QUESTION)
        self.assertEqual({m["model"] for m in self.messages()}, {"Qwen3.5-9B-MLX-4bit"})

    def test_a_missing_file_fails_before_anything_starts(self):
        r = self.jocal("summarise", str(self.project / "nope.txt"), QUESTION)
        self.assertEqual(r.returncode, 2)
        self.assertIn("nope.txt", r.stderr)
        self.assertEqual(self.omlx_calls(), [])

    def test_notes_already_taken_are_kept_when_the_reduce_is_refused(self):
        r = self.jocal("summarise", str(self.document(1)), QUESTION, FAKE_MESSAGES_FAIL_AT="2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused", r.stderr)
        [kept] = (self.state / "summaries").iterdir()
        self.assertIn("fake reply 1", kept.read_text())

    def test_a_runtime_that_goes_away_fails_cleanly_and_keeps_the_notes(self):
        r = self.jocal("summarise", str(self.document(1)), QUESTION, FAKE_MESSAGES_DIE_AFTER="1")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(f"can't reach the runtime at http://127.0.0.1:{self.port}", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        [kept] = (self.state / "summaries").iterdir()
        self.assertIn("fake reply 1", kept.read_text())

    def test_an_empty_file_fails_with_exit_2_before_anything_starts(self):
        empty = self.project / "empty.txt"
        empty.write_text("")
        r = self.jocal("summarise", str(empty), QUESTION)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("empty.txt", r.stderr)
        self.assertEqual(self.omlx_calls(), [])

    def test_a_file_with_no_text_fails_with_exit_2(self):
        blank = self.project / "blank.txt"
        blank.write_text("\n  \f\n")
        r = self.jocal("summarise", str(blank), QUESTION)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("has no text", r.stderr)
        self.assertEqual(self.messages(), [])

    def test_an_empty_question_fails_with_exit_2_before_anything_starts(self):
        r = self.jocal("summarise", str(self.document(1)), "")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("usage: jocal summarise", r.stderr)
        self.assertEqual(self.omlx_calls(), [])

    def test_without_a_question_it_prints_usage(self):
        r = self.jocal("summarise", str(self.document(1)))
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: jocal summarise", r.stderr)


class Lifecycle(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf()
        self.doc = self.project / "doc.txt"
        self.doc.write_text("one page")

    def test_starts_the_runtime_holds_a_lease_and_stops_it_after_under_last_exit(self):
        r = self.jocal("summarise", str(self.doc), QUESTION, FAKE_LEASES_AT=str(self.state / "leases"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.omlx_calls()), 1)
        self.assertTrue(all(m["leases"] for m in self.messages()), "no lease held during a request")
        self.assertEqual(self.leases(), [])
        self.assertFalse(self.runtime_answers())

    def test_with_stop_runtime_manual_it_keeps_running(self):
        self.write_conf("STOP_RUNTIME=manual")
        self.jocal("summarise", str(self.doc), QUESTION)
        self.assertTrue(self.runtime_answers())

    def test_neither_sets_nor_clears_the_terminal_title(self):
        r = self.jocal("summarise", str(self.doc), QUESTION)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("\x1b]0;", r.stderr)

    def test_it_leaves_a_live_sessions_runtime_running(self):
        session = self.start_session()
        self.jocal("summarise", str(self.doc), QUESTION)
        self.assertTrue(self.runtime_answers())
        self.end_session(session)
        self.assertFalse(self.runtime_answers())


if __name__ == "__main__":
    unittest.main()
