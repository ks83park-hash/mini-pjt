"""환불 승인 대기 확인 (TASKS 4-1): 환불 접수에 approval_id가 오고, 승인 전에는 환불 기록이 생기지 않는다.

실제 모델 호출 없이 접수 함수와 저장소만 검사한다. 임시 DB 파일을 쓴다.
"""
import sys
import tempfile
from pathlib import Path

from approvals import ApprovalStore
from refund import RefundSession, prepare_refund

REFUNDS = Path("data/refunds.json")


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    tmp = Path(tempfile.mkdtemp()) / "approvals.sqlite"

    @test
    def 접수하면_approval_id가_발급되고_대기로_저장된다():
        store = ApprovalStore(tmp)
        s = RefundSession("C001", store, "conv-1")
        r = prepare_refund(s, "ORD-1002", "단순 변심")
        assert r["status"] == "pending"
        aid = r["request"]["approval_id"]
        assert aid.startswith("APV-") and aid in r["message"]
        saved = store.get(aid)
        assert saved["status"] == "pending" and saved["order_id"] == "ORD-1002"
        assert saved["customer_id"] == "C001" and saved["conversation_id"] == "conv-1" and saved["amount"] == 280000

    @test
    def 승인_전에는_환불_기록이_생기지_않는다():
        before = REFUNDS.read_text(encoding="utf-8")
        s = RefundSession("C004", ApprovalStore(tmp))
        assert prepare_refund(s, "ORD-1011", "단순 변심")["status"] == "pending"
        assert REFUNDS.read_text(encoding="utf-8") == before

    @test
    def 서버를_다시_띄워도_대기_건이_남는다():
        aid = prepare_refund(RefundSession("C003", ApprovalStore(tmp)), "ORD-1008", "단순 변심")["request"]["approval_id"]
        assert ApprovalStore(tmp).get(aid)["status"] == "pending"   # 새 저장소 객체(재시작)로 읽기

    @test
    def 차단_오류_건에는_발급되지_않는다():
        store = ApprovalStore(tmp)
        n = len(store.list_by_status("pending"))
        s = RefundSession("C001", store)
        assert prepare_refund(s, "ORD-1003", "단순 변심")["status"] == "blocked"      # 타인 주문
        assert prepare_refund(s, "ORD-9999", "단순 변심")["status"] == "error"        # 없는 주문
        assert prepare_refund(s, "ORD-1002", "")["status"] == "error"                 # 사유 없음
        assert len(store.list_by_status("pending")) == n

    @test
    def approval_id가_서로_다르다():
        store = ApprovalStore(tmp)
        ids = {store.create({"order_id": "ORD-1001", "amount": 1, "reason": "x"}) for _ in range(50)}
        assert len(ids) == 50

    @test
    def 없는_id는_None이고_저장소_오류는_접수_안됨으로_처리된다():
        assert ApprovalStore(tmp).get("APV-NONE") is None
        bad_store = ApprovalStore(Path(tempfile.mkdtemp()) / "x.sqlite")
        bad_store.path = str(Path(tempfile.mkdtemp()) / "없는폴더" / "x.sqlite")   # 열 수 없는 경로
        s = RefundSession("C001", bad_store)
        r = prepare_refund(s, "ORD-1002", "단순 변심")
        assert r["status"] == "error" and s.count == 0, "저장 실패인데 접수된 것으로 처리됨"

    @test
    def store가_없으면_기존처럼_동작한다():
        r = prepare_refund(RefundSession("C001"), "ORD-1002", "단순 변심")
        assert r["status"] == "pending" and "approval_id" not in r["request"]

    failed = 0
    for name, fn in tests.items():
        try:
            fn()
            print("통과:", name)
        except AssertionError as e:
            failed += 1
            print("실패:", name, e)
    print(f"{len(tests) - failed}/{len(tests)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
