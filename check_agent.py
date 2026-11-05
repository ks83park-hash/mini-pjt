"""에이전트 1개 조립 확인 (TASKS 3-2): 주문 질문은 주문 조회 도구가 1번 호출되고, 환불 기간 질문은 도구 없이 출처가 붙는다.

실제 Bedrock 모델을 호출한다. 실행: python check_agent.py
"""
import sys

from agent import build_agent, run_agent
from ownership import BLOCKED_REPLY
from refund import RefundSession


def ask(question, customer_id="C001"):
    agent, calls, searched = build_agent(RefundSession(customer_id))
    return run_agent(agent, calls, searched, question)


def main():
    results = {}
    cases = [
        ("ORD-1001 어떤 상품이야?", lambda r: r["tools_called"] == ["get_order"] and "노트북" in r["answer"]),
        ("환불 기간 알려줘", lambda r: r["tools_called"] == [] and "(출처: 환불 정책)" in r["answer"] and "7일" in r["answer"]),
        ("내일 서울 날씨 알려줘", lambda r: r["tools_called"] == [] and "담당 범위가 아닙니다" in r["answer"] and "(출처:" not in r["answer"]),
        ("ORD-1002 운송장 번호가 뭐야?", lambda r: "track_shipment" in r["tools_called"] and "TRK-9002" in r["answer"] and "마이페이지" not in r["answer"]),
        ("ORD-1003 배송 어디야?", lambda r: r["calls"] and r["calls"][0]["outcome"] == "blocked" and r["answer"] == BLOCKED_REPLY),
    ]
    failed = 0
    for q, check in cases:
        r = ask(q)
        ok = bool(check(r))
        failed += not ok
        print(("통과" if ok else "실패"), "|", q, "|", r["tools_called"], "|", r["answer"].replace("\n", " / ")[:150])
    print(f"{len(cases) - failed}/{len(cases)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
