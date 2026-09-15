"""Read pinned public sources and recount portfolio metrics; no project code is executed.

Run: python3 scripts/audit_project_metrics.py
Downloads approximately 100 MB, primarily the Jeju source CSV.
Counts test definitions, not passing tests. Never loads pickle/model objects.
"""

import ast
import csv
import io
import json
import re
import struct
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor


REVISIONS = {
    "samsung_axi_2nd": "9c6b4003fc4e84bf58d3c23990cf4c4e2d26acfc",
    "jeju_2024": "80a1dde19921a8f8671a0acd034e79b8bfb6cc2e",
    "stayview": "5300c95c08ee5cf325935f7fa7f29f31727c3987",
    "senior_finance_recommender": "ab024e6a1ddd177e610aa181ddb05fd022dc1bb0",
}


def source_url(repo, path):
    return (
        f"https://raw.githubusercontent.com/min03027/{repo}/{REVISIONS[repo]}/"
        + urllib.parse.quote(path)
    )


def read_text(repo, path):
    with urllib.request.urlopen(source_url(repo, path), timeout=60) as response:
        return response.read().decode("utf-8-sig")


def rows(repo, path, encoding):
    with urllib.request.urlopen(source_url(repo, path), timeout=60) as response:
        return list(csv.DictReader(io.TextIOWrapper(response, encoding=encoding, newline="")))


def tree(repo):
    url = f"https://api.github.com/repos/min03027/{repo}/git/trees/{REVISIONS[repo]}?recursive=1"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)["tree"]


def numpy_shape(path):
    # Only inspect the NPY header; do not deserialize array objects.
    with urllib.request.urlopen(source_url("jeju_2024", path), timeout=60) as response:
        magic = response.read(8)
        assert magic[:6] == b"\x93NUMPY"
        fmt, length = ("<H", 2) if magic[6] == 1 else ("<I", 4)
        size = struct.unpack(fmt, response.read(length))[0]
        assert size < 65536
        header = ast.literal_eval(response.read(size).decode("latin1"))
        return list(header["shape"])


def audit_lxp():
    prefix = "src/test/java/com/ssa/lms/ai/"
    files = {}
    for entry in tree("samsung_axi_2nd"):
        path = entry["path"]
        if not (path.startswith(prefix) and path.endswith(".java")):
            continue
        text = read_text("samsung_axi_2nd", path)
        code = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", text)
        files[path.rsplit("/", 1)[-1]] = len(re.findall(r"@Test\b", code))
        assert not re.search(r"@Disabled\b", code)
    assert len(files) == 7 and sum(files.values()) == 41
    return {"project": "LXP", "test_definitions": files, "total": 41, "tests_executed": False}


def audit_jeju():
    data = rows("jeju_2024", "data/JEJU_DATA.csv", "cp949")
    tours = rows("jeju_2024", "data/JEJU_TOUR.csv", "cp949")
    latest = {}
    for row in data:
        name = row["가맹점명"]
        if name and (name not in latest or row["기준연월"] > latest[name]["기준연월"]):
            latest[name] = row
    months = sorted({row["기준연월"] for row in data})
    store_shape = numpy_shape("modules/embeddings_array_file_1.npy")
    tour_shape = numpy_shape("modules/embeddings_tour_array_file_1.npy")
    assert (len(data), len(latest), len(tours), len(months)) == (67575, 9346, 381, 12)
    assert store_shape == [9346, 768] and tour_shape == [381, 768]
    return {"project": "Jeju", "source_rows": len(data), "latest_rows_by_store_name": len(latest),
            "tour_rows": len(tours), "months": months, "store_embedding_shape": store_shape,
            "tour_embedding_shape": tour_shape}


def audit_stayview():
    data = rows("stayview", "hotel_fin_0331_2.csv", "euc-kr")
    regions = {row["Location"] for row in data}
    names = {row["Hotel"] for row in data}
    positive = sum(bool(row["Refined_Positive"].strip()) for row in data)
    negative = sum(bool(row["Refined_Negative"].strip()) for row in data)
    assert (len(data), len(regions), len(names)) == (394, 9, 392)
    assert (positive, negative) == (394, 386)
    return {"project": "Stayview", "hotel_summary_rows": len(data), "regions": len(regions),
            "distinct_hotel_names": len(names), "positive_summary_cells": positive,
            "negative_summary_cells": negative, "total_summary_cells": positive + negative,
            "unit": "aggregated hotel rows and nonempty summary cells, not raw reviews"}


def audit_nohuae():
    result = {}
    named_candidates = {}
    for entry in tree("senior_finance_recommender"):
        path = entry["path"]
        if path.endswith(".csv") and entry.get("size", 0) > 10000:
            data = rows("senior_finance_recommender", path, "utf-8-sig")
            result[path] = len(data)
            column = "상품명" if "상품명" in data[0] else "펀드명"
            named_candidates[path] = len({r[column] for r in data if r[column] and r[column] != "무명상품"})
    assert sorted(result.values()) == [1122, 9598]
    assert sorted(named_candidates.values()) == [440, 9596]
    return {"project": "Nohuae", "source_rows_by_file": result, "total_source_rows": sum(result.values()),
            "named_candidates_by_file": named_candidates, "total_named_candidates": sum(named_candidates.values()),
            "unit": "source rows and candidate counts keyed by product name within each product group"}


if __name__ == "__main__":
    csv.field_size_limit(10_000_000)
    with ThreadPoolExecutor(max_workers=4) as executor:
        for result in executor.map(lambda fn: fn(), [audit_lxp, audit_jeju, audit_stayview, audit_nohuae]):
            print(json.dumps(result, ensure_ascii=False), flush=True)
