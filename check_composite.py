"""복합 질문 처리 확인 (TASKS 3-3): 같은 에이전트가 도구를 연달아 호출해 종합 답변한다.

실제 Bedrock 모델을 호출한다. 호출 순서(tools_called)까지 본다. 실행: python check_composite.py
"""
import sys

from agent import build_agent, run_agent
from refund import RefundSession

# (질문, 기대 도구 호출 순서, 답변에 있어야 하는 말, 기대 outcome 목록)
CASES = [
    ("ORD-1001 배송 확인하고 환불 접수해줘", ["track_shipment", "request_refund"], ["서울 허브 터미널", "승인"], ["ok", "pending"]),
    ("ORD-1001 배송이 늦는데 확인하고 환불 접수까지 해줘", ["track_shipment", "request_refund"], ["승인"], ["ok", "pending"]),
    ("ORD-1002 주문 내용 확인하고 환불 접수해줘", ["get_order", "request_refund"], ["무선 청소기", "승인"], ["ok", "pending"]),
    ("ORD-1001 주문 내용이랑 배송 상태를 같이 알려줘", ["get_order", "track_shipment"], ["노트북", "서울 허브 터미널"], ["ok", "ok"]),
    ("ORD-1002 환불 가능한지 정책이랑 내 주문 기준으로 알려줘", ["get_order"], ["7일", "(출처: 환불 정책"], ["ok"]),
]


def main():
    failed = 0
    for question, want_tools, words, want_outcomes in CASES:
        agent, calls, searched = build_agent(RefundSession("C001"))
        r = run_agent(agent, calls, searched, question)
        outcomes = [c["outcome"] for c in r["calls"] if c["tool"] != "search_policy"]
        ok = (r["tools_called"] == want_tools and outcomes == want_outcomes
              and all(w in r["answer"] for w in words))
        failed += not ok
        print("통과" if ok else "실패", "|", question, "|", r["tools_called"], outcomes)
        if not ok:
            print("   답변:", r["answer"].replace("\n", " / ")[:200])
    print(f"{len(CASES) - failed}/{len(CASES)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
