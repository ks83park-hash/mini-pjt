"""POST /query, POST /approve (FastAPI) — 에이전트(도구 3종 + 정책 검색)와 환불 승인.

요청: {"question": str, "customer_id": str(선택), "conversation_id": str(선택)}
응답: {"answer": str, "status": "ok"|"blocked"|"approval_required"|"error", "tools_called": [str]}
      status가 approval_required이면 "approval_id"(첫 건)와 "approval_ids"(이번 요청에서 접수된 전체)가 함께 온다.
- customer_id는 로그인한 고객(더미 세션)이다. 도구의 본인 확인에 쓰이며, 없으면 주문 도구는 차단된다.
- conversation_id가 같은 요청끼리 환불 접수 상태(대량 환불 규칙의 건수·합계)를 공유한다. 없으면 요청마다 새 대화다.
  대화 상태는 메모리에만 있다 (서버를 다시 띄우면 사라진다. 저장은 묶음 4).
  이전 질문·답변 내용은 이어받지 않는다 (한 요청이 한 질문).
- 모델·인덱스는 첫 요청 때 한 번 만들어 재사용한다 (build_app에 주입도 가능).
- 알 수 없는 오류는 예외를 밖으로 던지지 않고 안내 문구와 status "error"로 돌려준다.
- 입력 가드(guards_input.py)가 에이전트보다 먼저 동작한다. 인젝션·대량 환불 지시는 status "blocked"와 고정 문구만 돌려주고,
  사유는 감사 로그(logs/audit.log)에만 남긴다. 범위 밖 주제는 모델을 부르지 않고 범위 밖 안내(status "ok")를 돌려준다.
  통과한 질문은 보이지 않는 문자를 제거한 정규화 문장으로 에이전트에 보낸다.
- 마스킹(masking.py): 에이전트에 보내기 전 질문과, 고객에게 돌려주기 전 답변에서 전화번호·이메일·주소 등을 "[전화번호]"처럼 가린다.
  가려진 종류와 건수만 감사 로그에 남기고 원문은 남기지 않는다. 주문번호·운송장·승인 번호·금액은 가리지 않는다.
- 실행 기록(tracing.py): 요청마다 거친 단계(도구, 결과, 걸린 시간, 정책 검색의 근거 문서)와 전체 시간을 logs/trace.log에 한 줄로
  남기고, 응답에 trace_id를 담는다. 평가 실행기가 이 번호로 기록을 찾는다. /approve도 기록한다.

POST /approve (상담원이 환불 승인 대기 건을 처리)
요청: {"approval_id": str, "decision": "approve"|"modify"|"reject", "approver_id": str, "amount": int(modify일 때), "note": str(선택)}
응답: {"status": "approved"|"modified"|"rejected"|"error", "message": str, "approval_id", "refund_id"(승인·수정 승인일 때)}
- HTTP 코드: 200 처리됨, 403 승인자 아님, 404 없는 승인 번호, 409 이미 처리됨·중복 환불, 422 잘못된 입력, 500 저장 실패.
- 환불 기록은 approve·modify에서만 만들어진다. 규칙은 approval_flow.py.

실행: uvicorn api:app --port 8000
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent import ERROR_REPLY, build_agent, run_agent
from approval_flow import decide_approval
from approvals import ApprovalStore
from guards_input import audit_blocked, check_input
from guards_refusal import write_audit
from masking import mask_text
from refund import RefundSession
from tracing import finish_trace, start_trace, steps_from_calls, write_trace

MAX_CONVERSATIONS = 200  # 메모리에 들고 있는 대화 수 상한 (넘으면 오래된 것부터 버린다)


class QueryRequest(BaseModel):
    question: str
    customer_id: str | None = None
    conversation_id: str | None = None


class ApproveRequest(BaseModel):
    approval_id: str
    decision: str
    approver_id: str
    amount: int | None = None   # modify일 때 낮춘 금액
    note: str | None = None


def build_app(llm=None, db=None, data_dir=None, approval_path=None, audit_path=None, trace_path=None):
    """llm, db, data_dir, approval_path, audit_path, trace_path를 주입받을 수 있는 앱 빌더. 주입이 없으면 첫 요청 때 한 번 만든다."""
    app = FastAPI(title="고객센터 FAQ·주문 봇")
    cache = {"llm": llm, "db": db, "store": None}
    sessions = {}  # (customer_id, conversation_id) -> RefundSession

    def get_store():
        if cache["store"] is None:
            cache["store"] = ApprovalStore(approval_path)
        return cache["store"]

    def get_session(customer_id, conversation_id):
        store = get_store()
        if not conversation_id:
            return RefundSession(customer_id, store)
        key = (customer_id, conversation_id)
        if key not in sessions:
            if len(sessions) >= MAX_CONVERSATIONS:
                sessions.pop(next(iter(sessions)))
            sessions[key] = RefundSession(customer_id, store, conversation_id)
        return sessions[key]

    @app.post("/query")
    def query(req: QueryRequest):
        question = req.question.strip()
        if not question:
            return {"answer": "질문을 입력해 주세요.", "status": "ok", "tools_called": []}
        trace = start_trace("query", req.customer_id, req.conversation_id, question)
        calls = []

        def done(response, **fields):
            """응답을 돌려주기 직전에 실행 기록을 한 줄 남기고, 응답에 trace_id를 붙인다."""
            # 마지막으로 응답한 모델 이름 (예비 모델 묶음일 때만 있다). 모델을 부르지 않은 요청에는 넣지 않는다.
            # 요청이 동시에 처리되면 다른 요청의 모델 이름이 들어갈 수 있는 근사값이다.
            fields.setdefault("model", getattr(cache["llm"], "last_used", None))
            record = finish_trace(trace, status=response["status"], tools_called=response["tools_called"],
                                  answer_chars=len(response["answer"]), **fields)
            write_trace(record, trace_path)
            response["trace_id"] = trace["trace_id"]
            return response

        try:
            guard = check_input(question)
            if not guard["allowed"]:
                audit_blocked(guard, req.customer_id, req.conversation_id, audit_path)
                return done({"answer": guard["reply"], "status": guard["status"], "tools_called": []},
                            guard={"allowed": False, "category": guard["category"], "rule": guard["rule"]}, steps=[], model=None)
            question, found_in = mask_text(guard["clean"])
            if found_in:
                write_audit({"stage": "mask", "direction": "input", "types": found_in,
                             "customer_id": req.customer_id, "conversation_id": req.conversation_id}, audit_path)
            if cache["llm"] is None:
                from llm import build_llm_chain
                cache["llm"] = build_llm_chain()
            if cache["db"] is None:
                from index import load_index
                cache["db"] = load_index()
            session = get_session(req.customer_id, req.conversation_id)
            agent, calls, searched = build_agent(session, llm=cache["llm"], db=cache["db"], data_dir=data_dir)
            result = run_agent(agent, calls, searched, question)
        except Exception as e:  # 모르는 오류는 안전한 쪽으로 처리하되, 내용은 로그로만 남긴다
            print(f"[query 오류] {type(e).__name__}")
            return done({"answer": ERROR_REPLY, "status": "error", "tools_called": []},
                        guard={"allowed": True}, steps=steps_from_calls(calls), error=type(e).__name__)
        answer, found_out = mask_text(result["answer"])
        if found_out:
            write_audit({"stage": "mask", "direction": "output", "types": found_out,
                         "customer_id": req.customer_id, "conversation_id": req.conversation_id}, audit_path)
        response = {"answer": answer, "status": result["status"], "tools_called": result["tools_called"]}
        if result["approval_ids"]:
            response["approval_id"] = result["approval_ids"][0]
            response["approval_ids"] = result["approval_ids"]
        return done(response, guard={"allowed": True}, input_masked=found_in, output_masked=found_out,
                    steps=steps_from_calls(result["calls"]))

    @app.post("/approve")
    def approve(req: ApproveRequest):
        trace = start_trace("approve", None, None, None)
        try:
            result = decide_approval(get_store(), req.approval_id, req.approver_id, req.decision,
                                     req.amount, req.note, data_dir)
        except Exception as e:  # 모르는 오류는 안전한 쪽(처리 안 됨)으로, 내용은 로그로만 남긴다
            print(f"[approve 오류] {type(e).__name__}")
            result = {"code": 500, "status": "error", "message": "승인 처리 중 문제가 생겼습니다. 다시 시도해 주세요."}
        code = result.pop("code")
        write_trace(finish_trace(trace, status=result["status"], approval_id=req.approval_id, decision=req.decision,
                                 approver_id=req.approver_id, http_code=code), trace_path)
        return JSONResponse(status_code=code, content=result)

    return app


app = build_app()
