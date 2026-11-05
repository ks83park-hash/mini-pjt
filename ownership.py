"""본인 주문 확인 규칙 (결정적 규칙, LLM을 쓰지 않는다).

더미 세션의 고객 ID(로그인한 고객)와 주문 소유자를 Python 코드로 비교한다.
- 주문번호든 운송장 번호든 받아서, 연결된 주문의 소유자를 확인한다.
- 소유자가 다르거나 로그인 정보(고객 ID)가 없으면 차단한다. 모르는 오류도 차단(안전한 쪽)이다.
- 존재하지 않는 번호는 소유자가 없으므로 통과시키고, 도구가 "찾을 수 없음"으로 안내한다.
- 차단 사유는 고정 문구로만 보여준다. 누구의 주문인지는 어디에도 노출하지 않는다.
- 도구 실행 앞에서 이 함수를 먼저 부른다 (3-1에서 도구에 연결).
"""
from tools import _load, find_order, normalize_tracking_no

BLOCKED_REPLY = "본인의 주문만 조회할 수 있습니다. 로그인한 계정의 주문번호를 확인해 주세요."


def owner_of(number, data_dir=None):
    """주문번호 또는 운송장 번호에 연결된 주문의 고객 ID를 돌려준다. 못 찾으면 None."""
    order = find_order(number, data_dir)
    if order:
        return order["customer_id"]
    tracking_no = normalize_tracking_no(number)
    if tracking_no:
        shipment = next((s for s in _load("shipments.json", data_dir) if s["tracking_no"] == tracking_no), None)
        if shipment:
            order = find_order(shipment["order_id"], data_dir)
            return order["customer_id"] if order else None
    return None


def check_owner(customer_id, number, data_dir=None):
    """(허용 여부, 안내 문구)를 돌려준다. 허용이면 안내 문구는 빈 문자열이다."""
    try:
        if not customer_id:
            return False, BLOCKED_REPLY
        owner = owner_of(number, data_dir)
        if owner is None or owner == customer_id:
            return True, ""
        return False, BLOCKED_REPLY
    except Exception:  # 모르는 오류는 안전한 쪽(차단)
        return False, BLOCKED_REPLY
