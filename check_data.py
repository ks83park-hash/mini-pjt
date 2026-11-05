"""더미 데이터 검증 (TASKS 2-1 확인): 건수와 연결이 맞는지 본다. 통과하면 종료 코드 0.

실행: python check_data.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def main():
    customers, orders = load("customers.json"), load("orders.json")
    shipments, refunds = load("shipments.json"), load("refunds.json")
    errors = []

    for label, rows, want in [("고객", customers, 5), ("주문", orders, 15), ("배송", shipments, 12), ("환불", refunds, 5)]:
        if len(rows) != want:
            errors.append(f"{label} 건수 {len(rows)} (기대 {want})")

    cids = {c["customer_id"] for c in customers}
    oids = {o["order_id"] for o in orders}
    trks = {s["tracking_no"] for s in shipments}
    by_order = {o["order_id"]: o for o in orders}

    for o in orders:
        if o["customer_id"] not in cids:
            errors.append(f"{o['order_id']}: 없는 고객 {o['customer_id']}")
        if o["tracking_no"] and o["tracking_no"] not in trks:
            errors.append(f"{o['order_id']}: 없는 운송장 {o['tracking_no']}")
        if o["status"] == "배송 전" and o["tracking_no"]:
            errors.append(f"{o['order_id']}: 배송 전인데 운송장이 있음")
    for s in shipments:
        o = by_order.get(s["order_id"])
        if not o or o["tracking_no"] != s["tracking_no"]:
            errors.append(f"{s['tracking_no']}: 주문 연결이 어긋남")
        elif o["status"] != s["status"]:
            errors.append(f"{s['tracking_no']}: 주문과 배송 상태가 다름")
    for r in refunds:
        o = by_order.get(r["order_id"])
        if not o or o["customer_id"] != r["customer_id"]:
            errors.append(f"{r['refund_id']}: 주문·고객 연결이 어긋남")

    states = Counter(o["status"] for o in orders)
    for need in ("배송 전", "배송 중", "배송 완료"):
        if not states[need]:
            errors.append(f"주문 상태 '{need}'가 없음")

    if errors:
        print("실패:")
        for e in errors:
            print(" -", e)
        return 1
    print(f"통과: 고객 {len(customers)}, 주문 {len(orders)}, 배송 {len(shipments)}, 환불 {len(refunds)}, 주문 상태 {dict(states)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
