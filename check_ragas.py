"""RAGAS 연동 코드 확인 (실제 호출 없음): 샘플 만들기, 건너뛰기, NaN 처리, 집계, 호환 처리를 검사한다.

ragas가 실제로 점수를 내는지, 좋은 답변과 나쁜 답변을 가르는지는 check_ragas_real.py(실제 모델 호출)에서 본다.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import ragas_compat
import ragas_eval
from ragas_eval import (METRIC_COLUMNS, build_samples, clean_response, ragas_results, score_samples, summarize_ragas)

REFS = {"e01": "정답 1", "e05": "정답 5", "e21": "정답 21"}


def row(f=1.0, a=0.2, p=1.0, r=1.0):
    return {"faithfulness": f, "answer_relevancy": a, "llm_context_precision_with_reference": p, "context_recall": r}


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    @test
    def 출처_줄만_뺀다():
        assert clean_response("7일 이내입니다.\n(출처: 환불 정책)") == "7일 이내입니다."
        assert clean_response("A\n(출처: 환불 정책, 교환 정책)\n") == "A"
        assert clean_response("**7일** 이내\n| 표 | 값 |") == "**7일** 이내\n| 표 | 값 |", "다른 가공은 하지 않는다"
        assert clean_response("출처: 없음\n(출처 아님)") == "출처: 없음\n(출처 아님)"
        assert clean_response(None) == ""

    @test
    def 채점할_샘플과_건너뛸_문항을_가른다():
        results = [
            {"id": "e01", "type": "fact", "question": "q1", "answer": "a1\n(출처: 환불 정책)", "contexts": ["c1", "c2"]},
            {"id": "e05", "type": "paraphrase", "question": "q5", "answer": "a5", "contexts": []},          # 근거 없음
            {"id": "e21", "type": "fact", "question": "q21", "answer": None, "contexts": ["c"]},           # 답변 없음
            {"id": "e26", "type": "fact", "question": "q26", "answer": "a26", "contexts": ["c"]},          # 정답 문장 없음
            {"id": "e10", "type": "single_tool", "question": "q", "answer": "a", "contexts": ["c"]},      # 정책 질문 아님
            {"id": "e22", "type": "fact", "question": "q22", "answer": "a22", "contexts": None},          # 기록 없음
        ]
        samples, skipped = build_samples(results, REFS)
        assert [s["id"] for s in samples] == ["e01"]
        assert samples[0] == {"id": "e01", "user_input": "q1", "response": "a1", "retrieved_contexts": ["c1", "c2"], "reference": "정답 1"}
        assert set(skipped) == {"e05", "e21", "e26", "e22"} and "e10" not in skipped
        assert "답변이 없음" in skipped["e21"] and "정답 문장" in skipped["e26"] and "근거" in skipped["e05"]

    @test
    def 점수를_숫자로_바꾸고_NaN은_None으로_둔다():
        nan = float("nan")
        scores = score_samples([{}, {}, {}], lambda s: [row(), row(f=nan, a=None, p="x", r=0.5), row(f=0, r=1)])
        assert scores[0] == {"faithfulness": 1.0, "answer_relevancy": 0.2, "context_precision": 1.0, "context_recall": 1.0}
        assert scores[1] == {"faithfulness": None, "answer_relevancy": None, "context_precision": None, "context_recall": 0.5}
        assert scores[2]["faithfulness"] == 0.0, "0점은 0점이다 (None과 다르다)"
        assert set(scores[0]) == set(METRIC_COLUMNS)

    @test
    def 결과_수가_다르면_오류다():
        try:
            score_samples([{}, {}], lambda s: [row()])
        except ValueError:
            return
        raise AssertionError("샘플 수와 다른 결과를 받아들임")

    @test
    def 집계는_None을_빼고_낮은_점수를_표시한다():
        results = [
            {"id": "a", "ragas": {"faithfulness": 1.0, "answer_relevancy": 0.2, "context_precision": 1.0, "context_recall": 1.0}},
            {"id": "b", "ragas": {"faithfulness": 0.4, "answer_relevancy": 0.1, "context_precision": None, "context_recall": 0.0}},
            {"id": "c"},
        ]
        s = summarize_ragas(results, {"x": "사유"}, "judge", "embed")
        assert s["scored"] == 2 and s["skipped"] == {"x": "사유"}
        assert s["faithfulness_avg"] == 0.7 and s["context_precision_n"] == 1 and s["context_recall_avg"] == 0.5
        assert s["low_cases"] == [{"id": "b", "faithfulness": 0.4, "context_recall": 0.0}]
        assert "answer_relevancy" in s["unreliable"], "신뢰할 수 없는 지표 표시가 없음"
        assert all("answer_relevancy" not in c for c in s["low_cases"]), "신뢰 못 하는 지표로 낮은 점수 문항을 만들면 안 됨"
        assert summarize_ragas([], {}, "j", "e")["faithfulness_avg"] is None

    @test
    def 결과에_점수를_붙인다():
        results = [{"id": "e01", "type": "fact", "question": "q", "answer": "a", "contexts": ["c"]},
                   {"id": "e07", "type": "no_answer", "question": "q", "answer": "a", "contexts": []}]
        summary = ragas_results(results, REFS, evaluate_fn=lambda s: [row(f=0.8)], model_name="m", embedding_name="e")
        assert results[0]["ragas"]["faithfulness"] == 0.8 and "ragas" not in results[1]
        assert summary["scored"] == 1 and summary["judge_model"] == "m"

    @test
    def 채점할_것이_없으면_ragas를_부르지_않는다():
        called = []
        summary = ragas_results([{"id": "e07", "type": "no_answer", "question": "q", "answer": "a"}], REFS,
                                evaluate_fn=lambda s: called.append(1) or [])
        assert not called and summary["scored"] == 0

    @test
    def 호환_처리는_ragas를_불러올_수_있게_하고_통계_전송을_끈다():
        ragas_compat.install()
        ragas_compat.install()   # 두 번 불러도 같다
        assert os.environ.get("RAGAS_DO_NOT_TRACK", "").lower() == "true", "ragas 사용 통계 전송이 켜져 있음"
        import ragas.llms  # noqa: F401  (호환 처리 없이는 ImportError)
        import ragas.metrics._faithfulness  # noqa: F401

    @test
    def 결과_파일이_없으면_안내하고_종료한다():
        assert ragas_eval.main(["--round", "99", "--results", str(Path(tempfile.mkdtemp()) / "none.json")]) == 1

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
