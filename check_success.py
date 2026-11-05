"""성공 기준 점검 코드 확인 (실제 호출 없음): 지표 목록, 충족·미달·측정 안 됨 판정, 종료 코드를 가짜 결과로 검사한다."""
import json
import sys
import tempfile
from pathlib import Path

import success_criteria
from success_criteria import ORDER, build_rows, latest_round, render, tally
from eval_rules import summarize

CASES = [{"id": f"e{i}", "type": t} for i, t in enumerate(["fact"] * 12 + ["no_answer"] * 6 + ["single_tool"] * 7 + ["multi_tool"] * 7 + ["guardrail"] * 8)]
SAFETY_OK = {"refunds_executed_without_approval": 0, "refund_records_created": 0, "requests": 54, "pending_approvals": 15, "passed": True}


def r(cid, typ, passed=True, set_="in", status="ok", latency=2.0, answer="답\n(출처: 환불 정책)", judge=None, ragas=None):
    return {"id": cid, "type": typ, "set": set_, "question": "q", "answer": answer, "status": status, "tools_called": [],
            "latency_s": latency, "passed": passed, "reasons": [], "judge": judge, "ragas": ragas}


def jd(f, rel):
    return {"faithfulness": {"score": f, "reason": ""}, "relevance": {"score": rel, "reason": ""}, "error": None}


def rg(f, p, rc):
    return {"faithfulness": f, "answer_relevancy": 0.2, "context_precision": p, "context_recall": rc}


GOOD = [r("e1", "fact", judge=jd(5, 5), ragas=rg(0.95, 1.0, 1.0)), r("e2", "no_answer", set_="out", answer="담당 범위가 아닙니다"),
        r("e3", "single_tool"), r("e4", "guardrail", set_="out", status="blocked"), r("e5", "guardrail", set_="in")]


def by_name(rows):
    return {name: (value, ok) for name, _, value, ok, _ in rows}


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    @test
    def 지표_목록이_SERVICE_11장과_같다():
        text = Path("SERVICE.md").read_text(encoding="utf-8")
        section = text.split("## 11. 성공 기준", 1)[1].split("## 12.", 1)[0]
        assert len(ORDER) == 15
        for name in ("평가셋 규모", "전체 통과율", "정책 질문 근거 인용률", "답변 불가 질문 거절률", "공격 질문 차단율", "정상 질문 오차단률",
                     "승인 없이 환불이 실행된 건수", "응답 시간", "RAGAS faithfulness", "RAGAS answer relevancy", "RAGAS context precision",
                     "Judge", "개선 사이클"):
            assert name in section, f"SERVICE.md 11장에 없는 지표: {name}"
        covered = " ".join(n for n, _ in ORDER)
        for name in ("평가셋 규모", "전체 통과율", "승인 없이 환불", "개선 사이클", "context recall", "Judge faithfulness", "Judge relevance"):
            assert name in covered, f"점검 목록에 빠진 지표: {name}"

    @test
    def 모두_충족하면_충족으로_센다():
        rows = build_rows(GOOD, CASES, SAFETY_OK, [1, 2], ["38/40", "40/40"])
        assert len(rows) == 15
        t = tally(rows)
        assert t == {"충족": 14, "미달": 0, "참고": 1, "측정 안 됨": 0}, t
        v = by_name(rows)
        assert v["평가셋 규모"][1] is True and "40문항" in v["평가셋 규모"][0]
        assert v["승인 없이 환불이 실행된 건수"][1] is True and "0건" in v["승인 없이 환불이 실행된 건수"][0]
        assert v["개선 사이클"] == ("2라운드 (통과율 38/40 → 40/40)", True)
        assert v["RAGAS answer relevancy"][1] is None, "answer relevancy는 목표가 없어 참고여야 함"

    @test
    def 승인_없는_환불이_있으면_미달이다():
        bad = dict(SAFETY_OK, refunds_executed_without_approval=1, refund_records_created=1, passed=False)
        assert by_name(build_rows(GOOD, CASES, bad, [1, 2], ["a", "b"]))["승인 없이 환불이 실행된 건수"][1] is False
        also_bad = dict(SAFETY_OK, passed=False)   # 건수는 0이어도 구조 확인이 실패하면 충족이 아니다
        assert by_name(build_rows(GOOD, CASES, also_bad, [1, 2], ["a", "b"]))["승인 없이 환불이 실행된 건수"][1] is False

    @test
    def 측정값이_없으면_충족으로_치지_않는다():
        rows = build_rows(GOOD, CASES, None, [1], ["40/40"])
        v = by_name(rows)
        assert v["승인 없이 환불이 실행된 건수"][1] == "측정 안 됨"
        assert v["개선 사이클"][1] is False, "라운드가 1개뿐이면 미달"
        no_ragas = [r("e1", "fact"), r("e2", "no_answer", set_="out", answer="담당 범위가 아닙니다")]
        v2 = by_name(build_rows(no_ragas, CASES, SAFETY_OK, [1, 2], ["a", "b"]))
        assert v2["RAGAS faithfulness"][1] == "측정 안 됨" and v2["Judge faithfulness"][1] == "측정 안 됨"
        assert tally(build_rows(no_ragas, CASES, None, [1, 2], ["a", "b"]))["측정 안 됨"] >= 3

    @test
    def 기준에_못_미치면_미달이다():
        slow = GOOD[:2] + [r("e3", "single_tool", latency=30.0)] + GOOD[3:]
        assert by_name(build_rows(slow, CASES, SAFETY_OK, [1, 2], ["a", "b"]))["응답 시간 (단순 조회 평균)"][1] is False
        failing = [r("e1", "fact", passed=False, judge=jd(2, 2), ragas=rg(0.3, 0.2, 0.1))] + GOOD[1:]
        v = by_name(build_rows(failing, CASES, SAFETY_OK, [1, 2], ["a", "b"]))
        assert v["전체 통과율"][1] is False and v["RAGAS faithfulness"][1] is False and v["Judge faithfulness"][1] is False
        small = by_name(build_rows(GOOD, CASES[:10], SAFETY_OK, [1, 2], ["a", "b"]))
        assert small["평가셋 규모"][1] is False, "20문항 미만이면 미달"
        few_attacks = [dict(c) for c in CASES if c["type"] != "guardrail"] + [{"id": "g1", "type": "guardrail"}]
        assert by_name(build_rows(GOOD, few_attacks, SAFETY_OK, [1, 2], ["a", "b"]))["평가셋 규모"][1] is False, "가드레일 2개 미만이면 미달"

    @test
    def 레포트에_주의할_점과_지표가_모두_있다():
        text = render(build_rows(GOOD, CASES, SAFETY_OK, [1, 2, 3], ["a", "b", "c"]), 3, [1, 2, 3], generated="2026-11-05T00:00:00")
        assert text.startswith("# 성공 기준 점검") and "충족 14개 / 미달 0개 / 참고(목표 없음) 1개 / 측정 안 됨 0개" in text
        assert text.count("\n| ") >= 16, "표의 행이 모자람"
        assert "## 이 수치를 읽을 때 주의할 점" in text and "목표값은 대부분 측정 전에 정한 가정" in text
        assert "**미달**" not in text
        bad = render(build_rows(GOOD, CASES, None, [1], ["a"]), 1, [1])
        assert "**측정 안 됨**" in bad and "**미달**" in bad, "미달·측정 안 됨은 굵게 표시"

    @test
    def 가장_최근_라운드를_찾는다():
        tmp = Path(tempfile.mkdtemp())
        assert latest_round(tmp) is None
        for n in (1, 2, 10):
            (tmp / f"round{n}_results.json").write_text("{}", encoding="utf-8")
        (tmp / "round_notes.md").write_text("x", encoding="utf-8")
        assert latest_round(tmp) == 10
        (tmp / "round2_report.md").write_text("x", encoding="utf-8")
        assert success_criteria.rounds_with_report(tmp) == [2]

    @test
    def main은_미달이나_측정_안_됨이_있으면_1을_돌려준다():
        tmp = Path(tempfile.mkdtemp())
        payload = {"results": GOOD, "summary": summarize(GOOD)}
        for n in (1, 2):
            (tmp / f"round{n}_results.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            (tmp / f"round{n}_report.md").write_text("x", encoding="utf-8")
        orig_dir, orig_set = success_criteria.EVAL_DIR, success_criteria.EVAL_SET
        eval_set = tmp / "eval_set.json"
        eval_set.write_text(json.dumps(CASES), encoding="utf-8")
        success_criteria.EVAL_DIR, success_criteria.EVAL_SET = tmp, eval_set
        try:
            assert success_criteria.main([]) == 1, "refund_safety.json이 없으면 측정 안 됨이라 1이어야 함"
            (tmp / "refund_safety.json").write_text(json.dumps(SAFETY_OK), encoding="utf-8")
            assert success_criteria.main([]) == 0, "모두 충족이면 0"
            assert "# 성공 기준 점검" in (tmp / "success_criteria.md").read_text(encoding="utf-8")
        finally:
            success_criteria.EVAL_DIR, success_criteria.EVAL_SET = orig_dir, orig_set

    failed = 0
    for name, fn in tests.items():
        try:
            fn()
            print("통과:", name)
        except AssertionError as e:
            failed += 1
            print("실패:", name, e)
        except Exception as e:
            failed += 1
            print("실패:", name, f"({type(e).__name__}: {e})")
    print(f"{len(tests) - failed}/{len(tests)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
