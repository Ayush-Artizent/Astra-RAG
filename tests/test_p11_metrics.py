import unittest
from pathlib import Path

import yaml

from p11 import metrics as m
from p11.run_eval import compare, summarize

QUESTIONS = Path(__file__).parent.parent / "p11" / "questions.yaml"


def chunk(file, text="", heading=()):
    return {"file": file, "heading_path": list(heading), "text": text}


class SourceMatchingTests(unittest.TestCase):
    def test_file_matches_exactly_or_as_trailing_part(self):
        self.assertTrue(m.source_matches({"file": "stories.csv"}, chunk("project-data/jira-export/stories.csv")))
        self.assertTrue(m.source_matches({"file": "jira-export/stories.csv"}, chunk("project-data/jira-export/stories.csv")))
        self.assertFalse(m.source_matches({"file": "ories.csv"}, chunk("project-data/jira-export/stories.csv")))

    def test_heading_is_a_whole_segment_ignoring_case_and_numbering(self):
        scope = {"file": "epic.md", "heading": "Scope"}
        self.assertTrue(m.source_matches(scope, chunk("epic.md", heading=["Epic", "2. Scope"])))
        self.assertFalse(m.source_matches(scope, chunk("epic.md", heading=["Epic", "Not in scope"])))

    def test_row_must_be_in_the_text(self):
        spec = {"file": "stories.csv", "row": "CHK-104"}
        self.assertTrue(m.source_matches(spec, chunk("stories.csv", "Row 4\nid: CHK-104")))
        self.assertFalse(m.source_matches(spec, chunk("stories.csv", "Row 5\nid: CHK-105")))


class RankMetricTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [chunk("a.md"), chunk("b.md"), chunk("c.md"), chunk("d.md")]
        self.specs = [{"file": "b.md"}, {"file": "d.md"}, {"file": "z.md"}]

    def test_ranks_are_one_based_and_none_when_missing(self):
        self.assertEqual(m.source_ranks(self.specs, self.chunks), [2, 4, None])

    def test_recall_all_is_a_fraction_and_any_is_binary(self):
        ranks = m.source_ranks(self.specs, self.chunks)
        self.assertAlmostEqual(m.recall_at(ranks, "all", None), 2 / 3)
        self.assertAlmostEqual(m.recall_at(ranks, "all", 2), 1 / 3)
        self.assertEqual(m.recall_at(ranks, "any", 2), 1.0)
        self.assertEqual(m.recall_at([None, None], "any", None), 0.0)
        self.assertIsNone(m.recall_at([], "all", None))

    def test_reciprocal_rank_uses_the_best_source(self):
        self.assertEqual(m.reciprocal_rank([4, 2, None]), 0.5)
        self.assertEqual(m.reciprocal_rank([None]), 0.0)

    def test_dropped_relevant_counts_only_sources_that_were_present(self):
        self.assertEqual(m.dropped_relevant([1, 3, None], [1, None, None]), (1, 2))


class FactAndEvidenceTests(unittest.TestCase):
    def test_facts_ignore_case_spaces_and_thousands_commas(self):
        chunks = [chunk("a.md", "Limit is INR 10,000. Latency 2.5s. Cod-Enabled.")]
        self.assertEqual(m.fact_recall(["10000", "2.5 s", "COD-enabled", "missing"], chunks), 0.75)

    def test_evidence_averages_sources_and_facts(self):
        self.assertEqual(m.evidence_score({}, 1.0, 0.5, True), 0.75)

    def test_no_answer_question_wants_nothing_returned(self):
        self.assertEqual(m.evidence_score({"negative": True}, None, None, answered=False), 1.0)
        self.assertEqual(m.evidence_score({"negative": True}, None, None, answered=True), 0.0)


class RuleTests(unittest.TestCase):
    RULES = [{"file": "policies.md", "section": "7. Requirements", "text": "x"},
             {"file": "rules/pay.md", "section": "R-PAY-01 Idempotency", "text": "y"},
             {"file": "rules/pay.md", "section": "R-PAY-09 Extra", "text": "z"}]

    def test_tokens_match_by_file_and_number_or_by_text(self):
        self.assertTrue(m.rule_matches("policies.md#7", self.RULES[0]))
        self.assertFalse(m.rule_matches("policies.md#1", self.RULES[0]))
        self.assertFalse(m.rule_matches("policies.md#7", {"file": "policies.md", "section": "70. Other", "text": ""}))
        self.assertTrue(m.rule_matches("R-PAY-01", self.RULES[1]))

    def test_precision_recall_and_what_was_missed(self):
        out = m.rule_scores(["policies.md#7", "R-PAY-01", "R-SEC-01"], self.RULES)
        self.assertAlmostEqual(out["precision"], 2 / 3)
        self.assertAlmostEqual(out["recall"], 2 / 3)
        self.assertEqual(out["missing"], ["R-SEC-01"])
        self.assertEqual(out["unexpected"], ["rules/pay.md#R-PAY-09 Extra"])

    def test_template_match(self):
        self.assertTrue(m.template_ok("brd-payments", {"variant": "brd-payments-template", "path": "t/x.md"}))
        self.assertFalse(m.template_ok("brd-payments", None))
        self.assertIsNone(m.template_ok(None, None))


class CombinedTests(unittest.TestCase):
    def test_weights(self):
        self.assertAlmostEqual(m.combined(1.0, 0.5, 0.0), 0.6 + 0.15 + 0.1)

    def test_missing_part_is_left_out_and_rest_rescaled(self):
        self.assertAlmostEqual(m.combined(0.5, None, 0.0), (0.6 * 0.5 + 0.1) / 0.7)
        self.assertIsNone(m.combined(None, None, None))


class QuestionSetTests(unittest.TestCase):
    def test_every_question_is_well_formed(self):
        spec = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
        ids = [q["id"] for q in spec["questions"]]
        self.assertEqual(len(ids), len(set(ids)))
        for q in spec["questions"]:
            self.assertIn(q.get("match", "all"), ("all", "any"))
            self.assertTrue(q.get("negative") or (q["sources"] and q["facts"]), q["id"])
            self.assertTrue(all("file" in s for s in q["sources"]), q["id"])
        self.assertTrue(all(c["rules"] and c["doc_type"] for c in spec["rule_cases"]))


class SummaryAndBaselineTests(unittest.TestCase):
    ROW = {"id": "E01", "negative": False, "difficulty": "easy", "evidence": 1.0, "degraded": False, "recall_10": 1.0,
           "recall_all": 1.0, "rr": 1.0, "recall_5": 1.0, "dropped": (0, 1), "recall_kept": 1.0, "recall_budget": 1.0,
           "facts_budget": 1.0, "knowledge_truncated": False, "knowledge_status": "ok", "rerank_status": "ok",
           "final_items": 3, "seconds": 2.0}
    CFG = {"candidates": 30}

    def test_summary_combines_the_parts(self):
        rule = {"id": "C01", "precision": 1.0, "recall": 1.0, "f1": 1.0, "template": True}
        s = summarize([self.ROW], [rule], self.CFG)
        self.assertEqual(s["combined"], 1.0)
        self.assertEqual(s["rerank"]["dropped_relevant_rate"], 0.0)

    def test_compare_flags_a_question_that_got_worse(self):
        base_rows = [self.ROW]
        worse = [{**self.ROW, "evidence": 0.5}]
        baseline = {"questions": base_rows, "rule_cases": [], "summary": summarize(base_rows, [], self.CFG)}
        bad = compare(baseline, worse, [], summarize(worse, [], self.CFG), 0.02)
        self.assertTrue(any("E01" in line for line in bad))
        self.assertEqual(compare(baseline, base_rows, [], summarize(base_rows, [], self.CFG), 0.02), [])



class PolicyReplayTests(unittest.TestCase):
    ROW = {"overhead_tokens": 100, "trace": [
        {"score": 5.0, "tokens": 50, "sources": [0], "facts": [0]},
        {"score": -3.0, "tokens": 50, "sources": [1], "facts": []},
        {"score": -8.0, "tokens": 50, "sources": [2], "facts": [1]}]}
    Q = {"sources": [{}, {}, {}], "facts": ["a", "b"], "match": "all"}

    def test_floor_and_margin_cut_hits(self):
        from p11.policies import replay
        self.assertAlmostEqual(replay(self.ROW, self.Q, -9, None, 1000), 1.0)
        self.assertAlmostEqual(replay(self.ROW, self.Q, -5, None, 1000), (2 / 3 + 0.5) / 2)
        self.assertAlmostEqual(replay(self.ROW, self.Q, -9, 2, 1000), (1 / 3 + 0.5) / 2)

    def test_budget_ends_the_list_at_the_first_hit_that_does_not_fit(self):
        from p11.policies import replay
        self.assertAlmostEqual(replay(self.ROW, self.Q, -9, None, 160), (1 / 3 + 0.5) / 2)

    def test_no_answer_question_wants_an_empty_result(self):
        from p11.policies import replay
        q = {"negative": True, "sources": [], "facts": []}
        self.assertEqual(replay(self.ROW, q, 9, None, 1000), 1.0)
        self.assertEqual(replay(self.ROW, q, -9, None, 1000), 0.0)


if __name__ == "__main__":
    unittest.main()
