"""승인 처리 확인 (TASKS 4-2): approve·modify·reject 각 1건이 처리되고, approve 계열에서만 환불 기록이 생긴다.

실제 모델 호출 없이 승인 로직과 POST /approve를 검사한다.
데이터 폴더와 DB는 임시 복사본을 쓰므로 프로젝트의 data/refunds.json은 바뀌지 않는다.
"""
import json
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import approval_flow
from approval_flow import decide_approval
from approvals import ApprovalStore

REAL_REFUNDS = Path("data/refunds.json")


def fresh():
    """(store, data_dir): 임시 DB와 데이터 폴더 복사본."""
    root = Path(tempfile.mkdtemp())
    shutil.copytree("data", root / "data")
    return ApprovalStore(root / "approvals.sqlite"), root / "data"


def new_request(store, order_id="ORD-1002", amount=280000, customer_id="C001"):
    return store.create({"order_id": order_id, "amount": amount, "reason": "단순 변심"}, customer_id, "conv")


def refunds(data_dir):
    return json.loads((Path(data_dir) / "refunds.json").read_text(encoding="utf-8"))


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    before_real = REAL_REFUNDS.read_text(encoding="utf-8")

    @test
    def approve는_환불_기록을_만든다():
        store, d = fresh()
        aid = new_request(store)
        assert len(refunds(d)) == 5
        r = decide_approval(store, aid, "A001", "approve", data_dir=d)
        assert (r["code"], r["status"]) == (200, "approved") and r["refund_id"] == "RF-006", r
        rows = refunds(d)
        assert len(rows) == 6 and rows[-1]["amount"] == 280000 and rows[-1]["status"] == "승인"
        assert rows[-1]["order_id"] == "ORD-1002" and rows[-1]["customer_id"] == "C001" and rows[-1]["approval_id"] == aid
        saved = store.get(aid)
        assert saved["status"] == "approved" and saved["decided_by"] == "A001" and saved["refund_id"] == "RF-006"

    @test
    def modify는_낮춘_금액으로_기록을_만든다():
        store, d = fresh()
        aid = new_request(store)
        r = decide_approval(store, aid, "A002", "modify", amount=200000, note="일부 환불", data_dir=d)
        assert (r["code"], r["status"], r["amount"]) == (200, "modified", 200000), r
        assert refunds(d)[-1]["amount"] == 200000
        saved = store.get(aid)
        assert saved["status"] == "modified" and saved["final_amount"] == 200000 and saved["note"] == "일부 환불"

    @test
    def reject는_환불_기록을_만들지_않는다():
        store, d = fresh()
        aid = new_request(store)
        r = decide_approval(store, aid, "A001", "reject", note="정책 위반", data_dir=d)
        assert (r["code"], r["status"], r["refund_id"]) == (200, "rejected", None), r
        assert len(refunds(d)) == 5 and store.get(aid)["status"] == "rejected"

    @test
    def modify는_금액을_늘리거나_잘못_넣으면_거부되고_대기가_유지된다():
        store, d = fresh()
        aid = new_request(store)
        for bad in (None, 0, -1, 280000, 300000, 1.5, "100000", True):
            r = decide_approval(store, aid, "A001", "modify", amount=bad, data_dir=d)
            assert r["code"] == 422, (bad, r)
        assert store.get(aid)["status"] == "pending" and len(refunds(d)) == 5

    @test
    def 승인자가_아니거나_입력이_틀리면_처리되지_않는다():
        store, d = fresh()
        aid = new_request(store)
        assert decide_approval(store, aid, "C001", "approve", data_dir=d)["code"] == 403   # 고객은 승인할 수 없다
        assert decide_approval(store, aid, None, "approve", data_dir=d)["code"] == 403
        assert decide_approval(store, aid, "A001", "delete", data_dir=d)["code"] == 422
        assert decide_approval(store, "APV-NONE", "A001", "approve", data_dir=d)["code"] == 404
        assert store.get(aid)["status"] == "pending" and len(refunds(d)) == 5

    @test
    def 한_번_처리된_건은_다시_처리되지_않는다():
        store, d = fresh()
        aid = new_request(store)
        assert decide_approval(store, aid, "A001", "approve", data_dir=d)["code"] == 200
        for decision in ("approve", "reject", "modify"):
            assert decide_approval(store, aid, "A001", decision, amount=1000, data_dir=d)["code"] == 409
        assert len(refunds(d)) == 6

    @test
    def 같은_주문에_이미_환불이_있으면_승인되지_않는다():
        store, d = fresh()
        a1, a2 = new_request(store), new_request(store)          # 같은 주문의 대기 건 2개
        assert decide_approval(store, a1, "A001", "approve", data_dir=d)["code"] == 200
        r = decide_approval(store, a2, "A001", "approve", data_dir=d)
        assert r["code"] == 409 and store.get(a2)["status"] == "pending" and len(refunds(d)) == 6
        assert decide_approval(store, a2, "A001", "reject", data_dir=d)["code"] == 200   # 거절은 가능
        done = new_request(store, "ORD-1013", 95000, "C005")      # 이미 환불 완료(RF-003)인 주문
        assert decide_approval(store, done, "A001", "approve", data_dir=d)["code"] == 409

    @test
    def 동시에_같은_건을_승인해도_한_번만_처리된다():
        store, d = fresh()
        aid = new_request(store)
        codes = []
        threads = [threading.Thread(target=lambda: codes.append(decide_approval(store, aid, "A001", "approve", data_dir=d)["code"]))
                   for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert sorted(codes) == [200] + [409] * 5, codes
        assert len(refunds(d)) == 6

    @test
    def 기록_저장에_실패하면_승인이_취소된다():
        store, d = fresh()
        aid = new_request(store)
        orig = approval_flow._write_refunds
        approval_flow._write_refunds = lambda rows, data_dir=None: (_ for _ in ()).throw(OSError("디스크 오류"))
        try:
            r = decide_approval(store, aid, "A001", "approve", data_dir=d)
        finally:
            approval_flow._write_refunds = orig
        assert r["code"] == 500 and store.get(aid)["status"] == "pending", "승인됐는데 기록이 없는 상태"
        assert store.get(aid)["refund_id"] is None and len(refunds(d)) == 5
        assert decide_approval(store, aid, "A001", "approve", data_dir=d)["code"] == 200   # 다시 시도하면 성공

    @test
    def 예전_형식의_DB_파일도_열린다():
        import sqlite3
        path = Path(tempfile.mkdtemp()) / "old.sqlite"
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE approvals (approval_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, customer_id TEXT,
                        conversation_id TEXT, amount INTEGER NOT NULL, reason TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("INSERT INTO approvals VALUES ('APV-OLD','ORD-1002','C001','c',280000,'x','pending','2026-11-05T00:00:00')")
        conn.commit()
        conn.close()
        store = ApprovalStore(path)
        assert store.get("APV-OLD")["refund_id"] is None
        assert store.decide("APV-OLD", "rejected", "A001") is True

    @test
    def POST_approve_엔드포인트():
        import uvicorn
        from api import build_app
        store_path = Path(tempfile.mkdtemp()) / "approvals.sqlite"
        d = Path(tempfile.mkdtemp()) / "data"
        shutil.copytree("data", d)
        server = uvicorn.Server(uvicorn.Config(build_app(data_dir=d, approval_path=store_path, audit_path=store_path.parent / "audit.log", trace_path=store_path.parent / "trace.log"), port=8012, log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        time.sleep(2)
        try:
            store = ApprovalStore(store_path)
            a1, a2, a3 = (new_request(store, o, a) for o, a in (("ORD-1002", 280000), ("ORD-1004", 25000), ("ORD-1006", 74000)))

            def post(body):
                req = urllib.request.Request("http://127.0.0.1:8012/approve", json.dumps(body).encode(),
                                             {"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        return resp.status, json.loads(resp.read())
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read())

            code, body = post({"approval_id": a1, "decision": "approve", "approver_id": "A001"})
            assert (code, body["status"]) == (200, "approved") and body["refund_id"] == "RF-006", body
            code, body = post({"approval_id": a2, "decision": "modify", "approver_id": "A001", "amount": 20000})
            assert (code, body["status"]) == (200, "modified"), body
            code, body = post({"approval_id": a3, "decision": "reject", "approver_id": "A002", "note": "사유 부족"})
            assert (code, body["status"]) == (200, "rejected"), body
            assert [r["amount"] for r in refunds(d)[5:]] == [280000, 20000], "approve·modify에서만 기록이 생겨야 함"
            assert post({"approval_id": a1, "decision": "approve", "approver_id": "A001"})[0] == 409
            assert post({"approval_id": a1, "decision": "approve", "approver_id": "C001"})[0] == 403
            assert post({"approval_id": "APV-NONE", "decision": "approve", "approver_id": "A001"})[0] == 404
            assert post({"approval_id": a1, "approver_id": "A001"})[0] == 422          # decision 누락(형식 오류)
        finally:
            server.should_exit = True

    failed = 0
    for name, fn in tests.items():
        try:
            fn()
            print("통과:", name)
        except AssertionError as e:
            failed += 1
            print("실패:", name, e)
    if REAL_REFUNDS.read_text(encoding="utf-8") != before_real:
        failed += 1
        print("실패: 프로젝트의 data/refunds.json이 바뀌었다")
    print(f"{len(tests) - failed}/{len(tests)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
