"""고정 거절 문구와 감사 로그.

- 사용자에게는 이 파일의 고정 문구만 보여준다. 차단 사유(어떤 규칙에 걸렸는지)는 감사 로그에만 남긴다.
  (사유를 알려 주면 공격자가 규칙을 피해 가기 쉬워진다.)
- 감사 로그는 한 줄에 JSON 하나(logs/audit.log)다. 질문 전문은 남기지 않는다:
  규칙 이름, 걸린 짧은 부분(최대 40자), 질문 길이, 질문의 해시 앞 12자만 남긴다. (개인정보·비밀값이 섞였을 수 있기 때문)
- 로그를 쓰다 실패해도 요청 처리는 멈추지 않는다 (예외를 밖으로 던지지 않는다).
- 경로를 주입해 테스트에서 임시 파일을 쓴다. 모듈 최상단에서 파일을 만들지 않는다.
"""
import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path

DEFAULT_AUDIT_PATH = Path(__file__).parent / "logs" / "audit.log"

BLOCKED_INPUT_REPLY = (
    "요청하신 내용은 처리할 수 없습니다. "
    "환불·교환·배송 정책, 주문·배송 조회, 환불 접수에 관해 문의해 주세요."
)
OUT_OF_SCOPE_REPLY = (
    "죄송합니다. 담당 범위가 아닙니다. "
    "주문·배송·환불과 환불·교환·배송 정책에 관해 문의해 주세요."
)

_LOCK = threading.Lock()


def write_audit(event, path=None):
    """감사 로그 한 줄을 덧붙인다. 실패해도 예외를 던지지 않고 True/False만 돌려준다."""
    try:
        record = {"time": datetime.now().isoformat(timespec="seconds"), **event}
        target = Path(path or DEFAULT_AUDIT_PATH)
        with _LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print(f"[감사 로그 쓰기 실패] {type(e).__name__}")  # 내용은 남기지 않는다
        return False


def digest(text):
    """질문 전문 대신 로그에 남기는 해시 앞 12자 (같은 질문이 반복되는지만 볼 수 있다)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
