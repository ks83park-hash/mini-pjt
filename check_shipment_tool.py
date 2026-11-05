"""track_shipment 확인 (TASKS 2-3): 배송 중·완료·배송 전 주문 각 1건의 상태가 맞게 나온다."""
import sys

from tools import SHIPMENT_ERROR, SHIPMENT_NOT_FOUND, track_shipment


def main():
    moving = track_shipment("ORD-1001")      # 배송 중
    done = track_shipment("ORD-1002")        # 배송 완료
    before = track_shipment("ORD-1004")      # 배송 전
    for text in (moving, done, before):
        print(text, end="\n\n")
    assert "배송 중" in moving and "서울 허브 터미널" in moving and "예상 도착일: 2026-11-07" in moving
    assert "배송 완료" in done and "수령일: 2026-11-03" in done and "예상 도착일" not in done
    assert "발송 전" in before and "TRK" not in before
    assert track_shipment("TRK-9001") == moving, "운송장 번호로도 같은 결과"
    assert track_shipment("trk9001") == moving, "형식이 느슨한 운송장 입력"
    for bad in ["ORD-9999", "TRK-0000", "", "abc", None]:
        assert track_shipment(bad) == SHIPMENT_NOT_FOUND, f"없는 번호 처리 실패: {bad!r}"
    assert track_shipment("ORD-1001", data_dir="없는폴더") == SHIPMENT_ERROR
    print("통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
