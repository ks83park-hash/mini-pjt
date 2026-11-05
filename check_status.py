"""status_of 확인 (실제 호출 없음): 도구 호출 기록 -> 응답 status."""
import sys

from agent import status_of


def calls(*outcomes):
    return [{"tool": "t", "outcome": o, "message": ""} for o in outcomes]


def main():
    cases = [
        ([], "ok"), (calls("ok"), "ok"), (calls("ok", "ok"), "ok"),
        (calls("pending"), "approval_required"), (calls("ok", "pending"), "approval_required"),
        (calls("blocked"), "blocked"),
        (calls("pending", "blocked"), "blocked"),        # 일부 접수 + 차단(대량 환불) -> blocked
        (calls("blocked", "error"), "error"),
    ]
    bad = [(c, want, status_of(c)) for c, want in cases if status_of(c) != want]
    for b in bad:
        print("실패:", b)
    print(f"{len(cases) - len(bad)}/{len(cases)} 통과")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
