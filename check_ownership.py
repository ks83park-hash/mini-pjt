"""본인 주문 확인 규칙 확인 (TASKS 2-4): 본인 주문은 통과, 타인 주문은 차단."""
import sys

from ownership import BLOCKED_REPLY, check_owner


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    @test
    def 본인_주문은_통과한다():
        assert check_owner("C001", "ORD-1001") == (True, "")
        assert check_owner("C001", "ord-1002") == (True, "")      # 입력 형식이 달라도
        assert check_owner("C001", "TRK-9001") == (True, "")      # 운송장 번호로도

    @test
    def 타인_주문은_차단된다():
        assert check_owner("C001", "ORD-1003") == (False, BLOCKED_REPLY)   # 소유자 C002
        assert check_owner("C001", "TRK-9003") == (False, BLOCKED_REPLY)   # 운송장으로 우회 시도
        assert check_owner("C002", "ORD-1001") == (False, BLOCKED_REPLY)

    @test
    def 로그인_정보가_없으면_차단된다():
        for cid in (None, ""):
            assert check_owner(cid, "ORD-1001") == (False, BLOCKED_REPLY)

    @test
    def 없는_번호는_통과해_도구가_안내한다():
        assert check_owner("C001", "ORD-9999") == (True, "")

    @test
    def 문구에_소유자_정보가_없다():
        _, msg = check_owner("C001", "ORD-1003")
        assert "C002" not in msg and "이바다" not in msg

    @test
    def 오류가_나면_차단된다():
        assert check_owner("C001", "ORD-1001", data_dir="없는폴더") == (False, BLOCKED_REPLY)

    failed = 0
    for name, fn in tests.items():
        try:
            fn()
            print("통과:", name)
        except AssertionError:
            failed += 1
            print("실패:", name)
    print(f"{len(tests) - failed}/{len(tests)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
