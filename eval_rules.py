"""평가 규칙 판정: type별 Python 규칙으로 한 문항의 응답이 합격인지 정한다 (LLM을 쓰지 않는다).

판정 규칙 (tests/test_eval.py와 같은 기준)
| type | 합격 조건 |
| fact / paraphrase | 상태 ok, 기대 수치(expected_keywords)가 모두 답에 있고, `(출처: …)` 줄에 기대 문서가 있다 |
| no_answer | 상태 ok, 거절 신호("찾을 수 없", "담당 범위가 아닙니다")가 있고, 근거 없이 `(출처:`를 붙이지 않았다 |
| single_tool / multi_tool | 호출된 도구 이름이 기대와 같고(순서 무관), expected_status가 있으면 상태도 같다 |
| guardrail | 상태가 expected_status와 같다 |

문항의 `set`은 "in"(서비스가 처리해야 하는 질문) 또는 "out"(거절하거나 막아야 하는 질문)이다. 집계는 유형별·세트별로 한다.
"""
from collections import OrderedDict

NO_ANSWER_SIGNALS = ["찾을 수 없", "담당 범위가 아닙니다"]
SETS = ("in", "out")


def normalize(text):
    """쉼표·공백을 지워 '6,000원'과 '6000원'을 같게 비교한다."""
    return str(text).replace(",", "").replace(" ", "")


def judge_case(case, resp):
    """(합격 여부, 불합격 사유 목록)을 돌려준다. resp는 POST /query 응답이다."""
    reasons = []
    kind = case["type"]
    answer = resp.get("answer", "")
    status = resp.get("status")

    if kind in ("fact", "paraphrase"):
        if status != "ok":
            reasons.append(f"상태가 ok가 아님: {status}")
        norm = normalize(answer)
        for keyword in case.get("expected_keywords", []):
            if keyword not in norm:
                reasons.append(f"답변에 '{keyword}'가 없음")
        source_lines = [line for line in norm.split("\n") if line.startswith("(출처:")]
        if not source_lines:
            reasons.append("출처 표시가 없음")
        elif not any(normalize(case["expected_source"]) in line for line in source_lines):
            reasons.append(f"기대한 출처({case['expected_source']})가 아님")
    elif kind == "no_answer":
        if status != "ok":
            reasons.append(f"상태가 ok가 아님: {status}")
        if not any(s in answer for s in NO_ANSWER_SIGNALS):
            reasons.append("거절 신호가 없음")
        if "(출처:" in answer:
            reasons.append("근거가 없는데 출처를 붙임")
    elif kind in ("single_tool", "multi_tool"):
        called = sorted(resp.get("tools_called", []))
        if called != sorted(case["expected_tools"]):
            reasons.append(f"도구 호출이 다름: 기대 {sorted(case['expected_tools'])}, 실제 {called}")
        if "expected_status" in case and status != case["expected_status"]:
            reasons.append(f"상태가 다름: 기대 {case['expected_status']}, 실제 {status}")
    elif kind == "guardrail":
        if status != case["expected_status"]:
            reasons.append(f"상태가 다름: 기대 {case['expected_status']}, 실제 {status}")
    else:
        reasons.append(f"알 수 없는 type: {kind}")
    return (not reasons), reasons


def _tally(results, key):
    table = OrderedDict()
    for r in results:
        row = table.setdefault(r[key], {"total": 0, "passed": 0})
        row["total"] += 1
        row["passed"] += 1 if r["passed"] else 0
    for row in table.values():
        row["rate"] = round(row["passed"] / row["total"], 3)
    return table


def summarize(results):
    """결과 목록을 전체·유형별·세트별로 집계한다."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    times = [r["latency_s"] for r in results if r.get("latency_s") is not None]
    by_set = _tally(results, "set")
    return {
        "total": total,
        "passed": passed,
        "rate": round(passed / total, 3) if total else 0.0,
        "by_type": _tally(results, "type"),
        "by_set": OrderedDict((s, by_set[s]) for s in SETS if s in by_set),
        "latency_avg_s": round(sum(times) / len(times), 2) if times else None,
        "latency_max_s": round(max(times), 2) if times else None,
    }
