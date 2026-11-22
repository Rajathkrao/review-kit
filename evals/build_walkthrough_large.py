#!/usr/bin/env python3
"""Build a realistic, larger review package for checking the HTML page by eye.

    python3 evals/build_walkthrough_large.py OUT_DIR
    python3 skills/review-kit/scripts/render_html.py OUT_DIR/large-pkg --copy-to OUT_DIR

A 12-file Python change in a monorepo with a nested src/ layout (decision_evals/src/decision_evals/...),
one important and six minor findings with long titles, two dismissed candidates, an architecture
diagram, a sequence diagram and a walkthrough. This is the shape that exposed the cramped contents
rail and the unreadable module graph in v1.6.0.
"""
import json
import sys
from pathlib import Path

PKG = "decision_evals/src/decision_evals"
TESTS = "decision_evals/tests"

FILES = {
    f"{PKG}/__init__.py": "",
    f"{PKG}/metrics/__init__.py": "",
    f"{PKG}/metrics/core/__init__.py": "from decision_evals.metrics.core.topk import TopKMetric\n",
    f"{PKG}/metrics/core/base.py": '''"""Base class every metric implements."""
from dataclasses import dataclass


@dataclass
class MetricResult:
    name: str
    rows: list
    summary: dict


class Metric:
    name = "metric"

    def compute(self, input_data):
        raise NotImplementedError

    def write_to_csv(self, result, out_dir):
        raise NotImplementedError
''',
    f"{PKG}/metrics/core/shared.py": '''"""Helpers the ranking and top-k metrics both use."""
from collections import defaultdict


def group_by_case(units):
    groups = defaultdict(list)
    for unit in units:
        groups[unit.case_id].append(unit)
    return dict(groups)


def rank_of(returned, gold_id):
    """1-based rank of gold_id in the returned list, or None."""
    for i, item in enumerate(returned, 1):
        if item.unit_id == gold_id:
            return i
    return None


def small_sample_notes(n, threshold=20):
    if n < threshold:
        return [f"Only {n} cases: treat rates as rough."]
    return []
''',
    f"{PKG}/metrics/core/ranking.py": '''"""Mean reciprocal rank over graded gold units."""
from decision_evals.metrics.core.base import Metric, MetricResult
from decision_evals.metrics.core.shared import group_by_case, rank_of, small_sample_notes


class RankingMetric(Metric):
    name = "ranking"

    def compute(self, input_data):
        rows = []
        for case_id, units in group_by_case(input_data.units).items():
            ranks = [rank_of(input_data.returned[case_id], u.unit_id) for u in units if u.grade > 0]
            best = min((r for r in ranks if r), default=None)
            rows.append({"case": case_id, "mrr": 1 / best if best else 0.0})
        mean = sum(r["mrr"] for r in rows) / len(rows) if rows else 0.0
        return MetricResult(self.name, rows, {"mrr": mean, "notes": small_sample_notes(len(rows))})
''',
    f"{PKG}/metrics/core/topk.py": '''"""Score the first k items a tool returns for each case against graded gold."""
import csv
import json
from pathlib import Path

from decision_evals.metrics.core.base import Metric, MetricResult
from decision_evals.metrics.core.shared import group_by_case, rank_of


class TopKMetric(Metric):
    name = "topk"

    def __init__(self, k=5):
        self.k = k

    def compute(self, input_data):
        rows, misses = [], []
        for case_id, units in group_by_case(input_data.units).items():
            returned = input_data.returned.get(case_id, [])
            grades = [u for u in units if u.grade > 0]
            if not returned:
                continue
            top = returned[: self.k]
            in_top_k = [u for u in grades if rank_of(top, u.unit_id)]
            recall_at_k = len(in_top_k) / min(self.k, len(grades)) if grades else 0.0
            hit_at_1 = 1 if grades and rank_of(returned[:1], grades[0].unit_id) else 0
            rows.append({"case": case_id, "recall_at_k": recall_at_k, "hit_at_1": hit_at_1,
                         "returned_count": len(top)})
            if not hit_at_1:
                misses.append({"case": case_id, "miss_kind": "top_not_best",
                               "gold_note_top": grades[0].note if grades else ""})
        return MetricResult(self.name, rows, self._summary(rows, misses))

    def _summary(self, rows, misses):
        n = len(rows)
        return {
            "shape": "topk",
            "k": self.k,
            "recall_at_k": sum(r["recall_at_k"] for r in rows) / n if n else 0.0,
            "hit_at_1": sum(r["hit_at_1"] for r in rows) / n if n else 0.0,
            "misses": misses,
            "notes": self._top_k_small_sample_notes(n),
        }

    def _top_k_small_sample_notes(self, n, threshold=20):
        if n < threshold:
            return [f"Only {n} cases: treat rates as rough."]
        return []

    def write_to_csv(self, result, out_dir):
        out = Path(out_dir)
        with open(out / "topk.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["case", "recall_at_k", "hit_at_1", "returned_count"])
            w.writeheader()
            w.writerows(result.rows)
        (out / "topk_summary.json").write_text(json.dumps(result.summary, indent=2))
        with open(out / "topk_misses.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["case", "miss_kind", "gold_note_top"])
            w.writeheader()
            w.writerows(result.summary["misses"])
''',
    f"{PKG}/units.py": '''"""ScenarioUnits: what an adapter hands the engine for one record."""
from dataclasses import dataclass, field


@dataclass
class Unit:
    case_id: str
    unit_id: str
    grade: int = 0
    note: str = ""


@dataclass
class ScenarioUnits:
    units: list = field(default_factory=list)
    returned: dict = field(default_factory=dict)
    unanswered: int = 0
''',
    f"{PKG}/run_files.py": '''"""Where each metric writes its files."""
from pathlib import Path

FILES = {
    "ranking": ["ranking.csv"],
    "topk": ["topk.csv", "topk_summary.json", "topk_misses.csv"],
}


def evaluation_dir(run_dir):
    out = Path(run_dir) / "evaluations"
    out.mkdir(parents=True, exist_ok=True)
    return out
''',
    f"{PKG}/postprocess/__init__.py": "",
    f"{PKG}/postprocess/summary.py": '''"""Read every metric summary and write the report."""
import json

from decision_evals.postprocess.renderers import RENDERERS
from decision_evals.run_files import FILES, evaluation_dir


def summarise(run_dir):
    out = evaluation_dir(run_dir)
    sections = []
    for name in FILES:
        path = out / f"{name}_summary.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        sections.append(RENDERERS[data.get("shape", name)](data))
    return "\\n\\n".join(sections)
''',
    f"{PKG}/postprocess/renderers.py": '''"""Turn one metric summary into report text."""


def render_ranking(data):
    return f"MRR {data['mrr']:.2f}"


def render_topk(data):
    lines = [f"Top-{data['k']} quality", f"recall@k {data['recall_at_k']:.0%}", f"hit@1 {data['hit_at_1']:.0%}"]
    lines += data.get("notes", [])
    return "\\n".join(lines)


FILES_SECTION = {
    "topk.csv": "One row per scenario",
    "topk_misses.csv": "Cases where the best gold unit was not ranked first",
}

RENDERERS = {"ranking": render_ranking, "topk": render_topk}
''',
    f"{PKG}/adapters/__init__.py": "",
    f"{PKG}/adapters/search.py": '''"""Adapter for the search tool: turns API responses into ScenarioUnits."""
from decision_evals.units import ScenarioUnits, Unit


def to_units(records):
    su = ScenarioUnits()
    for rec in records:
        if not rec.get("results"):
            su.unanswered += 1
            continue
        su.returned[rec["id"]] = [Unit(rec["id"], r["id"]) for r in rec["results"]]
    return su
''',
    f"{TESTS}/metrics/test_core_topk.py": '''from decision_evals.metrics.core.topk import TopKMetric
from decision_evals.units import ScenarioUnits, Unit


def test_recall_full_hit():
    su = ScenarioUnits(units=[Unit("c1", "a", 2)], returned={"c1": [Unit("c1", "a")]})
    res = TopKMetric(k=3).compute(su)
    assert res.rows[0]["recall_at_k"] == 1.0
''',
    f"{TESTS}/metrics/test_topk_metric.py": '''from decision_evals.metrics.core.topk import TopKMetric


def test_name():
    assert TopKMetric().name == "topk"
''',
    f"{TESTS}/test_summary_postprocessor.py": '''from decision_evals.postprocess.summary import summarise


def test_empty(tmp_path):
    assert summarise(tmp_path) == ""
''',
    f"{TESTS}/test_units.py": '''from decision_evals.units import ScenarioUnits


def test_defaults():
    assert ScenarioUnits().unanswered == 0
''',
}

CHANGED = {  # path -> (status, added, deleted)
    f"{PKG}/metrics/core/topk.py": ("added", 72, 0),
    f"{PKG}/metrics/core/shared.py": ("added", 24, 0),
    f"{PKG}/metrics/core/ranking.py": ("modified", 6, 21),
    f"{PKG}/metrics/core/__init__.py": ("modified", 1, 0),
    f"{PKG}/units.py": ("modified", 3, 1),
    f"{PKG}/run_files.py": ("modified", 1, 0),
    f"{PKG}/postprocess/summary.py": ("modified", 4, 2),
    f"{PKG}/postprocess/renderers.py": ("modified", 14, 3),
    f"{TESTS}/metrics/test_core_topk.py": ("added", 412, 0),
    f"{TESTS}/metrics/test_topk_metric.py": ("added", 388, 0),
    f"{TESTS}/test_summary_postprocessor.py": ("modified", 296, 25),
    f"{TESTS}/test_units.py": ("modified", 236, 0),
}


def diff_for(path, text, status):
    lines = text.rstrip("\n").split("\n")
    head = f"diff --git a/{path} b/{path}\n" + ("new file mode 100644\n--- /dev/null\n" if status == "added" else f"--- a/{path}\n")
    body = "\n".join(f"{i:6d} {'+' if status == 'added' or i % 3 == 0 else ' '}{l}" for i, l in enumerate(lines, 1))
    return f"{head}+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}\n"


def finding(fid, title, file, a, b, sev, rec, conf=85):
    return dict(id=fid, title=title, body=title + ".", file=file, line_start=a, line_end=b, severity=sev,
                confidence=conf, recommendation=rec, evidence=f"Read {file} at the reviewed commit.",
                evidence_status="source-verified", lenses=["correctness", "python"])


TOPK = f"{PKG}/metrics/core/topk.py"
FINDINGS = [
    finding("F1", "recall@k can exceed 1 when several gold units share a rank", TOPK, 24, 25, "important",
            "Cap the numerator: ideal = min(k, len(grades)); recall_at_k = min(len(in_top_k), ideal) / ideal, and add a shared-rank test.", 92),
    finding("F2", "An unanswered record with no units vanishes instead of being counted as unanswered", TOPK, 21, 22, "minor",
            "Count a case with no returned items as unanswered and add it to the summary instead of skipping it."),
    finding("F3", "The report's Files section describes topk.csv as 'One row per scenario' but it has one row per case",
            f"{PKG}/postprocess/renderers.py", 14, 15, "minor", "Say 'One row per case (group)'."),
    finding("F4", "gold_note_top is not cut to 300 characters in the misses CSV", TOPK, 30, 31, "minor",
            "Truncate gold_note_top to 300 characters like the other CSV text columns."),
    finding("F5", "A returned item whose gold match is ranked earlier disappears from returned_count and unmatched_share", TOPK, 27, 28, "minor",
            "Count every returned item in returned_count, matched or not."),
    finding("F6", "_top_k_small_sample_notes duplicates shared.small_sample_notes", TOPK, 45, 48, "minor",
            "Call shared.small_sample_notes and delete the method."),
    finding("F7", "The new files never went through pre-commit (ruff format and the import sorter)", TOPK, 1, 6, "minor",
            "Run pre-commit run --files on the new modules."),
]

ARCH = {
    "caption": "The engine runs every metric over the adapter's ScenarioUnits, writes their files, then the summary step renders each summary by its shape.",
    "nodes": [
        {"id": "eng", "label": "Evaluation engine", "kind": "job"},
        {"id": "adp", "label": "Search adapter", "kind": "request", "file": f"{PKG}/adapters/search.py"},
        {"id": "topk", "label": "TopKMetric", "kind": "logic", "file": TOPK, "changed": True, "finding_ids": ["F1", "F2", "F4"]},
        {"id": "rank", "label": "RankingMetric", "kind": "logic", "file": f"{PKG}/metrics/core/ranking.py", "changed": True},
        {"id": "shared", "label": "shared helpers", "kind": "logic", "file": f"{PKG}/metrics/core/shared.py", "changed": True},
        {"id": "files", "label": "evaluations/ folder", "kind": "data"},
        {"id": "sum", "label": "Summary postprocessor", "kind": "job", "file": f"{PKG}/postprocess/summary.py", "changed": True, "finding_ids": ["F3"]},
    ],
    "edges": [
        {"from": "eng", "to": "adp", "label": "to_units"},
        {"from": "eng", "to": "topk", "label": "compute"},
        {"from": "eng", "to": "rank", "label": "compute"},
        {"from": "topk", "to": "shared", "label": "rank_of"},
        {"from": "rank", "to": "shared", "label": "rank_of"},
        {"from": "topk", "to": "files", "label": "write_to_csv"},
        {"from": "sum", "to": "files", "label": "read summaries"},
    ],
}

SEQ = {
    "title": "One evaluation run with the top-k metric",
    "actors": ["Engine", "TopKMetric", "evaluations/", "Summary"],
    "messages": [
        {"from": "Engine", "to": "TopKMetric", "label": "compute(input_data)"},
        {"from": "TopKMetric", "to": "TopKMetric", "label": "group_by_case, rank_of per gold unit"},
        {"from": "TopKMetric", "to": "TopKMetric", "label": "recall_at_k = in_top_k / min(k, grades)", "finding_id": "F1"},
        {"from": "TopKMetric", "to": "Engine", "label": "MetricResult(rows, summary)", "kind": "return"},
        {"from": "Engine", "to": "TopKMetric", "label": "status scored; hit@1 == 0 -> misses row, miss_kind top_not_best", "kind": "note"},
        {"from": "Engine", "to": "evaluations/", "label": "write_to_csv(results, evaluations/)"},
        {"from": "evaluations/", "to": "Summary", "label": "topk_summary.json (shape topk), topk_misses.csv", "kind": "async"},
        {"from": "Summary", "to": "Summary", "label": "RENDERERS[\"topk\"] -> Quality table + Summary sentence", "kind": "note"},
    ],
}

STEPS = [
    {"title": "Group the units by case and keep the graded gold", "kind": "logic", "file": TOPK, "lines": [16, 22],
     "explanation": "`compute` walks each case (one record from the adapter). Gold units are the ones with a grade above zero; cases where the tool returned nothing are skipped.",
     "finding_ids": ["F2"]},
    {"title": "Score the first k returned items", "kind": "logic", "file": TOPK, "lines": [23, 31],
     "explanation": "Recall@k counts gold units found in the top k and divides by the most it could find, `min(k, len(grades))`. Hit@1 checks whether the best gold unit came first.",
     "notes": [{"line": 25, "text": "Several gold units can match the same returned item, so the numerator can exceed the denominator."}],
     "finding_ids": ["F1", "F4", "F5"]},
    {"title": "Summarise and write three files", "kind": "data", "file": TOPK, "lines": [34, 60],
     "explanation": "The summary carries `shape: topk` so the postprocessor can pick its renderer. `write_to_csv` writes per-case rows, the summary JSON and the misses CSV.",
     "finding_ids": ["F6"]},
    {"title": "Render the top-k section in the report", "kind": "job", "file": f"{PKG}/postprocess/renderers.py", "lines": [8, 18],
     "explanation": "`render_topk` turns the summary into the Top-k quality block; `FILES_SECTION` describes each output file in the report.",
     "finding_ids": ["F3"]},
]

PROBLEMS = {
    "F1": {"pin_line": 25, "line_note": "len(in_top_k) counts gold units, not returned slots: two gold units on one passage both count.",
           "summary": "When two gold paragraphs map to the same returned passage, both count as found, so `len(in_top_k)` can be larger than `min(k, len(grades))` and recall@k comes out above 100%. The adapter contract explicitly allows several gold units per passage, so this happens on real data.",
           "scenario": ["Case c7 has three gold units a, b and c; a and b live in passage P1.", "The tool returns [P1, P9] and k = 1.", "top = [P1]; rank_of finds both a and b in it, so in_top_k has 2 units.", "recall_at_k = 2 / min(1, 3) = 2.0.", "The report shows recall@1 of 200% for c7 and lifts the average."],
           "failure_step": 4,
           "root_cause": "The numerator counts gold units while the denominator counts slots. They only agree when every returned item matches at most one gold unit, which the adapter contract does not promise. The ranking metric avoids this because it only uses the best rank.",
           "impact": "Any case with shared passages inflates recall@k, and the average can exceed 1. Teams comparing tools will trust the wrong one, and the misses file will not explain it.",
           "fix": {"explanation": "Cap the numerator at the ideal count and add a shared-rank test.", "file": TOPK,
                   "patch": "-            recall_at_k = len(in_top_k) / min(self.k, len(grades)) if grades else 0.0\n+            ideal = min(self.k, len(grades))\n+            recall_at_k = min(len(in_top_k), ideal) / ideal if grades else 0.0"},
           "test": {"name": "tests/metrics/test_core_topk.py::test_shared_rank_caps_recall", "explanation": "Fails today (2.0), passes after the fix (1.0).",
                    "code": "def test_shared_rank_caps_recall():\n    su = ScenarioUnits(units=[Unit('c7', 'P1', 2), Unit('c7', 'P1', 1), Unit('c7', 'P3', 1)],\n                       returned={'c7': [Unit('c7', 'P1'), Unit('c7', 'P9')]})\n    assert TopKMetric(k=1).compute(su).rows[0]['recall_at_k'] == 1.0"}},
    "F2": {"pin_line": 22, "line_note": "Skipped silently: the case never reaches rows or the unanswered count.",
           "summary": "A case where the tool returned nothing is skipped with `continue`, so it is neither scored as a miss nor counted as unanswered. The denominators shrink and the tool looks better than it is.",
           "scenario": ["The adapter returns 100 cases; 10 have no results.", "compute skips those 10.", "recall@k is averaged over 90 cases."],
           "root_cause": "The early `continue` was meant to avoid dividing by zero on empty lists, but it also removes the case from every count.",
           "impact": "Tools that fail to answer look better than tools that answer badly.",
           "fix": {"explanation": "Score an empty case as zero and count it as unanswered.", "file": TOPK,
                   "patch": "             if not returned:\n-                continue\n+                rows.append({\"case\": case_id, \"recall_at_k\": 0.0, \"hit_at_1\": 0, \"returned_count\": 0})\n+                continue"}},
}


def build(out: Path):
    src = out / "repo"
    for p, t in FILES.items():
        (src / p).parent.mkdir(parents=True, exist_ok=True)
        (src / p).write_text(t)
    diff = "".join(diff_for(p, FILES[p], CHANGED[p][0]) for p in CHANGED)
    meta = dict(repo="ras-search_decisions-tools", description="branch feature/2428983-topk-metric vs 272c9db123 + uncommitted",
                collection_status="completed", repo_root=str(src), reviewed_commit="1c8fd01e4b1c0a9f8e7d6c5b4a3928170f6e5aa",
                base="272c9db123", branch="feature/2428983-topk-metric", added=1457, deleted=52, rk_version="dev",
                files=[{"path": p, "status": s, "added": a, "deleted": d} for p, (s, a, d) in CHANGED.items()],
                risk=["metrics", "report"])
    explainer = dict(title="Generic top-k metric for decision_evals",
                     one_liner="Adds `TopKMetric`, which scores the first k items a tool returns for each group (case) against graded gold, writes topk.csv, topk_summary.json and topk_misses.csv, and gives the report a top-k quality section. Helpers the ranking and top-k metrics both use move into metrics/shared.py.",
                     why="From the ticket 2428983: search teams want one metric that works for any tool that returns a ranked list, instead of a bespoke script per tool.",
                     before="Only mean reciprocal rank was computed, inside ranking.py, with its own copies of the grouping and rank helpers.",
                     after="TopKMetric runs alongside RankingMetric. Both use shared.py. The summary step picks a renderer by the summary's `shape`, so new metrics only add a renderer.",
                     entry_point="TopKMetric.compute(input_data), called by the evaluation engine with one ScenarioUnits per record",
                     architecture=ARCH, sequences=[SEQ], steps=STEPS, problems=PROBLEMS,
                     key_concepts=[{"term": "recall@k", "meaning": "Share of the gold units that appear in the first k returned items, out of the most that could."},
                                   {"term": "hit@1", "meaning": "1 when the best gold unit is the first returned item."}],
                     try_it_yourself=["Run the metric on a case where two gold units share one passage: recall@k should stay at or below 1."],
                     changed_files=[{"path": f"{PKG}/metrics/core/shared.py", "role": "Rank and grouping helpers both metrics use", "change": "new", "order": 1},
                                    {"path": TOPK, "role": "The new metric", "change": "new", "order": 2},
                                    {"path": f"{PKG}/metrics/core/ranking.py", "role": "Now uses shared helpers", "change": "modified", "order": 3},
                                    {"path": f"{PKG}/postprocess/renderers.py", "role": "Top-k report section", "change": "modified", "order": 4}])
    review = dict(mode="deep", execution_status="completed", verdict="ship-after-fixes",
                  summary="One Important bug: recall@k can exceed 100% when several gold paragraphs share a returned passage, which the adapter contract allows. The rest are small: report text, a duplicated note helper, an uncut note, unanswered-record counting, and new files that skipped pre-commit.",
                  findings=FINDINGS,
                  plausible=[{"title": "hit@1 uses grades[0], which is the first gold unit, not the best graded", "file": TOPK, "line_start": 26,
                              "check": "Whether adapters always sort units by grade; if they do, this is fine."}],
                  dropped=[{"title": "Division by zero when k = 0", "confidence": 30, "reason": "The constructor is only called with k from config, which validates k >= 1."},
                           {"title": "CSV files opened without encoding", "confidence": 25, "reason": "The project pins UTF-8 mode in its runner."}])
    pkg = out / "large-pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "meta.json").write_text(json.dumps(meta, indent=1))
    (pkg / "diff-numbered.txt").write_text(diff)
    (pkg / "findings.json").write_text(json.dumps(review, indent=1))
    (pkg / "explainer.json").write_text(json.dumps(explainer, indent=1))
    return pkg


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(build(Path(sys.argv[1])))
