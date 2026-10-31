"""The notes put in front of a payload when a plane says something is off."""
import unittest

from astra_mcp import notes


class CodeQueryNoteTests(unittest.TestCase):
    def test_a_clean_answer_gets_no_note(self):
        self.assertIsNone(notes.code_query({
            "plane_status": "ok", "results": [{"plane_rank": 1}],
            "resolved_symbols": [{"input": "A.b", "status": "exact"}], "truncated": False,
        }))

    def test_an_unbuilt_index_says_so_and_that_documents_still_work(self):
        note = notes.code_query({"plane_status": "not_ready", "results": [],
                                 "snapshot": {"index_state": "not_indexed"}})
        self.assertIn("not ready", note)
        self.assertIn("not_indexed", note)
        self.assertIn("Documents are unaffected", note)

    def test_an_ambiguous_symbol_explains_the_empty_result_and_how_to_retry(self):
        # The adapter refuses an ambiguous name by default, so results are empty for a reason the
        # payload only hints at.
        note = notes.code_query({"plane_status": "degraded", "results": [], "resolved_symbols": [
            {"input": "filter", "status": "ambiguous", "alternatives": [
                {"qualified_name": "QuerySet.filter"}, {"qualified_name": "defaultfilters.filter"}]},
        ]})
        self.assertIn("matched several symbols", note)
        self.assertIn("QuerySet.filter", note)
        self.assertIn("qualified name", note)

    def test_a_symbol_that_matched_nothing_is_named(self):
        note = notes.code_query({"plane_status": "degraded", "results": [],
                                 "resolved_symbols": [{"input": "Nope.gone", "status": "not_found"}]})
        self.assertIn("'Nope.gone' matched no symbol", note)

    def test_a_running_sync_warns_that_lines_may_not_match(self):
        note = notes.code_query({"plane_status": "degraded", "results": [{"plane_rank": 1}],
                                 "snapshot": {"sync_in_progress": True}})
        self.assertIn("sync is running", note)

    def test_truncation_says_how_to_get_more(self):
        note = notes.code_query({"plane_status": "ok", "results": [{"plane_rank": 1}], "truncated": True})
        self.assertIn("limit", note)

    def test_an_empty_but_healthy_answer_suggests_what_to_try(self):
        note = notes.code_query({"plane_status": "ok", "results": [], "resolved_symbols": []})
        self.assertIn("Nothing matched", note)

    def test_a_percent_sign_in_a_symbol_name_does_not_blow_up(self):
        note = notes.code_query({"plane_status": "degraded", "results": [], "resolved_symbols": [
            {"input": "pct", "status": "fuzzy", "qualified_name": "Fmt.100%done"}]})
        self.assertIn("100%done", note)

    def test_malformed_resolved_symbols_are_ignored_rather_than_raising(self):
        self.assertIsNone(notes.code_query({"plane_status": "ok", "results": [{"x": 1}],
                                            "resolved_symbols": ["not a dict", None]}))


class CodeStatusNoteTests(unittest.TestCase):
    def test_a_ready_index_with_no_lag_gets_no_note(self):
        self.assertIsNone(notes.code_status({"state": "ready", "index_lag_seconds": 0, "error": None}))

    def test_a_state_other_than_ready_is_explained(self):
        self.assertIn("'indexing'", notes.code_status({"state": "indexing"}))

    def test_lag_and_errors_are_reported(self):
        note = notes.code_status({"state": "ready", "index_lag_seconds": 600, "error": "clone failed"})
        self.assertIn("10 minute", note)
        self.assertIn("clone failed", note)

    def test_a_pruned_project_says_it_is_being_rebuilt(self):
        self.assertIn("rebuilt", notes.code_status({"state": "not_indexed", "pruned_at": "2026-10-30T00:00:00Z"}))


class DocNoteTests(unittest.TestCase):
    def test_a_healthy_answer_gets_no_note(self):
        self.assertIsNone(notes.doc_context({"data": {"status": {"knowledge": "ok", "rerank": "ok"},
                                                      "warnings": [], "stale": False}}))

    def test_an_unindexed_project_says_rules_are_still_there(self):
        note = notes.doc_context({"data": {"status": {"knowledge": "no_index"}}})
        self.assertIn("not been indexed", note)
        self.assertIn("rules and template still are", note)

    def test_a_search_failure_is_reported_with_its_safe_reason(self):
        note = notes.doc_context({"data": {"status": {"knowledge": "unavailable: ConnectionError"}}})
        self.assertIn("ConnectionError", note)

    def test_stale_rules_say_the_host_was_unreachable(self):
        self.assertIn("cached copy", notes.doc_context({"data": {"stale": True}}))

    def test_plane_warnings_are_passed_through(self):
        note = notes.doc_context({"data": {"warnings": [
            {"code": "budget_truncated", "message": "Over the token budget, so content was left out: knowledge."}]}})
        self.assertIn("left out", note)

    def test_it_also_reads_a_payload_that_is_not_wrapped_in_data(self):
        # search_project_data returns items and status without the `data` wrapper.
        note = notes.doc_context({"status": {"knowledge": "empty"}})
        self.assertIn("No project data matched", note)


if __name__ == "__main__":
    unittest.main()
