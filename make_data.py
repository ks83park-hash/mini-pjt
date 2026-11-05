"""더미 데이터 생성기: 고객·주문·배송·환불 JSON을 data/ 에 만든다.

- 모든 값은 가상이다 (이름·전화번호·주소 포함). 실제 고객 정보는 쓰지 않는다.
- 기준일(TODAY)을 고정해 두어 실행할 때마다 같은 데이터가 나온다.
- 종류별 20개 이하: 고객 5, 주문 15, 배송 12, 환불 5.
- 주문 상태가 고르게 섞인다: 배송 전 3, 배송 중 5, 배송 완료 7(환불 가능/불가 포함).

실행: python make_data.py
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
TODAY = "2026-11-05"  # 환불 기간(수령 후 7일) 판정의 기준일

CUSTOMERS = [
    {"customer_id": "C001", "name": "김하늘", "phone": "010-0000-0001", "email": "c001@example.com", "address": "서울시 가나구 다라로 1"},
    {"customer_id": "C002", "name": "이바다", "phone": "010-0000-0002", "email": "c002@example.com", "address": "부산시 마바구 사아로 2"},
    {"customer_id": "C003", "name": "박나무", "phone": "010-0000-0003", "email": "c003@example.com", "address": "대구시 자차구 카타로 3"},
    {"customer_id": "C004", "name": "최구름", "phone": "010-0000-0004", "email": "c004@example.com", "address": "제주시 파하구 거너로 4"},
    {"customer_id": "C005", "name": "정바람", "phone": "010-0000-0005", "email": "c005@example.com", "address": "인천시 더러구 머버로 5"},
]

# (주문번호, 고객, 상품, 금액, 상태, 주문일, 수령일, 개봉/사용 여부, 운송장)
# 상태: 배송 전 / 배송 중 / 배송 완료. 운송장이 없으면 배송 전이다.
_ORDERS = [
    ("ORD-1001", "C001", "노트북", 320000, "배송 중", "2026-11-02", None, False, "TRK-9001"),
    ("ORD-1002", "C001", "무선 청소기", 280000, "배송 완료", "2026-10-30", "2026-11-03", False, "TRK-9002"),
    ("ORD-1003", "C002", "운동화", 89000, "배송 중", "2026-11-03", None, False, "TRK-9003"),
    ("ORD-1004", "C001", "텀블러", 25000, "배송 전", "2026-11-05", None, False, None),
    ("ORD-1005", "C002", "블루투스 이어폰", 59000, "배송 완료", "2026-10-15", "2026-10-20", False, "TRK-9004"),
    ("ORD-1006", "C002", "백팩", 74000, "배송 전", "2026-11-05", None, False, None),
    ("ORD-1007", "C003", "전기 포트", 38000, "배송 완료", "2026-11-01", "2026-11-04", False, "TRK-9005"),
    ("ORD-1008", "C003", "수건 세트", 22000, "배송 중", "2026-11-03", None, False, "TRK-9006"),
    ("ORD-1009", "C003", "향초", 18000, "배송 완료", "2026-10-05", "2026-10-10", True, "TRK-9007"),
    ("ORD-1010", "C004", "책상 조명", 46000, "배송 완료", "2026-10-28", "2026-11-01", False, "TRK-9008"),
    ("ORD-1011", "C004", "에코백", 12000, "배송 전", "2026-11-05", None, False, None),
    ("ORD-1012", "C004", "모니터", 210000, "배송 중", "2026-11-01", None, False, "TRK-9009"),
    ("ORD-1013", "C005", "키보드", 95000, "배송 완료", "2026-10-24", "2026-10-28", False, "TRK-9010"),
    ("ORD-1014", "C005", "머그컵 세트", 31000, "배송 완료", "2026-10-30", "2026-11-02", False, "TRK-9011"),
    ("ORD-1015", "C005", "공기청정기", 150000, "배송 중", "2026-11-02", None, False, "TRK-9012"),
]

# 운송장별 (택배사, 현재 위치, 예상 도착일). 배송 완료는 도착일이 수령일이다.
_TRACKING = {
    "TRK-9001": ("가상택배", "서울 허브 터미널", "2026-11-07"),
    "TRK-9003": ("가상택배", "부산 배송 출발", "2026-11-06"),
    "TRK-9006": ("가상택배", "대구 허브 터미널", "2026-11-07"),
    "TRK-9009": ("가상택배", "제주 도착 대기", "2026-11-08"),
    "TRK-9012": ("가상택배", "인천 허브 터미널", "2026-11-07"),
}

# (환불번호, 주문, 사유, 상태)
_REFUNDS = [
    ("RF-001", "ORD-1005", "단순 변심", "거절"),   # 수령 후 7일 초과
    ("RF-002", "ORD-1009", "단순 변심", "거절"),   # 개봉한 상품
    ("RF-003", "ORD-1013", "상품 불량", "완료"),   # 불량은 30일 이내
    ("RF-004", "ORD-1007", "단순 변심", "승인"),
    ("RF-005", "ORD-1010", "오배송", "접수"),
]


def build_orders():
    return [
        {
            "order_id": oid, "customer_id": cid, "product": product, "amount": amount,
            "status": status, "ordered_at": ordered, "delivered_at": delivered,
            "opened": opened, "tracking_no": trk,
        }
        for oid, cid, product, amount, status, ordered, delivered, opened, trk in _ORDERS
    ]


def build_shipments():
    shipments = []
    for oid, _cid, _p, _a, status, _o, delivered, _op, trk in _ORDERS:
        if not trk:
            continue
        carrier, location, eta = _TRACKING.get(trk, ("가상택배", "수령 완료", delivered))
        shipments.append({
            "tracking_no": trk, "order_id": oid, "carrier": carrier,
            "status": status, "location": location, "eta": eta,
        })
    return shipments


def build_refunds():
    amounts = {o[0]: o[3] for o in _ORDERS}
    owners = {o[0]: o[1] for o in _ORDERS}
    return [
        {"refund_id": rid, "order_id": oid, "customer_id": owners[oid],
         "amount": amounts[oid], "reason": reason, "status": status}
        for rid, oid, reason, status in _REFUNDS
    ]


def main():
    DATA_DIR.mkdir(exist_ok=True)
    files = {
        "customers.json": CUSTOMERS, "orders.json": build_orders(),
        "shipments.json": build_shipments(), "refunds.json": build_refunds(),
    }
    for name, rows in files.items():
        (DATA_DIR / name).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{name}: {len(rows)}건")


if __name__ == "__main__":
    main()
