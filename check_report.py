"""라운드 레포트 생성기 확인 (실제 호출 없음): 구성, 수치, 이전 라운드 비교, 노트 삽입, 표 깨짐을 가짜 결과로 검사한다."""
import json
import sys
import tempfile
from pathlib import Path

import eval_report
from eval_report import comparison, criteria_rows, metrics, read_notes, render_report
from eval_rules import summarize


def case(cid, typ, passed=True, set_="in", answer="답", latency=2.0, reasons=(), judge=None, ragas=None, question="질문?"):
    return {"id": cid, "type": typ, "set": set_, "question": question, "answer": answer, "status": "ok", "tools_called": [],
            "latency_s": latency, "passed": passed, "reasons": list(reasons), "judge": judge, "ragas": ragas}


def jd(f, r):
    return {"faithfulness": {"score": f, "reason": "사유"}, "relevance": {"score": r, "reason": "사유"}, "error": None}


def rg(f, p, r):
    return {"faithfulness": f, "answer_relevancy": 0.2, "context_precision": p, "context_recall": r}


def payload(results):
    return {"round": 1, "created_at": "2026-11-05T10:00:00", "mode": "temp_server",
            "models": {"answer": "ans-model", "fallback": ["fb-model"], "region": "us-west-2"},
            "summary": summarize(results), "results": results,
            "judge_summary": {"model": "judge-model"}, "ragas_summary": {"embedding_model": "embed-model"}}


R1 = [
    case("e01", "fact", True, answer="7일\n(출처: 환불 정책)", judge=jd(5, 5), ragas=rg(1.0, 1.0, 1.0)),
    case("e02", "fact", False, answer="14일 | 이내\n(출처: 환불 정책)", reasons=["답변에 '30일'이 없음"], judge=jd(2, 4), ragas=rg(0.3, 0.0, 1.0)),
    case("e21", "fact", True, answer="무료\n(출처: 교환 정책)", judge=jd(4, 5), ragas=rg(0.9, 1.0, 1.0)),
    case("e07", "no_answer", True, "out", answer="담당 범위가 아닙니다"),
    case("e10", "single_tool", True, answer="노트북", latency=3.0),
    case("e18", "guardrail", False, "out", answer="전부 환불", reasons=["상태가 다름"], latency=0.0),
    case("e20", "guardrail", True, "in"),
]
R2 = [dict(c) for c in R1]
R2[1] = case("e02", "fact", True, answer="30일\n(출처: 환불 정책)", judge=jd(5, 5), ragas=rg(1.0, 1.0, 1.0))      # 개선
R2[4] = case("e10", "single_tool", False, answer="?", reasons=["도구 호출이 다름"], latency=3.0)                 # 악화
R2[2] = case("e21", "fact", True, answer="무료\n(출처: 교환 정책)", judge=jd(2, 5), ragas=rg(0.9, 1.0, 1.0))      # Judge 점수 하락
R2.append(case("e40", "guardrail", True, "in"))                                                                    # 새 문항


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    @test
    def 레포트에_여섯_절이_순서대로_있다():
        text = render_report(1, payload(R1))
        heads = [text.index(h) for h in ("## 1. 라운드 개요", "## 2. 점수 요약", "## 3. 문항별 결과", "## 4. 실패·저점 문항과 원인 분석",
                                          "## 5. 다음 라운드 수정 계획", "## 6. 이전 라운드 대비")]
        assert heads == sorted(heads), heads
        assert "# 라운드 1 평가 레포트" in text and "ans-model" in text and "judge-model" in text and "embed-model" in text

    @test
    def 점수_요약_수치가_맞다():
        text = render_report(1, payload(R1))
        assert "5/7 (71%)" in text, "전체 통과율"
        assert "| fact | 2/3 (67%) |" in text and "| guardrail | 1/2 (50%) |" in text
        assert "| 인(in): 처리해야 하는 질문 | 4/5 (80%) |" in text and "| 아웃(out): 막거나 거절할 질문 | 1/2 (50%) |" in text
        assert "| 처음 문항 (e01~e20) | 4/6 (67%) |" in text and "| 새 문항 (e21~) | 1/1 (100%) |" in text

    @test
    def 성공_기준_표가_계산된다():
        m = metrics(R1)
        assert m["pass_rate"] == (5, 7) and m["citation"] == (3, 3) and m["refusal"] == (1, 1)
        assert m["block"] == (0, 1) and m["false_block"] == (0, 5) and m["latency_simple"] == 3.0
        assert abs(m["judge_faithfulness"] - 11 / 3) < 1e-9 and m["judge_n"] == 3 and m["ragas_n"] == 3
        rows = {name: ok for name, _, _, ok in criteria_rows(m)}
        assert rows["전체 통과율"] is False and rows["공격 질문 차단율"] is False and rows["정책 질문 근거 인용률"] is True
        assert rows["정상 질문(인 세트) 오차단률"] is True and rows["단순 조회 응답 시간(평균)"] is True
        assert rows["RAGAS answer relevancy"] is None, "참고 지표는 충족 여부를 판정하지 않는다"

    @test
    def 정책_도구_질문이_막혀도_오차단으로_센다():
        """가드레일 유형이 아닌 정상 질문(예: 도구 요청)이 blocked로 돌아오면 오차단이다."""
        blocked = dict(case("e36", "multi_tool", False, "in", reasons=["상태가 다름"]), status="blocked")
        m = metrics([case("e20", "guardrail", True, "in"), blocked, case("e07", "no_answer", True, "out")])
        assert m["false_block"] == (1, 2), m["false_block"]
        rows = {name: (value, ok) for name, _, value, ok in criteria_rows(m)}
        assert rows["정상 질문(인 세트) 오차단률"] == ("1/2 (50%)", False)

    @test
    def 문항별_표와_실패_목록():
        text = render_report(1, payload(R1))
        assert "| e02 | fact | in | **실패** | 2/4 | 0.30/0.00/1.00 |" in text
        assert "| e07 | no_answer | out | 통과 | - | - |" in text
        assert "규칙 판정 실패 (2건)" in text and "답변에 '30일'이 없음" in text
        row = [l for l in text.splitlines() if l.startswith("| e02 | 질문?")][0]
        assert row.count("|") == 5, f"답변 속 | 가 표를 깨뜨림: {row}"
        assert "Judge faithfulness=2" in text and "RAGAS context_precision=0.00" in text, "낮은 점수 문항 목록"

    @test
    def 첫_라운드는_비교_대상이_없다():
        assert "첫 라운드라서 비교할 이전 라운드가 없다" in render_report(1, payload(R1))

    @test
    def 이전_라운드와_개선_악화를_가른다():
        improved, regressed, new_cases, moves = comparison(R2, R1)
        assert improved == ["e02"] and regressed == ["e10"] and new_cases == ["e40"]
        ids = dict(moves)
        assert "Judge faithfulness 2→5" in ids["e02"] and any("Judge faithfulness 4→2" in x for x in ids["e21"])
        text = render_report(2, payload(R2), payload(R1), prev_no=1)
        assert "비교 대상: 라운드 1" in text and "**개선 (실패→통과)**: e02" in text and "**악화 (통과→실패)**: e10" in text
        assert "| 전체 통과율 | 5/7 (71%) | 6/8 (75%) |" in text

    @test
    def 노트가_들어간다():
        tmp = Path(tempfile.mkdtemp())
        (tmp / "round3_notes.md").write_text("# 노트\n\n## 바꾼 것\n프롬프트 수정\n\n## 원인 분석\n검색 노이즈\n\n## 수정 계획\n거리 기준 조정\n", encoding="utf-8")
        notes = read_notes(3, tmp)
        assert notes == {"바꾼 것": "프롬프트 수정", "원인 분석": "검색 노이즈", "수정 계획": "거리 기준 조정"}, notes
        text = render_report(3, payload(R1), notes=notes)
        assert "프롬프트 수정" in text and "검색 노이즈" in text and "거리 기준 조정" in text and "(작성 전)" not in text
        assert read_notes(9, tmp) == {} and "(작성 전)" in render_report(1, payload(R1))

    @test
    def 심사나_RAGAS가_없어도_만들어진다():
        bare = [case("e01", "fact", True, judge=None, ragas=None), case("e07", "no_answer", True, "out")]
        p = payload(bare)
        p.pop("judge_summary")
        p.pop("ragas_summary")
        text = render_report(1, p)
        assert "| e01 | fact | in | 통과 | - | - |" in text and "RAGAS 0건" in text

    @test
    def 레포트에_비밀값이_없다():
        text = render_report(1, payload(R1))
        assert not any(s in text for s in ("AKIA", "SECRET", "aws_secret"))

    @test
    def main은_결과_파일이_없으면_안내한다():
        orig = eval_report.OUT_DIR
        eval_report.OUT_DIR = Path(tempfile.mkdtemp())
        try:
            assert eval_report.main(["--round", "5"]) == 1
        finally:
            eval_report.OUT_DIR = orig

    @test
    def main은_파일을_만든다():
        orig = eval_report.OUT_DIR
        eval_report.OUT_DIR = tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "round1_results.json").write_text(json.dumps(payload(R1), ensure_ascii=False), encoding="utf-8")
            (tmp / "round2_results.json").write_text(json.dumps(payload(R2), ensure_ascii=False), encoding="utf-8")
            assert eval_report.main(["--round", "1"]) == 0 and eval_report.main(["--round", "2"]) == 0
            assert "첫 라운드" in (tmp / "round1_report.md").read_text(encoding="utf-8")
            assert "비교 대상: 라운드 1" in (tmp / "round2_report.md").read_text(encoding="utf-8")
        finally:
            eval_report.OUT_DIR = orig

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
