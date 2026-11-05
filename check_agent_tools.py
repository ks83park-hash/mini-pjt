"""도구 3종 등록 확인 (TASKS 3-1): 도구 3개가 이름·설명과 함께 목록에 나오고 각각 직접 호출된다."""
import sys

from agent_tools import build_tools
from ownership import BLOCKED_REPLY
from refund import RefundSession


def main():
    session, calls = RefundSession("C001"), []
    by_name = {t.name: t for t in build_tools(session, calls)}

    print("도구 목록:")
    for t in by_name.values():
        print(f" - {t.name}: {t.description[:60]}...")
    assert set(by_name) == {"get_order", "track_shipment", "request_refund"}
    assert all("언제 쓰나" in t.description for t in by_name.values()), "설명에 '언제 쓰나'가 없음"
    assert set(by_name["request_refund"].args) == {"order_id", "reason"}
    assert all("customer_id" not in t.args for t in by_name.values()), "고객 ID를 모델이 넘길 수 있음"

    out = by_name["get_order"].invoke({"order_id": "ORD-1001"})
    assert "노트북" in out
    out = by_name["track_shipment"].invoke({"number": "ORD-1001"})
    assert "서울 허브 터미널" in out
    out = by_name["request_refund"].invoke({"order_id": "ORD-1002", "reason": "단순 변심"})
    assert "접수" in out and session.count == 1

    # 타인 주문은 도구 실행 앞에서 차단된다
    assert by_name["get_order"].invoke({"order_id": "ORD-1003"}) == BLOCKED_REPLY
    assert by_name["track_shipment"].invoke({"number": "ORD-1003"}) == BLOCKED_REPLY
    assert by_name["request_refund"].invoke({"order_id": "ORD-1003", "reason": "단순 변심"}) == BLOCKED_REPLY

    assert [(c["tool"], c["outcome"]) for c in calls] == [
        ("get_order", "ok"),
        ("track_shipment", "ok"),
        ("request_refund", "pending"),
        ("get_order", "blocked"),
        ("track_shipment", "blocked"),
        ("request_refund", "blocked"),
    ], calls
    assert all(c["message"] == BLOCKED_REPLY for c in calls if c["outcome"] == "blocked"), "차단 문구가 기록되지 않음"
    assert "승인" in [c for c in calls if c["outcome"] == "pending"][0]["message"], "승인 대기 안내가 기록되지 않음"
    # 오류가 나도 예외 없이 문자열
    bad = {t.name: t for t in build_tools(RefundSession("C001"), data_dir="없는폴더")}
    assert isinstance(bad["get_order"].invoke({"order_id": "ORD-1001"}), str)
    print("통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
