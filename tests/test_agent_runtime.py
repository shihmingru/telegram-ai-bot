import unittest

from agent_runtime import AgentBudget, compact_tool_result, list_skill_names, runtime_guidance, run_parallel_analysis


class AgentBudgetTests(unittest.TestCase):
    def test_step_budget_stops_at_limit(self):
        budget = AgentBudget(max_steps=2, max_tool_calls=3)
        self.assertTrue(budget.begin_step())
        self.assertTrue(budget.begin_step())
        self.assertFalse(budget.begin_step())
        self.assertEqual(budget.steps_used, 2)

    def test_tool_budget_stops_at_limit(self):
        budget = AgentBudget(max_steps=3, max_tool_calls=2)
        self.assertTrue(budget.record_tool_call("web_search"))
        self.assertTrue(budget.record_tool_call("web_open"))
        self.assertFalse(budget.record_tool_call("web_crawl"))
        self.assertEqual(budget.remaining_tool_calls, 0)
        self.assertEqual(budget.tools_used, ["web_search", "web_open"])

    def test_tool_result_is_json_safe(self):
        result = compact_tool_result({"count": 2, "ok": True})
        self.assertEqual(result, {"count": 2, "ok": True})

    def test_large_tool_result_is_bounded(self):
        result = compact_tool_result({"text": "x" * 5000}, max_chars=500)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["preview"]), 500)
        self.assertGreater(result["original_characters"], 500)

    def test_skill_catalog_is_available(self):
        names = list_skill_names()
        self.assertIn("french", names)
        self.assertIn("buddhist studies", names)


    def test_parallel_analysis_runs_bounded_tasks(self):
        result = run_parallel_analysis(
            ["summarize argument A", "summarize argument B"],
            lambda task: "result for " + task,
        )
        self.assertEqual(result["tasks_completed"], 2)
        self.assertFalse(result["isolated_agent"])
        self.assertEqual(len(result["results"]), 2)
        self.assertIn("no paid fallback", result["note"])

    def test_parallel_analysis_rejects_too_many_tasks(self):
        result = run_parallel_analysis(
            ["one", "two", "three", "four"], lambda task: task
        )
        self.assertIn("error", result)

    def test_runtime_guidance_includes_cost_and_verification_rules(self):
        guidance = runtime_guidance()
        self.assertIn("zero-cost", guidance)
        self.assertIn("confirming tool result", guidance)


if __name__ == "__main__":
    unittest.main()
