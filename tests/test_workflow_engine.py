import unittest

from workflow_engine import run_workflow, validate_workflow, workflow_summary


class WorkflowEngineTests(unittest.TestCase):
    def test_validates_and_summarizes_allowlisted_workflow(self):
        steps = validate_workflow([
            {"name": "lookup", "action": "lookup", "params": {"query": "weather"}},
            {"name": "notify", "action": "notify", "params": {"text": "done"}, "requires_approval": True},
        ], {"lookup", "notify"})
        summary = workflow_summary(steps)
        self.assertEqual(summary["step_count"], 2)
        self.assertEqual(summary["execution"], "not_run")
        self.assertTrue(summary["steps"][1]["requires_approval"])

    def test_rejects_unregistered_actions(self):
        with self.assertRaisesRegex(ValueError, "allowlist"):
            validate_workflow([{"action": "shell", "params": {"cmd": "whoami"}}], {"lookup"})

    def test_rejects_excessive_steps(self):
        with self.assertRaisesRegex(ValueError, "step limit"):
            validate_workflow([{"action": "lookup"} for _ in range(21)], {"lookup"})

    def test_requires_approval_before_mutation(self):
        steps = validate_workflow([{"name": "change", "action": "change", "requires_approval": True}], {"change"})
        called = []
        result = run_workflow(steps, {"change": lambda params: called.append(params)}, approve=lambda step: False)
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(called, [])

    def test_retries_are_bounded_and_eventually_succeed(self):
        steps = validate_workflow([{"action": "lookup", "retries": 2}], {"lookup"})
        attempts = []
        def flaky(_):
            attempts.append(1)
            if len(attempts) < 3:
                raise TimeoutError()
            return "ok"
        result = run_workflow(steps, {"lookup": flaky})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(attempts), 3)

    def test_failure_stops_following_steps(self):
        steps = validate_workflow([
            {"name": "bad", "action": "lookup"},
            {"name": "later", "action": "notify"},
        ], {"lookup", "notify"})
        called = []
        result = run_workflow(steps, {
            "lookup": lambda _: (_ for _ in ()).throw(RuntimeError()),
            "notify": lambda _: called.append(True),
        })
        self.assertEqual(result["status"], "failed")
        self.assertEqual(called, [])

    def test_rejects_invalid_retry_values(self):
        with self.assertRaisesRegex(ValueError, "retries"):
            validate_workflow([{"action": "lookup", "retries": 999}], {"lookup"})


if __name__ == "__main__":
    unittest.main()
