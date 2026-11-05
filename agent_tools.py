"""에이전트에 붙일 도구 3종 (get_order, track_shipment, request_refund).

- 2-2~2-5에서 만든 함수를 LangChain 도구로 묶는다. 이름과 설명(언제 쓰는지)은 함수 docstring을 그대로 쓴다.
- 대화마다 build_tools(session)을 불러 새로 만든다. session(RefundSession)이 로그인 고객과 환불 접수 상태를 든다.
- 본인 주문 확인(ownership.check_owner)을 주문·배송 도구 실행 앞에 붙인다. 환불 접수는 refund.py 안에서 확인한다.
- 고객 ID는 도구 인자로 받지 않는다 (모델이 바꿀 수 없게 session에서만 읽는다).
- calls 리스트를 주면 호출마다 {"tool", "outcome", "approval_id", "ms", "message"}를 쌓는다 (ms는 걸린 시간)(message는 차단·승인 대기 안내 문구, 그 두 경우에만). 응답의 tools_called와 status(blocked/approval_required)에 쓴다.
  outcome: ok(정상) / blocked(차단) / pending(환불 승인 대기)
- 도구는 예외를 밖으로 던지지 않고 안내 문자열을 돌려준다.
"""
import time

from ownership import check_owner
from refund import prepare_refund, request_refund
from tools import get_order, track_shipment


def build_tools(session, calls=None, data_dir=None):
    """도구 3개 리스트를 만든다. 모듈 최상단에서 만들지 않고 호출할 때 만든다."""
    from langchain_core.tools import StructuredTool

    calls = calls if calls is not None else []

    def record(name, outcome, t0, message="", approval_id=None):
        # t0: 이 호출이 시작된 시각. 호출마다 따로 들고 있어서 도구가 병렬로 불려도 시간이 섞이지 않는다.
        calls.append({"tool": name, "outcome": outcome, "approval_id": approval_id,
                      "ms": round((time.perf_counter() - t0) * 1000),
                      "message": message if outcome in ("blocked", "pending") else ""})

    def guarded(name, fn, number):
        t0 = time.perf_counter()
        allowed, why = check_owner(session.customer_id, number, data_dir)
        if not allowed:
            record(name, "blocked", t0, why)
            return why
        text = fn(number, data_dir=data_dir)
        record(name, "ok", t0)
        return text

    def get_order_tool(order_id: str) -> str:
        return guarded("get_order", get_order, order_id)

    def track_shipment_tool(number: str) -> str:
        return guarded("track_shipment", track_shipment, number)

    def request_refund_tool(order_id: str, reason: str = "사유 미기재") -> str:
        t0 = time.perf_counter()
        result = prepare_refund(session, order_id, reason or "사유 미기재", data_dir)
        record("request_refund", {"pending": "pending", "blocked": "blocked"}.get(result["status"], "ok"), t0,
               result["message"], (result["request"] or {}).get("approval_id"))
        return result["message"]

    # 도구 설명은 원래 함수의 docstring(언제 쓰는지 포함)을 쓴다.
    specs = [
        (get_order_tool, "get_order", get_order.__doc__),
        (track_shipment_tool, "track_shipment", track_shipment.__doc__),
        (request_refund_tool, "request_refund", request_refund.__doc__),
    ]
    return [
        StructuredTool.from_function(func=fn, name=name, description=" ".join(doc.split()))
        for fn, name, doc in specs
    ]
