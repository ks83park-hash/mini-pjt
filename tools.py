"""에이전트가 쓰는 도구 함수 모음 (묶음 2에서 하나씩 채운다).

규칙
- 도구는 예외를 밖으로 던지지 않고 안내 문자열을 돌려준다. 모르는 오류는 안전한 쪽(조회 실패 안내)으로 처리한다.
- 도구 설명(docstring)에 "언제 쓰는지"를 적어 에이전트가 도구를 고르게 한다.
- 데이터는 호출할 때 읽는다 (모듈 최상단에서 파일을 읽지 않는다). data_dir로 다른 폴더를 주입할 수 있다.
- 본인 주문 확인(2-4)과 환불 규칙(2-5)은 이 함수들 앞뒤에 따로 붙인다.
"""
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

NOT_FOUND = "해당 주문번호를 찾을 수 없습니다. 주문번호(예: ORD-1001)를 다시 확인해 주세요."
LOOKUP_ERROR = "주문 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."


def _load(name, data_dir=None):
    return json.loads((Path(data_dir or DATA_DIR) / name).read_text(encoding="utf-8"))


def normalize_order_id(text):
    """'ord-1001', ' 1001 ' 같은 입력을 'ORD-1001'로 맞춘다. 형식이 아니면 None."""
    match = re.fullmatch(r"(?:ORD-?)?(\d{4})", str(text).strip().upper())
    return f"ORD-{match.group(1)}" if match else None


def find_order(order_id, data_dir=None):
    """주문 dict를 찾아 돌려준다. 없으면 None. (소유자 확인 등 다른 규칙에서도 쓴다)"""
    oid = normalize_order_id(order_id)
    if not oid:
        return None
    return next((o for o in _load("orders.json", data_dir) if o["order_id"] == oid), None)


def get_order(order_id, data_dir=None):
    """주문번호로 주문의 상품·금액·상태를 조회한다.

    언제 쓰나: 고객이 "주문 ORD-1001 어떤 상품이야", "내 주문 상태 알려줘"처럼
    주문 내용(상품, 금액, 상태, 주문일)을 물을 때. 이 도구는 운송장 번호·배송 위치·도착 예정일을 알지 못한다.
    그런 것을 물으면 track_shipment를 쓴다.
    """
    try:
        order = find_order(order_id, data_dir)
        if order is None:
            return NOT_FOUND
        lines = [
            f"주문번호: {order['order_id']}",
            f"상품: {order['product']}",
            f"금액: {order['amount']:,}원",
            f"상태: {order['status']}",
            f"주문일: {order['ordered_at']}",
        ]
        if order["delivered_at"]:
            lines.append(f"수령일: {order['delivered_at']}")
        return "\n".join(lines)
    except Exception:  # 모르는 오류는 내용을 노출하지 않고 안내 문구로
        return LOOKUP_ERROR


SHIPMENT_NOT_FOUND = "해당 번호의 배송 정보를 찾을 수 없습니다. 주문번호(예: ORD-1001) 또는 운송장 번호(예: TRK-9001)를 확인해 주세요."
SHIPMENT_ERROR = "배송 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."


def normalize_tracking_no(text):
    """'trk-9001', ' 9001 ' 같은 입력을 'TRK-9001'로 맞춘다. 형식이 아니면 None."""
    match = re.fullmatch(r"TRK-?(\d{4})", str(text).strip().upper())
    return f"TRK-{match.group(1)}" if match else None


def track_shipment(number, data_dir=None):
    """운송장 번호 또는 주문번호로 배송 위치와 예상 도착일을 조회한다.

    언제 쓰나: 고객이 "ORD-1001 배송 어디쯤이야", "택배 언제 와요", "운송장(송장) 번호 알려줘"처럼
    운송장 번호·배송 위치·예상 도착일·배송 진행 상태를 물을 때. 상품·금액 같은 주문 내용은 get_order를 쓴다.
    주문번호를 받으면 그 주문의 운송장을 찾아 조회한다. 아직 발송 전이면 발송 전이라고 안내한다.
    """
    try:
        order = find_order(number, data_dir)
        tracking_no = order["tracking_no"] if order else normalize_tracking_no(number)
        if order and not tracking_no:
            return f"주문 {order['order_id']}은(는) 아직 발송 전입니다. 발송되면 운송장 번호가 생성됩니다."
        shipment = next(
            (s for s in _load("shipments.json", data_dir) if s["tracking_no"] == tracking_no), None
        )
        if shipment is None:
            return SHIPMENT_NOT_FOUND
        if shipment["status"] == "배송 완료":
            tail = f"수령일: {shipment['eta']}"
        else:
            tail = f"예상 도착일: {shipment['eta']}"
        return "\n".join([
            f"운송장: {shipment['tracking_no']} ({shipment['carrier']})",
            f"주문번호: {shipment['order_id']}",
            f"상태: {shipment['status']}",
            f"현재 위치: {shipment['location']}",
            tail,
        ])
    except Exception:  # 모르는 오류는 내용을 노출하지 않고 안내 문구로
        return SHIPMENT_ERROR
