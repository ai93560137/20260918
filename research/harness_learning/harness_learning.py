"""Harness learning: core loop (after Zhang et al., arXiv:2609.35738).

A *harness* is Python source defining `solve(model, question) -> answer`.
A *proposer* LLM reads (task description, current harness, execution report)
and emits SEARCH/REPLACE edits. Revised harnesses are executed with a frozen
*solver* LLM, scored, and one is retained. Both models are plain callables
`str -> str`, so any backend can be plugged in.

Covers: Eq.3 (harness score), Eq.4 (propose / Apply / Select), Eq.7 (keep only
if improved), Eq.6/8 (RL reward), and GRPO group-normalised advantages.
The policy-gradient update itself is left to your trainer.

WARNING: harness code is model-generated and run with exec(). Run this inside
a sandbox (container / subprocess with limits), not on a machine you care about.
"""
from __future__ import annotations

import ast
import random
import re
import signal
import statistics
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

LLM = Callable[[str], str]
ENTRY_POINT = "solve"
NO_CHANGE = "NO_CHANGE"

SEED_HARNESS = '''\
def solve(model, question):
    return model(question).strip()
'''


# ---------------------------------------------------------------- task data
@dataclass
class Question:
    text: str
    answer: Any


@dataclass
class Task:
    description: str
    grader: Callable[[Any, Any], float]  # (prediction, gold) -> score in [0, 1]


def exact_match(pred: Any, gold: Any) -> float:
    def norm(s: Any) -> str:
        s = re.sub(r"[^\w\s]", "", str(s).lower())
        s = re.sub(r"\b(a|an|the)\b", " ", s)
        return " ".join(s.split())
    return float(norm(pred) == norm(gold))


# ---------------------------------------------------------------- execution
class TracedModel:
    """Wraps the solver so each question's calls are recorded and budgeted."""

    def __init__(self, solver: LLM, max_calls: int = 12):
        self.solver, self.max_calls, self.calls = solver, max_calls, []

    def __call__(self, prompt: str) -> str:
        if len(self.calls) >= self.max_calls:
            raise RuntimeError("solver call budget exceeded")
        out = self.solver(prompt)
        self.calls.append((prompt, out))
        return out


@dataclass
class Record:
    question: Question
    prediction: Any
    score: float
    error: Optional[str]
    calls: list


@dataclass
class ExecResult:
    records: list[Record] = field(default_factory=list)
    load_error: Optional[str] = None

    @property
    def runnable(self) -> bool:
        return self.load_error is None

    @property
    def score(self) -> float:  # Eq. 3: J(h; Q)
        return statistics.fmean(r.score for r in self.records) if self.records else 0.0

    @property
    def completed_fraction(self) -> float:
        if not self.records:
            return 0.0
        return sum(r.error is None for r in self.records) / len(self.records)


class HarnessTimeout(Exception):
    pass


class _Alarm:
    """Optional per-question wall-clock limit via signal.setitimer.
    Only works on Unix in the main thread; elsewhere it is a no-op."""

    def __init__(self, seconds: Optional[float]):
        self.seconds, self.active = seconds, False

    def __enter__(self):
        if self.seconds and hasattr(signal, "SIGALRM"):
            try:
                signal.signal(signal.SIGALRM, self._raise)
                signal.setitimer(signal.ITIMER_REAL, self.seconds)
                self.active = True
            except (ValueError, OSError):  # not in main thread
                self.active = False
        return self

    def __exit__(self, *exc):
        if self.active:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, signal.SIG_DFL)
        return False

    @staticmethod
    def _raise(signum, frame):
        raise HarnessTimeout("harness exceeded time limit")


def load_harness(source: str) -> Callable:
    ns: dict = {}
    exec(compile(source, "<harness>", "exec"), ns)
    fn = ns.get(ENTRY_POINT)
    if not callable(fn):
        raise ValueError(f"harness must define {ENTRY_POINT}(model, question)")
    return fn


def execute(source: str, task: Task, questions: Sequence[Question],
            solver: LLM, max_calls: int = 12,
            timeout: Optional[float] = None) -> ExecResult:
    """Run `source` on `questions` with the frozen solver. `timeout` is a
    per-question wall-clock limit in seconds (Unix main thread only)."""
    try:
        fn = load_harness(source)
    except Exception:
        return ExecResult(load_error=traceback.format_exc(limit=2))
    result = ExecResult()
    for q in questions:
        model = TracedModel(solver, max_calls)
        try:
            with _Alarm(timeout):
                pred, err = fn(model, q.text), None
            score = float(task.grader(pred, q.answer))
        except Exception as e:  # a crashing / timed-out question counts as incorrect
            pred, err, score = None, f"{type(e).__name__}: {e}", 0.0
        result.records.append(Record(q, pred, score, err, model.calls))
    return result


def build_report(result: ExecResult, max_failures: int = 8, clip: int = 400) -> str:
    if not result.runnable:
        return f"Harness failed to load:\n{result.load_error}"
    n = len(result.records)
    fails = [r for r in result.records if r.score < 1.0]
    lines = [f"Score: {result.score:.3f} on {n} questions "
             f"({n - len(fails)} correct, {len(fails)} failed, "
             f"{sum(r.error is not None for r in result.records)} crashed)."]
    for r in fails[:max_failures]:
        lines.append(f"\n--- FAILED ---\nQuestion: {r.question.text[:clip]}"
                     f"\nHarness answer: {r.prediction!r}\nExpected: {r.question.answer!r}")
        if r.error:
            lines.append(f"Error: {r.error}")
        for i, (p, o) in enumerate(r.calls, 1):
            lines.append(f"[call {i}] prompt: {p[:clip]!r}\n[call {i}] output: {o[:clip]!r}")
    return "\n".join(lines)


# ------------------------------------------------------------------- edits
EDIT_RE = re.compile(
    r"<<<<<<< SEARCH\n(.*?)\n?=======\n(.*?)\n?>>>>>>> REPLACE", re.DOTALL)


class EditError(Exception):
    pass


def parses(response: str) -> bool:
    """1[y parses] in Eq. 8: the response carries edit blocks or NO_CHANGE."""
    return bool(EDIT_RE.search(response)) or NO_CHANGE in response


def _find_span(src: str, search: str) -> tuple[int, int]:
    """Locate `search` in `src`, accepting only matches aligned to line
    boundaries (a partial-line hit would splice indentation and corrupt code)."""
    if not search.strip():
        raise EditError("SEARCH text is empty")
    hits, start = [], 0
    while (i := src.find(search, start)) >= 0:
        j = i + len(search)
        if (i == 0 or src[i - 1] == "\n") and (j == len(src) or src[j] == "\n"):
            hits.append((i, j))
        start = i + 1
    if len(hits) != 1:
        raise EditError(f"SEARCH text must match exactly once "
                        f"(found {len(hits)}):\n{search[:200]}")
    return hits[0]


def apply_edits(parent: str, response: str) -> str:
    """Apply(h, y). Returns revised source (== parent for an explicit no-change)."""
    edits = EDIT_RE.findall(response)
    if not edits:
        if NO_CHANGE in response:
            return parent
        raise EditError("no SEARCH/REPLACE block found")
    src = parent
    for search, replace in edits:
        i, j = _find_span(src, search)
        src = src[:i] + replace + src[j:]
    try:
        ast.parse(src)
    except SyntaxError as e:
        raise EditError(f"revised harness does not parse: {e}")
    return src


PROMPT = """\
You revise the harness of a fixed solver model. The harness is Python defining
`{entry}(model, question)`; `model(prompt)` calls the solver and returns text.

## Task
{task}

## Current harness (development score {score:.3f})
```python
{harness}
```

## Execution report
{report}

Diagnose the failures, then make a targeted change. Do not hard-code answers;
keep the `{entry}` entry point. Reply with one or more edits in this format:

<<<<<<< SEARCH
exact existing lines
=======
replacement lines
>>>>>>> REPLACE

If no change is warranted, reply with {no_change}.
"""


def build_prompt(task: Task, harness: str, result: ExecResult) -> str:
    return PROMPT.format(entry=ENTRY_POINT, task=task.description, harness=harness,
                         score=result.score, report=build_report(result),
                         no_change=NO_CHANGE)


@dataclass
class Proposal:
    response: str
    source: Optional[str]  # None = failed edit
    parsed: bool  # 1[y parses]: well-formed edit blocks / NO_CHANGE, even if not applicable


def propose(proposer: LLM, prompt: str, parent: str, max_attempts: int = 3) -> Proposal:
    """Sample one revision; a rejected edit gets error feedback and a retry."""
    p, response = prompt, ""
    for _ in range(max_attempts):
        response = proposer(p)
        try:
            return Proposal(response, apply_edits(parent, response), True)
        except EditError as e:
            p = f"{prompt}\n\nYour previous edit was rejected: {e}\nTry again."
    return Proposal(response, None, parses(response))


# ------------------------------------------------------ test-time adaptation
@dataclass
class Round:
    harness: str
    dev_score: float
    candidate_scores: list[float]


def adapt(task: Task, dev: Sequence[Question], proposer: LLM, solver: LLM, *,
          seed: str = SEED_HARNESS, rounds: int = 5, candidates: int = 1,
          select: str = "improve_only", n_feedback: Optional[int] = None,
          n_score: Optional[int] = None, rng: Optional[random.Random] = None,
          max_calls: int = 12, timeout: Optional[float] = None,
          ) -> tuple[str, list[Round]]:
    """Inner loop (Eq. 4): h_0 -> h_T with proposer and solver both frozen.

    select="improve_only": keep a candidate only if it beats the current
        harness on the scoring set (Eq. 7; Reasoning Gym protocol, G=1,
        feedback and scoring share the dev set).
    select="best_of_g":   advance to the top-scoring candidate even if it is
        worse than its parent; stay put only if every candidate fails
        (QA protocol, G=8, disjoint feedback/scoring draws each round).
    n_feedback / n_score: if given, sample disjoint subsets of `dev` per round.
    max_calls / timeout: per-question solver-call budget and wall-clock limit.
    """
    run = dict(max_calls=max_calls, timeout=timeout)
    rng = rng or random.Random(0)
    current, history = seed, []
    for _ in range(rounds):
        if n_feedback and n_score:
            pool = rng.sample(list(dev), n_feedback + n_score)
            q_fb, q_score = pool[:n_feedback], pool[n_feedback:]
        else:
            q_fb = q_score = list(dev)

        parent_fb = execute(current, task, q_fb, solver, **run)
        prompt = build_prompt(task, current, parent_fb)
        parent_score = (parent_fb.score if q_fb is q_score
                        else execute(current, task, q_score, solver, **run).score)

        scored: list[tuple[float, str]] = []  # runnable candidates only
        all_scores: list[float] = []
        for _ in range(candidates):
            prop = propose(proposer, prompt, current)
            res = execute(prop.source, task, q_score, solver, **run) if prop.source else None
            if res is not None and res.runnable:
                scored.append((res.score, prop.source))
                all_scores.append(res.score)
            else:
                all_scores.append(0.0)  # failed edit / unloadable harness

        if scored:
            best_score, best_src = max(scored, key=lambda t: t[0])
            if select == "improve_only":
                if best_score > parent_score:
                    current, parent_score = best_src, best_score
            elif select == "best_of_g":
                current, parent_score = best_src, best_score
            else:
                raise ValueError(select)
        history.append(Round(current, parent_score, all_scores))
    return current, history


def evaluate(source: str, task: Task, held_out: Sequence[Question], solver: LLM,
             max_calls: int = 12, timeout: Optional[float] = None) -> float:
    """J(h_T; Q_eval). Held-out questions must never appear in feedback/scoring."""
    return execute(source, task, held_out, solver, max_calls, timeout).score


# ------------------------------------------------------------- RL (outer loop)
def revision_reward(prop: Proposal, result: Optional[ExecResult]) -> float:
    """Eq. 6 with the Reasoning Gym validity terms of Eq. 8:
    r = J(h'; Q_score) + 0.05[parses] + 0.10[applies & loads] + 0.15*completed.
    A failed edit keeps only the credit accrued before the failure."""
    r = 0.05 if prop.parsed else 0.0
    if prop.source is None or result is None or not result.runnable:
        return r
    return r + 0.10 + 0.15 * result.completed_fraction + result.score


def grpo_advantages(rewards: Sequence[float], delta: float = 1e-6) -> list[float]:
    """Group-normalised advantage, shared by every token of response i."""
    if not rewards:
        return []
    mean, std = statistics.fmean(rewards), statistics.pstdev(rewards)
    return [(r - mean) / (std + delta) for r in rewards]


def collect_group(task: Task, parent: str, q_fb: Sequence[Question],
                  q_score: Sequence[Question], proposer: LLM, solver: LLM,
                  group_size: int = 8, max_calls: int = 12,
                  timeout: Optional[float] = None) -> dict:
    """One RL context: sample G revisions of `parent`, score them on a common
    scoring set disjoint from the feedback set, return what a GRPO step needs.
    For multistep training, feed `best_harness` back in as the next parent
    with fresh feedback questions."""
    run = dict(max_calls=max_calls, timeout=timeout)
    prompt = build_prompt(task, parent, execute(parent, task, q_fb, solver, **run))
    props, results = [], []
    for _ in range(group_size):
        prop = propose(proposer, prompt, parent, max_attempts=1)
        res = execute(prop.source, task, q_score, solver, **run) if prop.source else None
        props.append(prop)
        results.append(res)
    rewards = [revision_reward(p, r) for p, r in zip(props, results)]
    valid = [(r.score, p.source) for p, r in zip(props, results) if r and r.runnable]
    return {
        "prompt": prompt,
        "responses": [p.response for p in props],
        "rewards": rewards,
        "advantages": grpo_advantages(rewards),
        "best_harness": max(valid, key=lambda t: t[0])[1] if valid else parent,
    }
