"""RAGAS 지표 검증 (TASKS 5-4 확인): 4개 지표가 숫자로 나오고, 좋은 경우와 나쁜 경우를 가르는지 실제 모델로 본다.

실제 Bedrock 모델(심사 LLM)과 Titan 임베딩을 호출한다. 실행: python check_ragas_real.py
answer_relevancy는 이 환경에서 변별력이 없어(ragas_eval.py 참고) 점수가 숫자로 나오는지만 본다.
"""
import sys

import ragas_compat

ragas_compat.install()

from check_judge_real import section  # noqa: E402  (정책 문서 섹션을 근거 문장으로 읽는 함수)
from ragas_eval import METRIC_COLUMNS, score_samples  # noqa: E402

REFUND_PERIOD = section("refund_policy.md", "신청 기간")
REFUND_PROCESS = section("refund_policy.md", "처리 절차")
EXCHANGE_COND = section("exchange_policy.md", "신청 조건")
SHIPPING_PERIOD = section("shipping_policy.md", "소요 기간")
SEVEN_DAYS_ONLY = "환불 정책 > 신청 기간\n단순 변심으로 인한 환불은 상품 수령 후 7일 이내에 신청할 수 있습니다."

Q = "환불은 수령 후 며칠 이내에 가능한가요?"
GOOD = "단순 변심은 상품 수령 후 7일 이내, 상품 불량이나 오배송은 30일 이내에 신청할 수 있습니다."
REF = "단순 변심으로 인한 환불은 상품 수령 후 7일 이내에, 상품 불량 또는 오배송으로 인한 환불은 상품 수령 후 30일 이내에 신청할 수 있다."

# (이름, 답변, 근거 목록, 기대 조건). 조건: {지표: ("이상"|"이하", 점수)}
CASES = [
    ("좋은 검색 + 좋은 답변", GOOD, [REFUND_PERIOD, REFUND_PROCESS],
     {"faithfulness": ("이상", 0.8), "context_precision": ("이상", 0.8), "context_recall": ("이상", 0.8)}),
    ("숫자가 틀린 답변", "단순 변심 환불은 상품 수령 후 14일 이내에 신청할 수 있습니다.", [REFUND_PERIOD],
     {"faithfulness": ("이하", 0.5)}),
    ("검색 실패(관련 없는 근거만)", GOOD, [SHIPPING_PERIOD, EXCHANGE_COND],
     {"context_recall": ("이하", 0.3), "faithfulness": ("이하", 0.5)}),
    ("관련 근거가 맨 뒤로 밀린 검색", GOOD, [SHIPPING_PERIOD, EXCHANGE_COND, REFUND_PERIOD],
     {"context_precision": ("이하", 0.6), "context_recall": ("이상", 0.8)}),
    ("필요한 내용 일부만 검색됨", GOOD, [SEVEN_DAYS_ONLY],
     {"context_recall": ("이하", 0.7)}),
]


def main():
    samples = [{"id": name, "user_input": Q, "response": answer, "retrieved_contexts": ctx, "reference": REF}
               for name, answer, ctx, _ in CASES]
    scores = score_samples(samples)
    failed = 0
    for (name, _, _, expect), score in zip(CASES, scores):
        problems = []
        for metric in METRIC_COLUMNS:
            if score[metric] is None:
                problems.append(f"{metric} 점수가 없음")
        for metric, (direction, bound) in expect.items():
            value = score[metric]
            ok = value is not None and (value >= bound if direction == "이상" else value <= bound)
            if not ok:
                problems.append(f"{metric}={value} (기대: {bound} {direction})")
        failed += bool(problems)
        shown = " ".join(f"{m}={score[m]}" for m in METRIC_COLUMNS)
        print(f"{'통과' if not problems else '실패'}  {name}\n        {shown}" + (f"\n        <- {'; '.join(problems)}" if problems else ""))
    print(f"\n{len(CASES) - failed}/{len(CASES)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
