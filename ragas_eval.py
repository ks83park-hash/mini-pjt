"""RAGAS 지표 산출: 정책 질문의 답변과 검색 결과를 faithfulness·answer relevancy·context precision·context recall로 채점한다.

| 지표 | 보는 것 | 입력 |
| faithfulness | 답변의 사실이 검색한 근거에 있는가 | 질문, 답변, 근거(contexts) |
| answer_relevancy | 답변이 질문에 맞는가 (답변에서 질문을 만들어 원래 질문과 임베딩 유사도를 잰다) | 질문, 답변 |
| context_precision | 검색한 근거 중 관련 있는 것이 위쪽에 있는가 (순위를 본다) | 질문, 정답 문장, 근거 |
| context_recall | 정답에 필요한 내용이 검색한 근거에 다 있는가 | 질문, 정답 문장, 근거 |

사용하는 것
- 정답 문장(reference)은 평가셋(tests/eval_set.json)의 정책 질문에 있다. 근거(contexts)는 실행 기록에서 온 것으로,
  평가 실행기(run_eval.py)가 결과 파일에 담아 둔다 (그래서 임시 서버 모드나 --trace-file 모드로 실행한 결과여야 한다).
- 심사 LLM은 JUDGE_MODEL_ID(없으면 BEDROCK_MODEL_ID), 임베딩은 EMBEDDING_MODEL_ID(Titan v2)다.
- 답변에서 "(출처: …)" 줄은 뺀다 (출처 표시는 사실 주장이 아니다). 다른 가공은 하지 않는다.

주의: answer_relevancy는 이 환경에서 믿을 수 없다 (reliable=False로 표시한다).
  Titan v2는 한국어에서, 원래 질문과 그 질문에서 만든 알맞은 의역의 유사도(0.20)가 다른 주제의 질문(0.45)보다 낮다.
  그래서 정확한 답변도 0.2 안팎이 나온다. 질문 적합도는 LLM-as-Judge의 relevance(llm_judge.py)로 본다.
  쓸 수 있는 임베딩 모델이 Titan v2뿐이라 바꿀 수 없다 (cohere, titan v1은 접근 권한이 없다).
다른 세 지표는 LLM 심사라서 실행마다 조금 달라질 수 있다 (같은 입력 5번 측정에서는 흔들리지 않았다).

실행: python ragas_eval.py --round 1    (evaluation/round1_results.json에 ragas 점수와 ragas_summary를 써 넣는다)
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

import ragas_compat

ragas_compat.install()  # ragas를 import하기 전에 호환 처리를 한다

ROOT = Path(__file__).parent
EVAL_SET = ROOT / "tests" / "eval_set.json"
POLICY_TYPES = ("fact", "paraphrase")
# 우리가 쓰는 이름 -> ragas 결과 열 이름
METRIC_COLUMNS = {
    "faithfulness": "faithfulness",
    "answer_relevancy": "answer_relevancy",
    "context_precision": "llm_context_precision_with_reference",
    "context_recall": "context_recall",
}
UNRELIABLE = {"answer_relevancy": "Titan v2가 한국어에서 변별력이 없어 참고용 (llm_judge의 relevance를 쓴다)"}
LOW_SCORE = 0.5  # 이 점수 미만이면 사람이 볼 문항으로 표시한다
SOURCE_LINE = re.compile(r"^\s*\(출처:.*\)\s*$")


def clean_response(answer):
    """답변에서 출처 표시 줄만 뺀다."""
    return "\n".join(line for line in str(answer or "").splitlines() if not SOURCE_LINE.match(line)).strip()


def load_references():
    return {c["id"]: c["reference"] for c in json.loads(EVAL_SET.read_text(encoding="utf-8")) if c.get("reference")}


def build_samples(results, references):
    """(채점할 샘플 목록, 건너뛴 문항 {id: 사유})를 돌려준다. 정책 질문만, 근거와 정답 문장이 있는 것만 채점한다."""
    samples, skipped = [], {}
    for r in results:
        if r["type"] not in POLICY_TYPES:
            continue
        if not r.get("answer"):
            skipped[r["id"]] = "답변이 없음"
        elif r["id"] not in references:
            skipped[r["id"]] = "정답 문장(reference)이 없음"
        elif not r.get("contexts"):
            skipped[r["id"]] = "검색한 근거가 없음 (근거 없음 거절이거나 실행 기록이 없음)"
        else:
            samples.append({
                "id": r["id"], "user_input": r["question"], "response": clean_response(r["answer"]),
                "retrieved_contexts": list(r["contexts"]), "reference": references[r["id"]],
            })
    return samples, skipped


def _number(value):
    """점수를 숫자로 바꾼다. 비어 있거나 NaN이면 None (0점으로 채우지 않는다)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else round(value, 3)


def default_evaluate(samples, llm=None, embeddings=None):
    """ragas로 샘플 전체를 채점해 [{지표: 점수}] (샘플 순서대로)를 돌려준다."""
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics._answer_relevance import ResponseRelevancy
    from ragas.metrics._context_precision import LLMContextPrecisionWithReference
    from ragas.metrics._context_recall import LLMContextRecall
    from ragas.metrics._faithfulness import Faithfulness
    from ragas.run_config import RunConfig

    from index import build_embeddings
    from llm_judge import build_judge_llm

    ragas_llm = LangchainLLMWrapper(llm or build_judge_llm())
    ragas_emb = LangchainEmbeddingsWrapper(embeddings or build_embeddings())
    dataset = EvaluationDataset.from_list([{k: s[k] for k in ("user_input", "response", "retrieved_contexts", "reference")}
                                           for s in samples])
    result = evaluate(
        dataset, metrics=[Faithfulness(), ResponseRelevancy(), LLMContextPrecisionWithReference(), LLMContextRecall()],
        llm=ragas_llm, embeddings=ragas_emb, show_progress=False, raise_exceptions=False,
        run_config=RunConfig(timeout=180, max_retries=5, max_workers=2),  # 동시 호출을 줄여 모델 한도에 걸리지 않게 한다 (4일 때 한도 오류가 한 번 났다)
    )
    return result.to_pandas().to_dict("records")


def score_samples(samples, evaluate_fn=None):
    """샘플마다 {지표: 점수 또는 None}을 돌려준다. evaluate_fn을 주입하면 ragas 대신 그것을 쓴다 (테스트용)."""
    rows = (evaluate_fn or default_evaluate)(samples)
    scores = []
    for row in rows:
        scores.append({name: _number(row.get(column)) for name, column in METRIC_COLUMNS.items()})
    if len(scores) != len(samples):
        raise ValueError(f"채점 결과 수({len(scores)})가 샘플 수({len(samples)})와 다름")
    return scores


def summarize_ragas(results, skipped, model_name, embedding_name):
    scored = [r for r in results if r.get("ragas")]
    summary = {"judge_model": model_name, "embedding_model": embedding_name, "scored": len(scored),
               "skipped": skipped, "unreliable": UNRELIABLE}
    for name in METRIC_COLUMNS:
        values = [r["ragas"][name] for r in scored if r["ragas"].get(name) is not None]
        summary[f"{name}_avg"] = round(sum(values) / len(values), 3) if values else None
        summary[f"{name}_n"] = len(values)
    summary["low_cases"] = [
        {"id": r["id"], **{n: r["ragas"][n] for n in METRIC_COLUMNS if n != "answer_relevancy" and r["ragas"].get(n) is not None}}
        for r in scored
        if any(r["ragas"].get(n) is not None and r["ragas"][n] < LOW_SCORE for n in METRIC_COLUMNS if n != "answer_relevancy")
    ]
    return summary


def ragas_results(results, references=None, evaluate_fn=None, model_name=None, embedding_name=None):
    """결과 목록의 정책 질문에 ragas 점수를 붙이고 요약을 돌려준다 (results를 직접 고친다)."""
    from config import load_settings

    settings = load_settings()
    samples, skipped = build_samples(results, references if references is not None else load_references())
    by_id = {r["id"]: r for r in results}
    if samples:
        for sample, score in zip(samples, score_samples(samples, evaluate_fn)):
            by_id[sample["id"]]["ragas"] = score
    return summarize_ragas(
        results, skipped, model_name or settings.get("JUDGE_MODEL_ID") or settings["BEDROCK_MODEL_ID"],
        embedding_name or settings["EMBEDDING_MODEL_ID"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="평가 결과의 정책 질문을 RAGAS 지표로 채점한다.")
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--results", help="결과 파일 경로 (기본: evaluation/roundN_results.json)")
    args = parser.parse_args(argv)
    path = Path(args.results) if args.results else ROOT / "evaluation" / f"round{args.round}_results.json"
    if not path.exists():
        print(f"결과 파일이 없습니다: {path}  (먼저 python run_eval.py --round {args.round})")
        return 1
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = ragas_results(payload["results"])
    payload["ragas_summary"] = summary
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"심사 모델: {summary['judge_model']} / 임베딩: {summary['embedding_model']}")
    print(f"채점 {summary['scored']}건, 건너뜀 {len(summary['skipped'])}건 {summary['skipped'] or ''}")
    for name in METRIC_COLUMNS:
        note = f"  (참고용: {UNRELIABLE[name]})" if name in UNRELIABLE else ""
        print(f"  {name:<18} 평균 {summary[f'{name}_avg']} ({summary[f'{name}_n']}건){note}")
    if summary["low_cases"]:
        print(f"낮은 점수(< {LOW_SCORE}) 문항: {summary['low_cases']}")
    print(f"결과 저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
