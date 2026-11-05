"""마스킹 확인 (TASKS 4-4): 개인정보가 든 문장 3개가 모두 마스킹되어 모델 입력과 응답에 원문이 없다.

실제 모델 호출 없이 가짜 모델로 검사한다. 가짜 모델은 (1) 자기가 받은 입력을 기록하고
(2) 일부러 개인정보가 든 답을 돌려줘서, 입력 쪽과 출력 쪽 마스킹을 모두 시험한다.
"""
import json
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from masking import mask_text

# 개인정보가 든 문장 3개 (전화번호, 이메일, 주소) 와 그 원문
PII_SENTENCES = [
    ("제 번호는 010-1234-5678 인데 환불 정책 알려주세요", "010-1234-5678"),
    ("답변은 hong.gildong@example.com 으로 보내주세요. 교환 방법이 궁금해요", "hong.gildong@example.com"),
    ("서울시 강남구 테헤란로 123 으로 배송되나요?", "테헤란로 123"),
]


class FakeModel(Runnable):
    """모델 입력을 기록하고, 개인정보가 섞인 답을 돌려주는 가짜 모델 (도구는 부르지 않는다)."""

    def __init__(self):
        self.seen = []

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, input, config=None, **kwargs):
        messages = input if isinstance(input, list) else getattr(input, "messages", input)
        self.seen.append(json.dumps([str(getattr(m, "content", m)) for m in messages], ensure_ascii=False))
        return AIMessage(content="문의 주셔서 감사합니다. 고객센터 010-9999-8888, help@shop.co.kr, 서울시 마포구 월드컵로 12길 5 로 연락 주세요.")


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    @test
    def 전화번호_표기들을_가린다():
        for s in ("010-1234-5678", "01012345678", "010.1234.5678", "+82 10-1234-5678", "02-123-4567", "031-1234-5678"):
            m, c = mask_text(f"연락처는 {s} 입니다")
            assert "[전화번호]" in m and s not in m and c == {"전화번호": 1}, (s, m)

    @test
    def 이메일을_가린다():
        m, c = mask_text("a.b+c@sub.example.co.kr 로 보내주세요")
        assert m == "[이메일] 로 보내주세요" and c == {"이메일": 1}

    @test
    def 주소를_끝까지_가린다():
        for s in ("서울시 강남구 테헤란로 123", "서울특별시 마포구 월드컵로 12길 5", "경기도 성남시 분당구 판교로 235 101동 202호",
                  "부산 해운대구 해운대해변로 264"):
            m, c = mask_text(f"주소: {s} 입니다")
            assert m == "주소: [주소] 입니다" and c == {"주소": 1}, (s, m)

    @test
    def 주민등록번호와_카드번호도_가린다():
        assert mask_text("주민번호 900101-1234567")[0] == "주민번호 [주민등록번호]"
        assert mask_text("카드 1234-5678-9012-3456")[0] == "카드 [카드번호]"

    @test
    def 한_문장의_여러_종류와_여러_건을_모두_가린다():
        m, c = mask_text("010-1111-2222 또는 010-3333-4444, x@y.com")
        assert m == "[전화번호] 또는 [전화번호], [이메일]" and c == {"이메일": 1, "전화번호": 2}

    @test
    def 주문번호_금액_날짜는_가리지_않는다():
        for s in ("ORD-1001 ORD-1002 주문 280,000원 TRK-9001 APV-1A2B3C4D 2026-11-05 수령", "ORD-1001, ORD-1002, ORD-1004 환불해줘",
                  "배송비 3,000원 5만 원 2,000원 적립", "수령 후 7일 이내 30일 이내 3영업일", "1001 1002 1004",
                  "주소 변경은 어떻게 하나요?", "서울 지역은 2~3일 걸려요", "도서산간 지역 추가 3,000원", "전화 상담은 몇 시까지인가요?"):
            assert mask_text(s) == (s, {}), mask_text(s)

    @test
    def 멱등이다_두_번_가려도_같다():
        once, _ = mask_text("010-1234-5678 a@b.com 서울시 강남구 테헤란로 123")
        assert mask_text(once) == (once, {})

    @test
    def 입력과_응답에_원문이_없다_POST_query():
        import uvicorn
        from api import build_app
        fake = FakeModel()
        log = Path(tempfile.mkdtemp()) / "audit.log"
        server = uvicorn.Server(uvicorn.Config(build_app(llm=fake, db=object(), audit_path=log, approval_path=log.parent / "approvals.sqlite", trace_path=log.parent / "trace.log"), port=8016, log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        time.sleep(2)
        try:
            def ask(q):
                req = urllib.request.Request("http://127.0.0.1:8016/query", json.dumps({"question": q, "customer_id": "C001"}).encode(),
                                             {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read())

            for sentence, raw in PII_SENTENCES:
                fake.seen.clear()
                r = ask(sentence)
                sent_to_model = "".join(fake.seen)
                assert raw not in sent_to_model, f"모델 입력에 원문이 있음: {raw}"
                assert "[" in sent_to_model, "마스킹된 문장이 모델에 전달되지 않음"
                # 가짜 모델이 일부러 섞어 보낸 개인정보가 응답에서 가려졌는지
                for leaked in ("010-9999-8888", "help@shop.co.kr", "월드컵로 12길 5"):
                    assert leaked not in r["answer"], f"응답에 원문이 있음: {leaked}"
                assert "[전화번호]" in r["answer"] and "[이메일]" in r["answer"] and "[주소]" in r["answer"], r["answer"]
            text = log.read_text(encoding="utf-8")
            for secret in ("010-1234-5678", "hong.gildong", "테헤란로", "010-9999-8888", "help@shop"):
                assert secret not in text, f"감사 로그에 원문이 남음: {secret}"
            entries = [json.loads(line) for line in text.splitlines()]
            assert {(e["direction"], tuple(e["types"])) for e in entries if e["stage"] == "mask"} >= {
                ("input", ("전화번호",)), ("input", ("이메일",)), ("input", ("주소",)),
                ("output", ("이메일", "전화번호", "주소"))}, entries
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
    print(f"{len(tests) - failed}/{len(tests)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
