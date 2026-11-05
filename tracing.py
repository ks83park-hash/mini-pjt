"""실행 기록(트레이스): 요청 하나가 어떤 단계를 거쳤고 얼마나 걸렸는지 한 줄(JSON)로 파일에 남긴다.

기록하는 것 (logs/trace.log, 요청마다 한 줄)
- trace_id, 시각, 종류(query/approve), 고객·대화 번호
- 질문 (개인정보를 마스킹한 뒤 200자까지만), 입력 가드 결과(통과 여부·분류·규칙), 입력·출력에서 가려진 개인정보 종류와 건수
- 거친 단계(steps): 호출한 도구 이름, 결과(ok/blocked/pending/error), 걸린 시간(ms), 승인 번호.
  정책 검색 단계에는 검색어, 근거로 쓴 문서명·거리, 근거 문서 내용(contexts)이 들어간다 (정책 문서는 민감 정보가 아니다).
- 최종 status, 호출한 도구 목록, 답변 글자 수, 전체 시간(ms), 마지막으로 응답한 모델 이름, 오류가 났다면 오류 이름
기록하지 않는 것: 답변 전문, 비밀값, 오류 내용(이름만), 마스킹 전의 질문.

용도
- 운영: 어느 단계에서 막혔고 어디가 느린지 본다 (감사 로그 audit.log는 차단 사유 전용이고, 이 로그는 처리 이력 전체다).
- 평가: 평가 실행기가 응답의 trace_id로 이 기록을 찾아, 호출한 도구와 검색된 근거 문서(contexts)를 평가 결과에 담는다.

로그를 쓰다 실패해도 요청 처리는 멈추지 않는다 (예외를 밖으로 던지지 않는다). 경로를 주입해 테스트에서 임시 파일을 쓴다.
"""
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from masking import mask_text

DEFAULT_TRACE_PATH = Path(__file__).parent / "logs" / "trace.log"
QUESTION_MAX_CHARS = 200
# 도구 호출 기록(calls)에서 단계로 옮기는 항목 (message 같은 고정 문구는 옮기지 않는다)
STEP_KEYS = ("tool", "outcome", "ms", "approval_id", "query", "sources", "distances", "contexts")

_LOCK = threading.Lock()


def start_trace(kind, customer_id=None, conversation_id=None, question=None):
    """기록을 시작한다. 시간 측정을 위해 시작 시각을 들고 있다 (finish_trace에서 제거된다)."""
    masked, _ = mask_text(question or "")
    return {
        "trace_id": "TR-" + uuid.uuid4().hex[:10],
        "kind": kind,
        "time": datetime.now().isoformat(timespec="seconds"),
        "customer_id": customer_id,
        "conversation_id": conversation_id,
        "question": masked[:QUESTION_MAX_CHARS] if question is not None else None,
        "_t0": time.perf_counter(),
    }


def steps_from_calls(calls):
    """도구 호출 기록을 단계 목록으로 바꾼다 (값이 없는 항목은 뺀다)."""
    return [{k: c[k] for k in STEP_KEYS if c.get(k) not in (None, [], "")} for c in calls]


def finish_trace(trace, **fields):
    """전체 시간(ms)을 채우고 기록 dict를 완성한다."""
    record = {k: v for k, v in trace.items() if k != "_t0"}
    record["total_ms"] = round((time.perf_counter() - trace["_t0"]) * 1000)
    record.update(fields)
    return record


def write_trace(record, path=None):
    """기록 한 줄을 덧붙인다. 실패해도 예외를 던지지 않고 True/False만 돌려준다."""
    try:
        target = Path(path or DEFAULT_TRACE_PATH)
        with _LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print(f"[실행 기록 쓰기 실패] {type(e).__name__}")  # 내용은 남기지 않는다
        return False


def load_traces(path=None):
    """기록 파일을 읽어 {trace_id: 기록}으로 돌려준다. 파일이 없거나 깨진 줄은 건너뛴다."""
    target = Path(path or DEFAULT_TRACE_PATH)
    traces = {}
    if not target.exists():
        return traces
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            traces[record["trace_id"]] = record
        except (ValueError, KeyError):
            continue
    return traces
