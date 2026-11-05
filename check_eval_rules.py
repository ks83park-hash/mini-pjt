"""평가 채점 규칙 확인 (실제 호출 없음): 합격 응답은 합격, 틀린 응답은 불합격으로 판정하는지 가짜 응답으로 검사한다.

채점기가 틀리면 평가 점수 전체를 믿을 수 없으므로, 실제 평가 전에 이 검사를 먼저 통과시킨다.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from eval_rules import judge_case, summarize

CASES = {c["id"]: c for c in json.loads(Path("tests/eval_set.json").read_text(encoding="utf-8"))}


def resp(answer="", status="ok", tools=()):
    return {"answer": answer, "status": status, "tools_called": list(tools)}


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    def verdict(case_id, response):
        return judge_case(CASES[case_id], response)[0]

    @test
    def 정책_질문_합격과_불합격():
        good = resp("수령 후 7일 이내입니다.\n(출처: 환불 정책)")
        assert verdict("e01", good)
        assert not verdict("e01", resp("수령 후 14일 이내입니다.\n(출처: 환불 정책)")), "수치가 틀린 답을 통과시킴"
        assert not verdict("e01", resp("수령 후 7일 이내입니다.")), "출처 없는 답을 통과시킴"
        assert not verdict("e01", resp("수령 후 7일 이내입니다.\n(출처: 배송 정책)")), "엉뚱한 출처를 통과시킴"
        assert not verdict("e01", resp("7일 이내입니다.\n(출처: 환불 정책)", status="blocked")), "차단 상태를 통과시킴"
        assert verdict("e01", resp("7일 이내입니다.\n(출처: 교환 정책, 환불 정책)")), "출처가 여러 개인 답을 불합격 처리"

    @test
    def 숫자_표기_차이는_같게_본다():
        assert verdict("e03", resp("왕복 배송비 6,000원은 고객 부담입니다.\n(출처: 교환 정책)"))
        assert verdict("e03", resp("왕복 배송비 6000 원은 고객 부담입니다.\n(출처: 교환 정책)"))

    @test
    def 답변_불가_질문():
        assert verdict("e07", resp("죄송합니다. 담당 범위가 아닙니다."))
        assert verdict("e09", resp("정책 문서에서 찾을 수 없습니다."))
        assert not verdict("e09", resp("네, 해외 배송도 가능합니다.")), "지어낸 답을 통과시킴"
        assert not verdict("e09", resp("찾을 수 없습니다.\n(출처: 배송 정책)")), "근거 없는데 출처가 있는 답을 통과시킴"

    @test
    def 도구_호출():
        assert verdict("e10", resp("노트북", tools=["get_order"]))
        assert not verdict("e10", resp("노트북", tools=[])), "도구를 안 부른 답을 통과시킴"
        assert not verdict("e10", resp("노트북", tools=["get_order", "track_shipment"])), "불필요한 도구 호출을 통과시킴"
        assert verdict("e13", resp("x", tools=["track_shipment", "get_order"])), "순서가 달라도 같은 도구면 통과해야 함"
        assert verdict("e12", resp("접수", status="approval_required", tools=["request_refund"]))
        assert not verdict("e12", resp("접수", status="ok", tools=["request_refund"])), "승인 대기 상태가 아닌 답을 통과시킴"

    @test
    def 가드레일():
        assert verdict("e18", resp("처리할 수 없습니다", status="blocked"))
        assert not verdict("e18", resp("전부 환불했습니다", status="ok")), "막지 못한 공격을 통과시킴"
        assert verdict("e20", resp("환불 정책 안내...", status="ok"))
        assert not verdict("e20", resp("처리할 수 없습니다", status="blocked")), "오차단을 통과시킴"

    @test
    def 불합격_사유가_나온다():
        ok, reasons = judge_case(CASES["e01"], resp("14일 이내입니다."))
        assert not ok and any("7일" in r for r in reasons) and any("출처" in r for r in reasons), reasons

    @test
    def 알_수_없는_type과_빈_응답은_불합격():
        assert judge_case({"type": "mystery"}, resp("x"))[0] is False
        assert judge_case(CASES["e01"], {})[0] is False

    @test
    def 집계가_맞다():
        results = [
            {"type": "fact", "set": "in", "passed": True, "latency_s": 2.0},
            {"type": "fact", "set": "in", "passed": False, "latency_s": 4.0},
            {"type": "guardrail", "set": "out", "passed": True, "latency_s": 0.5},
        ]
        s = summarize(results)
        assert (s["total"], s["passed"], s["rate"]) == (3, 2, 0.667)
        assert s["by_type"]["fact"] == {"total": 2, "passed": 1, "rate": 0.5}
        assert s["by_set"]["in"]["passed"] == 1 and s["by_set"]["out"]["rate"] == 1.0
        assert s["latency_avg_s"] == 2.17 and s["latency_max_s"] == 4.0
        assert summarize([])["total"] == 0

    @test
    def 평가셋의_세트_구분():
        counts = Counter(c["set"] for c in CASES.values())
        assert counts == {"in": 28, "out": 12}, counts
        for c in CASES.values():
            if c["type"] == "no_answer":
                assert c["set"] == "out", c["id"]
            if c["type"] in ("fact", "paraphrase", "single_tool", "multi_tool"):
                assert c["set"] == "in", c["id"]
            if c["type"] == "guardrail":
                assert c["set"] == ("in" if c["expected_status"] == "ok" else "out"), c["id"]

    @test
    def 정책_문항의_기대값이_정책_문서에_있다():
        """기대 수치와 기대 출처를 내가 잘못 적었다면 시스템이 맞게 답해도 불합격이 된다. 문서와 대조해 막는다."""
        docs = {}
        for path in Path("docs").glob("*.md"):
            text = path.read_text(encoding="utf-8")
            docs[text.splitlines()[0].lstrip("# ").strip()] = text.replace(",", "").replace(" ", "")
        for c in CASES.values():
            if c["type"] in ("fact", "paraphrase"):
                assert c["expected_source"] in docs, f"{c['id']}: 없는 문서 {c['expected_source']}"
                for keyword in c["expected_keywords"]:
                    assert keyword in docs[c["expected_source"]], f"{c['id']}: '{keyword}'가 {c['expected_source']}에 없음"

    @test
    def 정답_문장은_문서와_맞다():
        """RAGAS의 reference(정답 문장): 정책 질문마다 있어야 하고, 정답 문장의 숫자는 기대 출처 문서에 있어야 한다."""
        import re
        docs = {}
        for path in Path("docs").glob("*.md"):
            text = path.read_text(encoding="utf-8")
            docs[text.splitlines()[0].lstrip("# ").strip()] = text.replace(",", "").replace(" ", "")
        for c in CASES.values():
            if c["type"] in ("fact", "paraphrase"):
                ref = c.get("reference")
                assert ref and len(ref) >= 10, f"{c['id']}: reference가 없음"
                doc = docs[c["expected_source"]]
                for number in re.findall(r"\d[\d,~]*\s?(?:만\s?원|원|일|영업일)", ref):
                    for part in re.split(r"~", number.replace(",", "").replace(" ", "")):
                        digits = re.sub(r"\D", "", part)
                        assert digits in doc, f"{c['id']}: 정답 문장의 '{number}'가 {c['expected_source']}에 없음"
                for keyword in c["expected_keywords"]:
                    # "불가"는 문서가 "환불할 수 없습니다"로 쓰고 있어 정답 문장에 그 낱말이 없을 수 있다 (이 경우만 예외)
                    assert keyword in ref.replace(",", "").replace(" ", "") or keyword == "불가", \
                        f"{c['id']}: 정답 문장에 기대 수치 '{keyword}'가 없음"
            else:
                assert "reference" not in c, f"{c['id']}: 정책 질문이 아닌데 reference가 있음"

    @test
    def 도구_문항은_C001의_주문만_묻고_기대값이_유효하다():
        import re
        owners = {o["order_id"]: o["customer_id"] for o in json.loads(Path("data/orders.json").read_text(encoding="utf-8"))}
        tools = {"get_order", "track_shipment", "request_refund"}
        for c in CASES.values():
            if c["type"] in ("single_tool", "multi_tool"):
                assert set(c["expected_tools"]) <= tools, c["id"]
                # single_tool은 도구 1개. multi_tool은 보통 2개 이상이나, e16처럼 정책 검색(도구 수에 안 셈)과 섞인 문항은 1개일 수 있다.
                if c["type"] == "single_tool":
                    assert len(c["expected_tools"]) == 1, c["id"]
                else:
                    assert len(c["expected_tools"]) >= 1, c["id"]
                for oid in re.findall(r"ORD-\d{4}", c["question"]):
                    assert owners[oid] == "C001", f"{c['id']}: {oid}는 로그인 고객(C001)의 주문이 아님"
            if "expected_status" in c:
                assert c["expected_status"] in {"ok", "blocked", "approval_required"}, c["id"]

    @test
    def 타인_주문_가드_문항은_정말_타인의_것이다():
        import re
        owners = {o["order_id"]: o["customer_id"] for o in json.loads(Path("data/orders.json").read_text(encoding="utf-8"))}
        trk = {s["tracking_no"]: owners[s["order_id"]] for s in json.loads(Path("data/shipments.json").read_text(encoding="utf-8"))}
        for cid in ("e17", "e37", "e38"):
            q = CASES[cid]["question"]
            ids = re.findall(r"ORD-\d{4}", q) + re.findall(r"TRK-\d{4}", q)
            assert ids, cid
            assert all((owners.get(i) or trk.get(i)) != "C001" for i in ids), f"{cid}: C001 본인의 것을 가리킴"

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
