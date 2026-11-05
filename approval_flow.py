"""환불 승인 처리 (approve / modify / reject) — 규칙 판정은 모두 Python 코드다.

- approve: 요청 금액 그대로 승인 -> 환불 기록(data/refunds.json)을 만든다.
- modify: 승인자가 금액을 낮춰서 승인한다 (요청 금액보다 작은 양의 정수만 허용) -> 낮춘 금액으로 기록을 만든다.
  늘리는 것은 허용하지 않는다 (고객이 요청한 것보다 많이 환불할 수 없다).
- reject: 환불 기록을 만들지 않는다.
- 환불 기록은 approve·modify에서만 생긴다. 승인 전·거절 건에는 생기지 않는다 (성공 기준: 승인 없이 환불 0건).
- 승인자는 더미 상담원 목록(APPROVERS)에 있어야 한다. 새 로그인 체계는 만들지 않는다.
- 같은 건은 한 번만 처리된다 (저장소의 decide가 pending일 때만 바꾼다). 같은 주문에 이미 처리 중이거나
  끝난 환불이 있으면 승인하지 않는다 (중복 환불 방지).
- 기록을 쓰다 실패하면 승인 상태를 pending으로 되돌려, "승인됐는데 기록이 없는" 상태를 남기지 않는다.
- 반환: {"code": HTTP 상태 코드, "status": 결과, "message": 안내 문구, ...}. 예외를 밖으로 던지지 않는다.
"""
import json
import os
import threading
from pathlib import Path

from refund import ACTIVE_REFUND_STATUSES
from tools import DATA_DIR

APPROVERS = {"A001", "A002"}  # 더미 상담원 (SERVICE.md: 상담원 2명)
DECISIONS = {"approve", "modify", "reject"}

# 환불 기록 파일을 쓰는 동안 다른 처리가 끼어들지 못하게 한다 (검사 -> 승인 -> 기록을 한 번에).
_WRITE_LOCK = threading.Lock()


def _refunds_path(data_dir=None):
    return Path(data_dir or DATA_DIR) / "refunds.json"


def _read_refunds(data_dir=None):
    return json.loads(_refunds_path(data_dir).read_text(encoding="utf-8"))


def _write_refunds(rows, data_dir=None):
    """임시 파일에 쓴 뒤 바꿔치기해서, 쓰다가 끊겨도 기존 파일이 깨지지 않게 한다."""
    path = _refunds_path(data_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _next_refund_id(rows):
    numbers = [int(r["refund_id"].split("-")[1]) for r in rows if str(r.get("refund_id", "")).startswith("RF-")]
    return f"RF-{max(numbers, default=0) + 1:03d}"


def _result(code, status, message, **extra):
    return {"code": code, "status": status, "message": message, **extra}


def decide_approval(store, approval_id, approver_id, decision, amount=None, note=None, data_dir=None):
    """승인 대기 한 건을 처리한다. status: approved / modified / rejected / error."""
    try:
        if approver_id not in APPROVERS:
            return _result(403, "error", "승인 권한이 없습니다.")
        if decision not in DECISIONS:
            return _result(422, "error", "decision은 approve, modify, reject 중 하나여야 합니다.")
        item = store.get(approval_id)
        if item is None:
            return _result(404, "error", "해당 승인 번호를 찾을 수 없습니다.")
        if item["status"] != "pending":
            return _result(409, "error", f"이미 처리된 건입니다. (상태: {item['status']})")

        if decision == "reject":
            if not store.decide(approval_id, "rejected", approver_id, None, note):
                return _result(409, "error", "이미 처리된 건입니다.")
            return _result(
                200, "rejected",
                f"주문 {item['order_id']} 환불 요청이 거절되었습니다. 자세한 내용은 상담원에게 문의해 주세요.",
                approval_id=approval_id, refund_id=None,
            )

        final = item["amount"]
        if decision == "modify":
            if isinstance(amount, bool) or not isinstance(amount, int) or not (0 < amount < item["amount"]):
                return _result(
                    422, "error",
                    f"modify는 요청 금액({item['amount']:,}원)보다 작은 양의 정수 금액이 필요합니다.",
                )
            final = amount

        with _WRITE_LOCK:
            rows = _read_refunds(data_dir)
            if any(r["order_id"] == item["order_id"] and r["status"] in ACTIVE_REFUND_STATUSES for r in rows):
                return _result(
                    409, "error",
                    f"주문 {item['order_id']}은(는) 이미 환불이 처리 중이거나 완료되어 승인할 수 없습니다. 거절해 주세요.",
                )
            status = "approved" if decision == "approve" else "modified"
            if not store.decide(approval_id, status, approver_id, final, note):
                return _result(409, "error", "이미 처리된 건입니다.")
            try:
                refund_id = _next_refund_id(rows)
                rows.append({
                    "refund_id": refund_id, "order_id": item["order_id"], "customer_id": item["customer_id"],
                    "amount": final, "reason": item["reason"], "status": "승인", "approval_id": approval_id,
                })
                _write_refunds(rows, data_dir)
                store.set_refund_id(approval_id, refund_id)
            except Exception:  # 기록 실패: 승인 상태를 되돌려 "승인됐는데 기록 없음"을 남기지 않는다
                store.reopen(approval_id)
                return _result(500, "error", "환불 기록을 저장하지 못해 승인을 취소했습니다. 다시 시도해 주세요.")

        if status == "approved":
            message = f"주문 {item['order_id']} 환불 요청이 승인되었습니다. 환불 금액: {final:,}원 (접수번호 {refund_id})."
        else:
            message = (f"주문 {item['order_id']} 환불 요청이 수정 승인되었습니다. "
                       f"요청 {item['amount']:,}원 -> 환불 금액 {final:,}원 (접수번호 {refund_id}).")
        return _result(200, status, message, approval_id=approval_id, refund_id=refund_id, amount=final)
    except Exception:  # 모르는 오류는 안전한 쪽(처리 안 됨)
        return _result(500, "error", "승인 처리 중 문제가 생겼습니다. 다시 시도해 주세요.")
