"""환불 접수 함수와 대량 환불 규칙 (판정은 모두 Python 코드, LLM이 아니다).

- 대량 환불 규칙: 한 대화에서 접수 3건째부터 차단, 이번 건까지 합계가 50만 원을 넘으면 차단.
  (이번 건 포함 합계가 정확히 50만 원이면 허용)
- 접수는 "요청 생성"까지만 한다. 환불 기록(data/refunds.json)은 만들지 않는다.
  session.store가 있으면 접수마다 approval_id를 발급해 승인 대기로 저장한다 (approvals.py).
  승인(approve/modify/reject) 처리와 기록 생성은 4-2에서 붙인다. 승인 전에는 실행되지 않는다.
- 대화 상태는 RefundSession이 들고 있다 (대화마다 하나, 호출하는 쪽이 만든다).
- 차단된 시도는 건수·합계에 넣지 않는다. 접수된 요청만 센다.
- 도구는 예외를 밖으로 던지지 않는다. 모르는 오류는 안전한 쪽(접수 안 됨)으로 처리한다.
"""
import threading

from ownership import check_owner
from tools import NOT_FOUND, _load, find_order

MAX_REFUNDS_PER_CONVERSATION = 3   # 이 건수째부터 차단 (2건까지 허용)
MAX_TOTAL_AMOUNT = 500_000         # 이 금액을 넘으면 차단
ACTIVE_REFUND_STATUSES = {"접수", "승인", "완료"}  # 이미 처리 중이거나 끝난 환불

COUNT_BLOCKED = "한 번의 대화에서 환불은 2건까지만 접수할 수 있습니다. 상담원 문의를 이용해 주세요."
TOTAL_BLOCKED = "한 번의 대화에서 환불 합계가 500,000원을 넘을 수 없어 접수할 수 없습니다. 상담원 문의를 이용해 주세요."
REFUND_ERROR = "환불 접수 중 문제가 생겨 접수하지 못했습니다. 잠시 후 다시 시도해 주세요."


class RefundSession:
    """한 대화의 환불 접수 상태. customer_id는 로그인한 고객(더미 세션)이다."""

    def __init__(self, customer_id, store=None, conversation_id=None):
        self.customer_id = customer_id
        self.store = store                    # ApprovalStore. 있으면 접수마다 approval_id를 발급해 저장한다
        self.conversation_id = conversation_id
        # 에이전트가 환불 도구를 동시에(병렬로) 부르면 "한도 검사 -> 접수"가 겹쳐 대량 환불 규칙이 뚫린다.
        # 검사부터 접수까지를 이 잠금으로 한 번에 한 호출씩만 지나가게 한다.
        self.lock = threading.Lock()
        self.requests = []  # 접수된 요청: {"order_id", "amount", "reason", "status"}

    @property
    def count(self):
        return len(self.requests)

    @property
    def total(self):
        return sum(r["amount"] for r in self.requests)


def check_refund_limit(count, total, new_amount):
    """대량 환불 규칙. 지금까지의 접수 건수·합계와 이번 금액을 받아 (허용 여부, 사유 문구)를 돌려준다."""
    if count + 1 >= MAX_REFUNDS_PER_CONVERSATION:
        return False, COUNT_BLOCKED
    if total + new_amount > MAX_TOTAL_AMOUNT:
        return False, TOTAL_BLOCKED
    return True, ""


def prepare_refund(session, order_id, reason, data_dir=None):
    """환불 요청을 만든다. {"status": "pending"|"blocked"|"error", "message": str, "request": dict|None}를 돌려준다.

    pending이면 승인 대기 요청이 session에 쌓인 것이다 (환불 기록은 아직 없다).
    """
    def result(status, message, request=None):
        return {"status": status, "message": message, "request": request}

    try:
        allowed, why = check_owner(session.customer_id, order_id, data_dir)
        if not allowed:
            return result("blocked", why)
        order = find_order(order_id, data_dir)
        if order is None:
            return result("error", NOT_FOUND)
        if not str(reason or "").strip():
            return result("error", "환불 사유를 알려 주세요. (예: 단순 변심, 상품 불량, 오배송)")
        with session.lock:  # 중복·한도 검사부터 접수까지를 한 번에 한 호출씩 (병렬 호출 대비)
            if any(r["order_id"] == order["order_id"] for r in session.requests):
                return result("error", f"주문 {order['order_id']}은(는) 이미 환불 접수 대기 중입니다.")
            if any(r["order_id"] == order["order_id"] and r["status"] in ACTIVE_REFUND_STATUSES
                   for r in _load("refunds.json", data_dir)):
                return result("error", f"주문 {order['order_id']}은(는) 이미 환불이 접수되어 처리 중이거나 완료되었습니다.")
            ok, why = check_refund_limit(session.count, session.total, order["amount"])
            if not ok:
                return result("blocked", why)
            request = {"order_id": order["order_id"], "amount": order["amount"],
                       "reason": str(reason).strip(), "status": "pending"}
            notice = ""
            if session.store is not None:
                # 저장에 실패하면 예외 -> 아래 except에서 "접수 안 됨"으로 처리되고 session에도 쌓이지 않는다.
                request["approval_id"] = session.store.create(request, session.customer_id, session.conversation_id)
                notice = f" (승인 번호: {request['approval_id']})"
            session.requests.append(request)
            return result("pending", (
                f"환불 요청을 접수했습니다. 주문 {order['order_id']}({order['product']}, {order['amount']:,}원), "
                f"사유: {request['reason']}. 상담원 승인 후에 처리됩니다.{notice}"
            ), request)
    except Exception:  # 모르는 오류는 안전한 쪽(접수 안 됨)
        return result("error", REFUND_ERROR)


def request_refund(session, order_id, reason, data_dir=None):
    """주문번호와 사유로 환불 요청을 만든다.

    언제 쓰나: 고객이 "ORD-1002 환불해줘", "이 상품 반품할래요"처럼 환불을 요청할 때.
    환불 가능 기간·비용 같은 정책 질문에는 쓰지 않는다(정책 문서를 검색한다).
    접수만 하며 실제 환불은 상담원 승인 뒤에 처리된다.
    """
    return prepare_refund(session, order_id, reason, data_dir)["message"]
