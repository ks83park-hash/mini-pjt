"""get_order 확인 (TASKS 2-2): 있는 번호는 상품·금액·상태, 없는 번호는 예외 없이 안내 문구."""
import sys

from tools import LOOKUP_ERROR, NOT_FOUND, get_order


def main():
    ok = get_order("ORD-1001")
    print(ok)
    assert all(k in ok for k in ("노트북", "320,000원", "배송 중")), "상품·금액·상태가 빠짐"
    assert "수령일" not in ok, "배송 중 주문에 수령일이 있음"
    assert "2026-11-03" in get_order("ord-1002"), "소문자 입력과 수령일 처리"
    assert get_order("1001") == ok, "숫자만 입력"
    for bad in ["ORD-9999", "", "abc", None]:
        assert get_order(bad) == NOT_FOUND, f"없는 번호 처리 실패: {bad!r}"
    assert get_order("ORD-1001", data_dir="없는폴더") == LOOKUP_ERROR, "파일 오류가 예외로 나옴"
    print("통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
