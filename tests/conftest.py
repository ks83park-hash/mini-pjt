"""평가 테스트 공통 설정.

서버가 떠 있어야 하는 테스트는 `POST /query`를 HTTP로 호출한다 (표준 라이브러리만 사용).
- 주소: 환경변수 QUERY_URL (기본 http://127.0.0.1:8000/query)
- 서버에 연결되지 않으면 해당 테스트는 건너뛴다.

응답 형식 (이 형식으로 구현해야 테스트가 통과한다):
    {
      "answer": str,                              # 답변 본문
      "status": "ok" | "blocked" | "approval_required",
      "tools_called": [str]                       # 호출된 도구 이름 (get_order, track_shipment, request_refund)
    }
요청 형식:
    {"question": str, "customer_id": "C001"}      # 더미 세션의 로그인 고객
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

QUERY_URL = os.environ.get("QUERY_URL", "http://127.0.0.1:8000/query")
CUSTOMER_ID = "C001"
EVAL_SET_PATH = Path(__file__).parent / "eval_set.json"


def load_eval_set():
    return json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def ask():
    """질문을 보내 응답 dict를 돌려주는 함수. 서버가 없으면 테스트를 건너뛴다."""

    def _ask(question):
        body = json.dumps({"question": question, "customer_id": CUSTOMER_ID}).encode("utf-8")
        req = urllib.request.Request(
            QUERY_URL, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        _ask("연결 확인")
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        pytest.skip(f"서버에 연결할 수 없음: {QUERY_URL}", allow_module_level=False)
    return _ask
