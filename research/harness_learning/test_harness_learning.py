"""harness_learning.py 的單元測試（只用標準庫、不需真模型）。

執行：python3 -m unittest research/harness_learning/test_harness_learning.py -v
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness_learning as hl  # noqa: E402
from demo_small_sample import BAD_EDIT, GOOD_EDIT, TASK, fake_solver, make_fake_proposer, questions  # noqa: E402

SEED = hl.SEED_HARNESS


def _seq(*responses):
    """依序回傳給定回應的假 proposer；用完後一律回 'nothing'。"""
    it = iter(responses)

    def proposer(prompt):
        return next(it, "nothing")

    return proposer


class ApplyEditsTests(unittest.TestCase):
    def test_exact_edit(self):
        new = hl.apply_edits(SEED, GOOD_EDIT)
        self.assertIn("import re", new)
        self.assertNotIn("return model(question).strip()\n\ndef", new)

    def test_search_not_found(self):
        with self.assertRaises(hl.EditError) as cm:
            hl.apply_edits(SEED, BAD_EDIT)
        self.assertIn("found 0", str(cm.exception))

    def test_partial_line_match_rejected(self):
        # 兩格縮排的 SEARCH 不應命中四格縮排那行的中間（會把縮排疊加成語法錯誤）
        edit = "<<<<<<< SEARCH\n  return model(question).strip()\n=======\n    return 'x'\n>>>>>>> REPLACE"
        with self.assertRaises(hl.EditError) as cm:
            hl.apply_edits(SEED, edit)
        self.assertIn("found 0", str(cm.exception))

    def test_ambiguous_search(self):
        edit = "<<<<<<< SEARCH\na = 1\n=======\na = 3\n>>>>>>> REPLACE"
        with self.assertRaises(hl.EditError) as cm:
            hl.apply_edits("a = 1\nb = 2\na = 1\n", edit)
        self.assertIn("found 2", str(cm.exception))

    def test_empty_search(self):
        edit = "<<<<<<< SEARCH\n\n=======\nx = 1\n>>>>>>> REPLACE"
        with self.assertRaises(hl.EditError):
            hl.apply_edits(SEED, edit)

    def test_syntax_error_rejected(self):
        edit = "<<<<<<< SEARCH\n    return model(question).strip()\n=======\n    return model(question\n>>>>>>> REPLACE"
        with self.assertRaises(hl.EditError) as cm:
            hl.apply_edits(SEED, edit)
        self.assertIn("does not parse", str(cm.exception))

    def test_no_change(self):
        self.assertEqual(hl.apply_edits(SEED, "I think NO_CHANGE is right."), SEED)

    def test_no_blocks(self):
        with self.assertRaises(hl.EditError):
            hl.apply_edits(SEED, "just prose")

    def test_multiple_blocks_in_order(self):
        edit = ("<<<<<<< SEARCH\nx = 1\n=======\nx = 10\n>>>>>>> REPLACE\n"
                "<<<<<<< SEARCH\ny = 2\n=======\ny = 20\n>>>>>>> REPLACE")
        self.assertEqual(hl.apply_edits("x = 1\ny = 2\n", edit), "x = 10\ny = 20\n")

    def test_parses_predicate(self):
        self.assertTrue(hl.parses(BAD_EDIT))
        self.assertTrue(hl.parses("NO_CHANGE"))
        self.assertFalse(hl.parses("prose only"))


class ExecuteTests(unittest.TestCase):
    def test_score_is_mean(self):
        qs = questions(6, seed=3)
        self.assertEqual(hl.execute(SEED, TASK, qs, fake_solver).score, 0.0)
        res = hl.execute(hl.apply_edits(SEED, GOOD_EDIT), TASK, qs, fake_solver)
        self.assertEqual(res.score, 1.0)
        self.assertEqual(res.completed_fraction, 1.0)
        self.assertTrue(res.runnable)

    def test_load_error(self):
        res = hl.execute("def nope(): pass", TASK, questions(2, 0), fake_solver)
        self.assertFalse(res.runnable)
        self.assertEqual(res.score, 0.0)
        self.assertIn("must define solve", res.load_error)
        self.assertIn("failed to load", hl.build_report(res))

    def test_runtime_error_recorded_with_calls(self):
        src = "def solve(model, question):\n    model('hi')\n    raise ValueError('boom')\n"
        res = hl.execute(src, TASK, questions(1, 0), lambda p: "r")
        rec = res.records[0]
        self.assertEqual(rec.error, "ValueError: boom")
        self.assertEqual(rec.calls, [("hi", "r")])
        self.assertEqual(res.completed_fraction, 0.0)

    def test_call_budget(self):
        src = "def solve(model, question):\n    for _ in range(10):\n        model(question)\n    return '1'\n"
        res = hl.execute(src, TASK, questions(1, 0), lambda p: "x", max_calls=3)
        self.assertIn("budget exceeded", res.records[0].error)
        self.assertEqual(len(res.records[0].calls), 3)

    @unittest.skipUnless(hasattr(hl.signal, "SIGALRM"), "needs Unix signals")
    def test_timeout(self):
        src = "def solve(model, question):\n    while True:\n        pass\n"
        t0 = time.time()
        res = hl.execute(src, TASK, questions(1, 0), fake_solver, timeout=0.2)
        self.assertLess(time.time() - t0, 3)
        self.assertIn("HarnessTimeout", res.records[0].error)


class ReportAndPromptTests(unittest.TestCase):
    def test_report_lists_failures_and_calls(self):
        res = hl.execute(SEED, TASK, questions(3, seed=5), fake_solver)
        text = hl.build_report(res, max_failures=2)
        self.assertIn("Score: 0.000 on 3 questions", text)
        self.assertEqual(text.count("--- FAILED ---"), 2)
        self.assertIn("[call 1] output: '42'", text)
        prompt = hl.build_prompt(TASK, SEED, res)
        self.assertIn(SEED.strip(), prompt)
        self.assertIn("NO_CHANGE", prompt)
        self.assertIn("development score 0.000", prompt)


class ProposeTests(unittest.TestCase):
    def test_retry_with_feedback(self):
        seen = []

        def proposer(p):
            seen.append(p)
            return BAD_EDIT if len(seen) == 1 else GOOD_EDIT

        prop = hl.propose(proposer, "PROMPT", SEED, max_attempts=3)
        self.assertTrue(prop.parsed)
        self.assertIn("import re", prop.source)
        self.assertEqual(len(seen), 2)
        self.assertIn("previous edit was rejected", seen[1])
        self.assertIn("found 0", seen[1])

    def test_gives_up_parsed_flag_follows_eq8(self):
        prop = hl.propose(_seq(BAD_EDIT, BAD_EDIT), "PROMPT", SEED, max_attempts=2)
        self.assertIsNone(prop.source)
        self.assertTrue(prop.parsed)  # 格式正確但套不上：parses=1, applies=0
        prop = hl.propose(_seq("prose", "prose"), "PROMPT", SEED, max_attempts=2)
        self.assertIsNone(prop.source)
        self.assertFalse(prop.parsed)


class AdaptTests(unittest.TestCase):
    def test_improve_only_keeps_better_then_holds(self):
        best, hist = hl.adapt(TASK, questions(5, 0), _seq(GOOD_EDIT), fake_solver, rounds=2)
        self.assertIn("import re", best)
        self.assertEqual([r.dev_score for r in hist], [1.0, 1.0])
        self.assertEqual(hist[1].candidate_scores, [0.0])  # 第二輪 'nothing' → 失敗修訂記 0

    def test_improve_only_rejects_worse_and_no_change(self):
        good = hl.apply_edits(SEED, GOOD_EDIT)
        worse = "<<<<<<< SEARCH\n        return str(a + b if op == \"+\" else a - b if op == \"-\" else a * b)\n=======\n        return 'wrong'\n>>>>>>> REPLACE"
        best, hist = hl.adapt(TASK, questions(4, 0), _seq(worse, "NO_CHANGE"), fake_solver,
                              seed=good, rounds=2)
        self.assertEqual(best, good)
        self.assertEqual(hist[0].candidate_scores, [0.0])
        self.assertEqual(hist[1].candidate_scores, [1.0])  # NO_CHANGE 以 parent 計分
        self.assertEqual(hist[1].dev_score, 1.0)

    def test_best_of_g_accepts_worse_and_picks_highest(self):
        good = hl.apply_edits(SEED, GOOD_EDIT)
        worse = "<<<<<<< SEARCH\n        return str(a + b if op == \"+\" else a - b if op == \"-\" else a * b)\n=======\n        return 'wrong'\n>>>>>>> REPLACE"
        best, hist = hl.adapt(TASK, questions(4, 0), _seq(worse), fake_solver, seed=good, rounds=1,
                              select="best_of_g")
        self.assertIn("'wrong'", best)
        self.assertEqual(hist[0].dev_score, 0.0)
        # 兩個候選：一半對 vs 全對，best_of_g 取全對
        half = ("<<<<<<< SEARCH\n    return model(question).strip()\n=======\n"
                "    import re\n    m = re.search(r'(\\d+) \\+ (\\d+)', question)\n"
                "    return str(int(m.group(1)) + int(m.group(2))) if m else '0'\n>>>>>>> REPLACE")
        qs = [hl.Question("What is 1 + 2?", "3"), hl.Question("What is 2 * 3?", "6")]
        best, hist = hl.adapt(TASK, qs, _seq(half, GOOD_EDIT), fake_solver, rounds=1, candidates=2,
                              select="best_of_g")
        self.assertEqual(hist[0].candidate_scores, [0.5, 1.0])
        self.assertEqual(hist[0].dev_score, 1.0)

    def test_best_of_g_stays_when_all_fail(self):
        best, hist = hl.adapt(TASK, questions(3, 0), _seq("prose", "prose"), fake_solver, rounds=1,
                              candidates=2, select="best_of_g")
        self.assertEqual(best, SEED)
        self.assertEqual(hist[0].candidate_scores, [0.0, 0.0])

    def test_disjoint_feedback_and_scoring(self):
        best, hist = hl.adapt(TASK, questions(10, 7), _seq(GOOD_EDIT), fake_solver, rounds=1,
                              n_feedback=4, n_score=6)
        self.assertEqual(hist[0].dev_score, 1.0)

    def test_bad_select(self):
        with self.assertRaises(ValueError):
            hl.adapt(TASK, questions(2, 0), _seq(GOOD_EDIT), fake_solver, rounds=1, select="nope")


class RLTests(unittest.TestCase):
    def test_revision_reward_eq8(self):
        qs = questions(4, 0)
        good = hl.apply_edits(SEED, GOOD_EDIT)
        res = hl.execute(good, TASK, qs, fake_solver)
        self.assertAlmostEqual(hl.revision_reward(hl.Proposal("y", good, True), res), 1.0 + 0.30)
        res0 = hl.execute(SEED, TASK, qs, fake_solver)  # 全跑完但全錯 → 0.30
        self.assertAlmostEqual(hl.revision_reward(hl.Proposal("y", SEED, True), res0), 0.30)
        self.assertAlmostEqual(hl.revision_reward(hl.Proposal("y", None, True), None), 0.05)
        self.assertAlmostEqual(hl.revision_reward(hl.Proposal("y", None, False), None), 0.0)
        crash = hl.execute("def solve(m, q):\n    raise ValueError\n", TASK, qs, fake_solver)
        self.assertAlmostEqual(hl.revision_reward(hl.Proposal("y", "src", True), crash), 0.15)
        unload = hl.execute("def nope(): pass", TASK, qs, fake_solver)
        self.assertAlmostEqual(hl.revision_reward(hl.Proposal("y", "src", True), unload), 0.05)

    def test_grpo_advantages(self):
        self.assertEqual(hl.grpo_advantages([]), [])
        self.assertEqual(hl.grpo_advantages([1.0, 1.0, 1.0]), [0.0, 0.0, 0.0])
        adv = hl.grpo_advantages([0.0, 1.0])
        self.assertAlmostEqual(adv[0], -adv[1])
        self.assertAlmostEqual(sum(adv), 0.0)

    def test_collect_group(self):
        qs = questions(8, 0)
        g = hl.collect_group(TASK, SEED, qs[:4], qs[4:], make_fake_proposer(), fake_solver, group_size=3)
        self.assertEqual(len(g["responses"]), 3)
        self.assertAlmostEqual(g["rewards"][0], 0.05)  # 壞 SEARCH：parses 但套不上
        self.assertAlmostEqual(g["rewards"][1], 1.30)
        self.assertEqual(len(g["advantages"]), 3)
        self.assertIn("import re", g["best_harness"])
        self.assertIn("Execution report", g["prompt"])


if __name__ == "__main__":
    unittest.main()
