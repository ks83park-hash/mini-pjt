"""환불 접수 함수와 대량 환불 규칙 확인 (TASKS 2-5): 2건은 통과, 3건째와 합계 초과는 차단."""
import json
import sys

from refund import (COUNT_BLOCKED, TOTAL_BLOCKED, RefundSession, check_refund_limit,
                    prepare_refund, request_refund)

REFUNDS_PATH = "data/refunds.json"


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    @test
    def 규칙_함수_경계값():
        assert check_refund_limit(0, 0, 100_000) == (True, "")
        assert check_refund_limit(1, 100_000, 100_000) == (True, "")      # 2건째 허용
        assert check_refund_limit(2, 100_000, 10_000) == (False, COUNT_BLOCKED)  # 3건째 차단
        assert check_refund_limit(1, 200_000, 300_000) == (True, "")      # 합계 정확히 50만 원은 허용
        assert check_refund_limit(1, 200_000, 300_001) == (False, TOTAL_BLOCKED)

    @test
    def 두_건은_접수되고_세_건째는_차단된다():
        s = RefundSession("C002")  # 1003, 1005, 1006은 모두 환불 처리 중인 기록이 없다 (합계 22만 원이라 건수만 시험)
        a = prepare_refund(s, "ORD-1003", "단순 변심")
        b = prepare_refund(s, "ORD-1005", "단순 변심")
        c = prepare_refund(s, "ORD-1006", "단순 변심")
        assert (a["status"], b["status"]) == ("pending", "pending")
        assert s.count == 2 and s.total == 89_000 + 59_000
        assert c["status"] == "blocked" and c["message"] == COUNT_BLOCKED
        assert s.count == 2, "차단된 시도는 세지 않음"

    @test
    def 합계가_50만원을_넘으면_차단된다():
        s = RefundSession("C001")
        assert prepare_refund(s, "ORD-1002", "단순 변심")["status"] == "pending"  # 280,000
        r = prepare_refund(s, "ORD-1001", "단순 변심")                            # +320,000 = 600,000
        assert r["status"] == "blocked" and r["message"] == TOTAL_BLOCKED
        assert s.count == 1

    @test
    def 타인_주문은_접수되지_않는다():
        s = RefundSession("C001")
        assert prepare_refund(s, "ORD-1003", "단순 변심")["status"] == "blocked"
        assert s.count == 0

    @test
    def 사유_중복_없는주문_이미처리된_환불():
        s = RefundSession("C001")
        assert prepare_refund(s, "ORD-1002", "")["status"] == "error"
        assert prepare_refund(s, "ORD-9999", "단순 변심")["status"] == "error"
        assert prepare_refund(s, "ORD-1002", "단순 변심")["status"] == "pending"
        assert prepare_refund(s, "ORD-1002", "단순 변심")["status"] == "error"   # 같은 대화에서 중복
        s2 = RefundSession("C005")
        assert prepare_refund(s2, "ORD-1013", "상품 불량")["status"] == "error"  # 이미 환불 완료(RF-003)

    @test
    def 접수해도_환불_기록은_만들지_않는다():
        before = open(REFUNDS_PATH, encoding="utf-8").read()
        s = RefundSession("C004")
        assert prepare_refund(s, "ORD-1011", "단순 변심")["status"] == "pending"
        assert open(REFUNDS_PATH, encoding="utf-8").read() == before
        assert len(json.loads(before)) == 5

    @test
    def 도구는_문자열을_돌려주고_오류에도_예외가_없다():
        s = RefundSession("C001")
        assert isinstance(request_refund(s, "ORD-1002", "단순 변심"), str)
        assert "접수" in request_refund(RefundSession("C001"), "ORD-1004", "단순 변심")
        assert isinstance(request_refund(RefundSession("C001"), "ORD-1002", "x", data_dir="없는폴더"), str)

    @test
    def 동시에_호출해도_한도가_지켜진다():
        """에이전트가 환불 도구를 병렬로 부르는 상황: 합계 60만 원인 2건을 동시에 접수한다."""
        import threading
        import time

        import refund

        orig_check = refund.check_refund_limit

        def slow_check(*args):          # 검사 직후 잠깐 멈춰 두 호출이 겹치게 만든다 (잠금이 없으면 둘 다 통과)
            result = orig_check(*args)
            time.sleep(0.05)
            return result

        refund.check_refund_limit = slow_check
        try:
            for _ in range(5):
                s = RefundSession("C001")
                results = []
                threads = [threading.Thread(target=lambda o=o: results.append(prepare_refund(s, o, "단순 변심")))
                           for o in ("ORD-1002", "ORD-1001")]   # 28만 + 32만
                [t.start() for t in threads]
                [t.join() for t in threads]
                assert sorted(r["status"] for r in results) == ["blocked", "pending"], [r["status"] for r in results]
                assert s.count == 1 and s.total <= 500_000
        finally:
            refund.check_refund_limit = orig_check

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
