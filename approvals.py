"""환불 승인 대기 저장소 (SQLite, 표준 라이브러리 sqlite3).

- 환불 접수가 만들어지면 approval_id를 발급하고 상태 "pending"으로 저장한다.
- 승인 전에는 환불 기록(data/refunds.json)을 만들지 않는다. 기록은 승인(approve·modify) 처리 때만 만든다 (approval_flow.py).
- 서버를 다시 띄워도 승인 대기가 남도록 파일(approvals.sqlite)에 저장한다. 경로를 주입해 테스트에서 임시 파일을 쓴다.
- 연결은 호출마다 열고 닫는다 (요청이 여러 스레드에서 처리되어도 안전하다). 모듈 최상단에서 파일을 만들지 않는다.
- 상태 전이는 pending -> approved / modified / rejected 한 방향이다. decide()는 "pending일 때만" 바꾸는
  한 번의 UPDATE라서, 같은 건을 동시에 두 번 처리해도 한 번만 성공한다.
- 이 저장소는 상태만 다룬다. 누가 어떤 결정을 할 수 있는지는 approval_flow.py가 정한다.
"""
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "approvals.sqlite"

# 처리 결과가 들어가는 열 (기존 DB 파일에 없으면 열기 때 추가한다)
DECISION_COLUMNS = {
    "decided_by": "TEXT", "decided_at": "TEXT", "final_amount": "INTEGER", "note": "TEXT", "refund_id": "TEXT",
}


def _now():
    return datetime.now().isoformat(timespec="seconds")


class ApprovalStore:
    def __init__(self, path=None):
        self.path = str(path or DEFAULT_PATH)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, customer_id TEXT,
                    conversation_id TEXT, amount INTEGER NOT NULL, reason TEXT,
                    status TEXT NOT NULL, created_at TEXT NOT NULL)"""
            )
            have = {row["name"] for row in conn.execute("PRAGMA table_info(approvals)")}
            for column, kind in DECISION_COLUMNS.items():
                if column not in have:
                    conn.execute(f"ALTER TABLE approvals ADD COLUMN {column} {kind}")

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, request, customer_id=None, conversation_id=None):
        """승인 대기 한 건을 저장하고 approval_id를 돌려준다. request: {"order_id", "amount", "reason"}"""
        approval_id = "APV-" + uuid.uuid4().hex[:8].upper()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO approvals (approval_id, order_id, customer_id, conversation_id, amount, reason, status, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (approval_id, request["order_id"], customer_id, conversation_id, request["amount"],
                 request["reason"], "pending", _now()),
            )
        return approval_id

    def get(self, approval_id):
        """승인 건 하나를 dict로 돌려준다. 없으면 None."""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        return dict(row) if row else None

    def list_by_status(self, status="pending"):
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM approvals WHERE status = ? ORDER BY created_at", (status,)).fetchall()
        return [dict(r) for r in rows]

    def decide(self, approval_id, new_status, decided_by, final_amount=None, note=None):
        """pending인 건만 new_status로 바꾼다. 바꿨으면 True, 이미 처리됐거나 없으면 False."""
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE approvals SET status=?, decided_by=?, decided_at=?, final_amount=?, note=?"
                " WHERE approval_id=? AND status='pending'",
                (new_status, decided_by, _now(), final_amount, note, approval_id),
            )
            return cur.rowcount == 1

    def set_refund_id(self, approval_id, refund_id):
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE approvals SET refund_id=? WHERE approval_id=?", (refund_id, approval_id))

    def reopen(self, approval_id):
        """처리 도중 실패했을 때 되돌린다: 다시 pending으로, 처리 정보는 비운다."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE approvals SET status='pending', decided_by=NULL, decided_at=NULL, final_amount=NULL,"
                " note=NULL, refund_id=NULL WHERE approval_id=?",
                (approval_id,),
            )
