"""Offline behavior measurements against pinned project sources.

Install numpy, pandas and faiss-cpu in an isolated environment, then run:
  python scripts/measure_project_behavior.py --source-root /tmp/SOURCE_ROOT

SOURCE_ROOT contains Git checkouts named lxp, jeju, stayview, nohuae.
No model pickle, Streamlit application, external LLM or production DB is executed.
Selected reviewed Python functions/statements run unchanged via their AST.
"""

import argparse
import ast
import collections
import itertools
import json
import os
import platform
import re
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import faiss
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
from audit_project_metrics import REVISIONS


def read(path):
    return path.read_text(encoding="utf-8-sig")


def source_functions(path, names, namespace):
    tree = ast.parse(read(path))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    for node in nodes:
        node.decorator_list = []  # Do not initialize Streamlit caching/UI.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def timing_summary(samples):
    return {"samples": len(samples), "p50_ms": round(float(np.percentile(samples, 50)), 4),
            "p95_ms": round(float(np.percentile(samples, 95)), 4)}


def junit_results(root):
    suites = []
    for path in sorted((root / "lxp/build/test-results/test").glob("TEST-*.xml")):
        element = ET.parse(path).getroot()
        if not element.attrib["name"].startswith("com.ssa.lms.ai."):
            continue
        suite = {k: element.attrib[k] for k in ["name", "tests", "failures", "errors", "skipped"]}
        for key in ["tests", "failures", "errors", "skipped"]:
            suite[key] = int(suite[key])
        suite["cases"] = [{"name": case.attrib["name"],
                           "passed": not any(case.find(k) is not None for k in ["failure", "error", "skipped"])}
                          for case in element.findall("testcase")]
        suites.append(suite)
    assert len(suites) == 6 and sum(s["tests"] for s in suites) == 39, (
        "Run exactly the six documented LXP test classes before collecting measurements."
    )
    return {"suites": suites, "totals": {k: sum(s[k] for s in suites)
            for k in ["tests", "failures", "errors", "skipped"]},
            "scope": "Six existing unit-test classes only; DB integration tests excluded."}


def measure_jeju(root):
    folder = root / "jeju"
    vectors = np.load(folder / "modules/embeddings_array_file_1.npy", allow_pickle=False)
    namespace = source_functions(folder / "app.py", ["load_faiss_index"],
                                 {"os": os, "faiss": faiss, "module_path": str(folder / "modules")})
    loader = namespace["load_faiss_index"]
    store = loader()
    tour_path = str(folder / "modules/faiss_tour_index_1.index")
    tour = loader(index_path=tour_path)
    assert vectors.shape == (store.ntotal, store.d) == (9346, 768)
    assert (tour.ntotal, tour.d) == (381, 768)
    ids = np.random.default_rng(20260915).choice(len(vectors), 200, replace=False)
    max_delta = max(float(np.max(np.abs(store.reconstruct(int(i)) - vectors[i]))) for i in ids)
    queries = [np.ascontiguousarray(vectors[i:i+1], dtype="float32") for i in ids]
    for q in queries[:20]:
        store.search(q, 9)
        tour.search(q, 1)
    memory_ms, loading_ms = [], []
    for q in queries:
        start = time.perf_counter_ns()
        store.search(q, 9)
        tour.search(q, 1)
        memory_ms.append((time.perf_counter_ns() - start) / 1e6)
        start = time.perf_counter_ns()
        s, t = loader(), loader(index_path=tour_path)
        s.search(q, 9)
        t.search(q, 1)
        loading_ms.append((time.perf_counter_ns() - start) / 1e6)

    # Execute the actual response function with controlled retrieval and a local LLM stub.
    class FixtureIndex:
        def __init__(self, tourist=False):
            self.tourist = tourist

        def search(self, query, k):
            return np.zeros((1, k)), np.array([[0] if self.tourist else list(range(k))])

    prices = [1, 2, 3, 4, 5, 6, 3, 4, 1]
    frame = pd.DataFrame({"건당평균이용금액구간": [str(p) for p in prices],
                          "text": [f"STORE{i}" for i in range(len(prices))]})
    ns = {"os": os, "module_path": "/fixture", "embed_text": lambda _: np.zeros(768),
          "load_faiss_index": lambda index_path="": FixtureIndex("tour" in index_path)}
    source_functions(folder / "app.py", ["generate_response_with_faiss"], ns)
    model = SimpleNamespace(generate_content=lambda prompt: SimpleNamespace(text=prompt))
    cases = []
    for label, allowed in [("상관 없음", {1, 2, 3, 4, 5, 6}), ("최고가", {6}),
                           ("고가", {5}), ("평균 가격대", {3, 4}), ("저가", {2}), ("최저가", {1})]:
        ns["price"] = label
        actual = ns["generate_response_with_faiss"]("가격대 검사", frame, None, model,
                    pd.DataFrame({"text": ["TOUR"]}), None, print_prompt=False)
        found = sorted({int(i) for i in re.findall(r"STORE(\d+)", actual)})
        expected = [i for i, price in enumerate(prices) if price in allowed]
        cases.append({"price": label, "expected_rows": expected, "actual_rows": found,
                      "passed": found == expected})
    return {"index_type": type(store).__name__, "store_vectors": store.ntotal,
            "tour_vectors": tour.ntotal, "dimensions": store.d,
            "sampled_vector_to_index_max_absolute_delta": max_delta,
            "search_in_memory": timing_summary(memory_ms),
            "index_load_plus_search": timing_summary(loading_ms),
            "price_filter_tests": cases,
            "scope": "200 stored-vector queries; 20 warmups; 1 FAISS thread; store k=9 + tour k=1. "
                     "Loading uses warm OS file cache. Excludes text embedding, price filtering, LLM and network. "
                     "Not natural-language relevance/accuracy or end-to-end response latency."}


def measure_stayview(root):
    folder = root / "stayview"
    df = pd.read_csv(folder / "hotel_fin_0331_2.csv", encoding="euc-kr")
    tree = ast.parse(read(folder / "streamlit_hotel_viewer_with_fonts.py"))
    names = {"sorted_hotels", "top_hotels"}
    nodes = [n for n in tree.body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
    assert len(nodes) == 2
    operation = compile(ast.Module(body=nodes, type_ignores=[]), "stayview-original-ranking", "exec")
    aspects = ["소음", "가격", "위치", "서비스", "청결", "편의시설"]
    cases = []
    for region, aspect in itertools.product(sorted(df.Location.unique()), aspects):
        region_df = df[df.Location == region]
        ns = {"region_df": region_df, "aspect_to_sort": aspect}
        exec(operation, ns)
        result = ns["top_hotels"]
        values = result[aspect].dropna().tolist()
        best_by_hotel = {}
        for _, row in region_df.iterrows():
            score = row[aspect]
            if pd.notna(score):
                best_by_hotel[row.Hotel] = max(best_by_hotel.get(row.Hotel, -float("inf")), score)
        expected_scores = sorted(best_by_hotel.values(), reverse=True)[:5]
        checks = {"unique_names": result.Hotel.is_unique,
                  "row_count": len(result) == min(5, region_df.Hotel.nunique()),
                  "descending": values == sorted(values, reverse=True),
                  "region_membership": set(result.Hotel).issubset(set(region_df.Hotel)),
                  "top_five_scores": values == expected_scores}
        cases.append({"region": region, "aspect": aspect, "checks": checks, "passed": all(checks.values())})
    return {"cases": cases, "total": len(cases), "passed": sum(c["passed"] for c in cases),
            "scope": "9 regions × 6 aspects; original ranking statements. "
                     "Functional checks only; not summary factuality or recommendation relevance."}


def measure_nohuae(root):
    folder = root / "nohuae"
    frames = {}
    for p in folder.glob("*.csv"):
        name = unicodedata.normalize("NFC", p.name)
        if name in {"금융상품_3개_통합본.csv", "펀드_병합본.csv"}:
            frames[name] = pd.read_csv(p, encoding="utf-8-sig")
    functions = ["build_index", "index_search", "preprocess_products", "rule_based_filter",
                 "_get_feature_vector", "_get_user_vector", "_add_explain", "recommend_fallback_split"]
    ns = {"np": np, "pd": pd, "faiss": faiss, "USE_FAISS": True,
          "st": SimpleNamespace(warning=lambda _: None),
          "load_deposit_csv": lambda: frames["금융상품_3개_통합본.csv"].copy(),
          "load_fund_csv": lambda: frames["펀드_병합본.csv"].copy()}
    source_functions(folder / "senior_survey_paged_app.py", functions, ns)
    allowed = {"안정형": {"낮음", "중간"}, "위험중립형": {"낮음", "중간", "높음"},
               "공격형": {"높음", "중간"}}
    catalogs = [ns["preprocess_products"](frame.copy(), group).to_dict("records")
                for frame, group in [(frames["금융상품_3개_통합본.csv"], "예·적금"),
                                     (frames["펀드_병합본.csv"], "펀드")]]
    amounts = [0, 99, 100, 499, 500, 999, 1000, 5000]
    periods = [0, 5, 6, 11, 12, 23, 24, 36]
    inputs = list(itertools.product(allowed, amounts, periods))
    np.random.default_rng(20260915).shuffle(inputs)
    cases, latencies = [], []
    for risk, amount, period in inputs:
        user = {"투자성향": risk, "투자금액": amount, "투자기간": period, "목표월이자": 3}
        start = time.perf_counter_ns()
        result = ns["recommend_fallback_split"](user)
        latencies.append((time.perf_counter_ns() - start) / 1e6)
        products = [] if "상품명" not in result else result.to_dict("records")
        violations = 0
        for product in products:
            violations += int(not (product["최소투자금액"] <= amount
                and product["투자기간(개월)"] <= period and product["리스크"] in allowed[risk]))
        groups = collections.Counter(p["구분"] for p in products)
        eligible_counts = [sum(p["최소투자금액"] <= amount and p["권장투자기간"] <= period
                               and p["리스크"] in allowed[risk] for p in catalog) for catalog in catalogs]
        empty_handling_valid = bool(products) == any(eligible_counts)
        valid_shape = (len(products) <= 3 and groups["예·적금"] <= 2 and groups["펀드"] <= 1
                       and len({p["상품명"] for p in products}) == len(products))
        cases.append({"risk": risk, "amount": amount, "months": period, "returned": len(products),
                      "violations": violations, "eligible_counts": eligible_counts,
                      "empty_handling_valid": empty_handling_valid,
                      "passed": violations == 0 and valid_shape and empty_handling_valid})
    # Inspect the actual recommendation input, not the separate TabNet survey labels.
    module = ast.parse(read(folder / "senior_survey_paged_app.py"))
    selector = next(n for n in ast.walk(module) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == "selectbox"
                    and any(k.arg == "key" and isinstance(k.value, ast.Constant)
                            and k.value.value == "reco_risk" for k in n.keywords))
    labels = ast.literal_eval(selector.args[1])
    assert set(labels) == set(allowed)
    return {"total_cases": len(cases), "passed": sum(c["passed"] for c in cases),
            "nonempty_cases": sum(c["returned"] > 0 for c in cases),
            "returned_recommendations": sum(c["returned"] for c in cases),
            "condition_violations": sum(c["violations"] for c in cases),
            "timing": timing_summary(latencies), "cases": cases,
            "recommendation_ui_risk_labels": labels,
            "scope": "3 explicitly supported risk labels × 8 amounts × 8 periods; original preprocessing, "
                     "rules and FAISS recommendation functions; input CSVs preloaded, generated attributes "
                     "seed=42 as in source; no TabNet, UI, network or real suitability validation. "
                     "Empty cases counted separately and checked against independently counted eligible candidates. "
                     "All 3 risk choices of the recommendation UI are included. Separate TabNet survey labels "
                     "are not passed to this function by the recommendation form."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    revisions = {}
    for local, repo in {"lxp": "samsung_axi_2nd", "jeju": "jeju_2024",
                        "stayview": "stayview", "nohuae": "senior_finance_recommender"}.items():
        revision = subprocess.check_output(["git", "-C", str(args.source_root / local),
                                            "rev-parse", "HEAD"], text=True).strip()
        assert revision == REVISIONS[repo], f"Unexpected revision for {repo}: {revision}"
        revisions[repo] = revision
    faiss.omp_set_num_threads(1)
    report = {"measured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "environment": {"os": platform.platform(), "machine": platform.machine(),
                              "python": platform.python_version(), "numpy": np.__version__,
                              "pandas": pd.__version__, "faiss": faiss.__version__, "faiss_threads": 1},
              "source_revisions": revisions, "external_llm_calls": 0}
    for label, fn in [("lxp", junit_results), ("jeju", measure_jeju),
                      ("stayview", measure_stayview), ("nohuae", measure_nohuae)]:
        print(f"Measuring {label}...", file=sys.stderr, flush=True)
        report[label] = fn(args.source_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in {"lxp", "jeju", "stayview", "nohuae"}}
    for label in ["lxp", "jeju", "stayview", "nohuae"]:
        summary[label] = {k: v for k, v in report[label].items() if k not in {"cases", "suites"}}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
