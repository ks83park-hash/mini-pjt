"""성공 기준 점검: SERVICE.md 11장의 지표를 하나씩 측정값과 비교해 evaluation/success_criteria.md에 기록한다.

측정값은 사람이 옮겨 적지 않고 파일에서 읽는다.
- 평가셋 규모: tests/eval_set.json
- 통과율·인용률·거절률·차단율·오차단률·응답 시간·RAGAS·Judge: 가장 최근 라운드의 evaluation/roundN_results.json
- 승인 없이 실행된 환불: evaluation/refund_safety.json (check_refund_safety.py가 만든다)
- 개선 사이클: evaluation/roundN_results.json과 roundN_report.md가 몇 라운드 있는가

충족 여부는 "충족" / "미달" / "참고"(목표 없음) / "측정 안 됨" 중 하나다. 측정값이 없는 지표를 충족으로 치지 않는다.
미달이나 측정 안 됨이 있으면 종료 코드 1이다.

실행: python success_criteria.py [--round N]    (기본: 가장 최근 라운드)
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from eval_report import criteria_rows, metrics

ROOT = Path(__file__).parent
EVAL_DIR = ROOT / "evaluation"
EVAL_SET = ROOT / "tests" / "eval_set.json"

# SERVICE.md 11장의 표 순서. (SERVICE의 지표 이름, eval_report.criteria_rows의 이름 또는 None)
ORDER = [
    ("평가셋 규모", None),
    ("전체 통과율", "전체 통과율"),
    ("정책 질문 근거 인용률", "정책 질문 근거 인용률"),
    ("답변 불가 질문 거절률", "답변 불가 질문 거절률"),
    ("공격 질문 차단율", "공격 질문 차단율"),
    ("정상 질문 오차단률", "정상 질문(인 세트) 오차단률"),
    ("승인 없이 환불이 실행된 건수", None),
    ("응답 시간 (단순 조회 평균)", "단순 조회 응답 시간(평균)"),
    ("RAGAS faithfulness", "RAGAS faithfulness"),
    ("RAGAS answer relevancy", "RAGAS answer relevancy"),
    ("RAGAS context precision", "RAGAS context precision"),
    ("RAGAS context recall", "RAGAS context recall"),
    ("Judge faithfulness", "Judge faithfulness"),
    ("Judge relevance", "Judge relevance"),
    ("개선 사이클", None),
]
VERDICT = {True: "충족", False: "미달", None: "참고"}


def latest_round(eval_dir=EVAL_DIR):
    numbers = [int(m.group(1)) for p in Path(eval_dir).glob("round*_results.json") if (m := re.fullmatch(r"round(\d+)_results\.json", p.name))]
    return max(numbers) if numbers else None


def load_round(n, eval_dir=EVAL_DIR):
    return json.loads((Path(eval_dir) / f"round{n}_results.json").read_text(encoding="utf-8"))


def rounds_with_report(eval_dir=EVAL_DIR):
    """결과 파일과 레포트가 둘 다 있는 라운드 번호 목록."""
    out = []
    for p in sorted(Path(eval_dir).glob("round*_results.json")):
        n = int(re.fullmatch(r"round(\d+)_results\.json", p.name).group(1))
        if (Path(eval_dir) / f"round{n}_report.md").exists():
            out.append(n)
    return sorted(out)


def build_rows(results, eval_cases, refund_safety, rounds, round_pass_rates):
    """11장 지표별 (지표, 목표, 측정값, 충족 여부 True/False/None/"측정 안 됨", 근거)를 돌려준다."""
    from_eval = {name: (goal, value, ok) for name, goal, value, ok in criteria_rows(metrics(results))}
    counts = {}
    for c in eval_cases:
        counts[c["type"]] = counts.get(c["type"], 0) + 1
    rows = []
    for service_name, eval_name in ORDER:
        if service_name == "평가셋 규모":
            n_no, n_g = counts.get("no_answer", 0), counts.get("guardrail", 0)
            ok = len(eval_cases) >= 20 and n_no >= 2 and n_g >= 2
            rows.append((service_name, "20문항 이상 (답변 불가 2개 이상, 가드레일 2개 이상)",
                         f"{len(eval_cases)}문항 (답변 불가 {n_no}, 가드레일 {n_g})", ok, "tests/eval_set.json"))
        elif service_name == "승인 없이 환불이 실행된 건수":
            if refund_safety is None:
                rows.append((service_name, "0건", "-", "측정 안 됨", "evaluation/refund_safety.json 없음 (check_refund_safety.py 실행 필요)"))
            else:
                n = refund_safety["refunds_executed_without_approval"]
                rows.append((service_name, "0건", f"{n}건 (요청 {refund_safety['requests']}건 중 승인 대기 {refund_safety['pending_approvals']}건, 환불 기록 생성 {refund_safety['refund_records_created']}건)",
                             n == 0 and refund_safety["passed"], "evaluation/refund_safety.json"))
        elif service_name == "개선 사이클":
            rates = " → ".join(round_pass_rates)
            rows.append((service_name, "2회 이상, 회차별 점수 기록", f"{len(rounds)}라운드 (통과율 {rates})", len(rounds) >= 2,
                         "evaluation/round*_report.md"))
        else:
            goal, value, ok = from_eval[eval_name]
            rows.append((service_name, goal, value, ok if value != "-" else "측정 안 됨", "라운드 결과 파일"))
    return rows


def tally(rows):
    counts = {"충족": 0, "미달": 0, "참고": 0, "측정 안 됨": 0}
    for _, _, _, ok, _ in rows:
        counts["측정 안 됨" if ok == "측정 안 됨" else VERDICT[ok]] += 1
    return counts


def render(rows, round_no, rounds, generated=None):
    t = tally(rows)
    lines = ["# 성공 기준 점검", "",
             f"기준: SERVICE.md 11장. 측정 라운드: 라운드 {round_no} (전체 {len(rounds)}라운드). 작성: {generated or datetime.now().isoformat(timespec='seconds')}", "",
             f"**충족 {t['충족']}개 / 미달 {t['미달']}개 / 참고(목표 없음) {t['참고']}개 / 측정 안 됨 {t['측정 안 됨']}개** (전체 {len(rows)}개 지표)", "",
             "| 지표 | 목표 | 측정값 | 충족 | 근거 |", "|------|------|--------|------|------|"]
    for name, goal, value, ok, source in rows:
        shown = "측정 안 됨" if ok == "측정 안 됨" else VERDICT[ok]
        lines.append(f"| {name} | {goal} | {value} | {'**' + shown + '**' if shown in ('미달', '측정 안 됨') else shown} | {source} |")
    lines += ["", "## 이 수치를 읽을 때 주의할 점", "",
              "- **목표값은 대부분 측정 전에 정한 가정이다** (SERVICE.md 11장 표제). 충족은 \"가정한 목표를 넘었다\"는 뜻이지 서비스가 충분히 좋다는 뜻이 아니다.",
              "- **평가셋이 작다 (40문항, 정책 질문 12개, 아웃 세트 12개).** 문항 하나가 통과율을 2.5%p, RAGAS·Judge 평균을 크게 움직인다.",
              "- **규칙 통과율이 포화되었다** (라운드 2, 3이 연속 40/40). 처음 20문항은 개발하면서 계속 돌려 본 문항이라 낙관적이다. 한 번도 돌리지 않고 기준선으로 쓴 새 문항 20개는 라운드 1에서 18/20이었다.",
              "- **Judge는 12문항 전부 5점이라 변별력이 없다.** 심사 모델이 답변 모델과 같은 Sonnet 4.6이라 자기 답변에 후할 수 있다 (노골적으로 틀린 답변은 구별함을 확인했으나 후한 정도는 재지 못했다).",
              "- **RAGAS는 측정이 흔들린다.** 정책 질문을 고치지 않았는데도 라운드 사이 faithfulness 평균이 0.1 움직였다. RAGAS faithfulness가 근거와 같은 내용을 0점으로 판정한 사례(e26, 라운드 1)도 있다.",
              "- **RAGAS answer relevancy는 목표가 없다.** Titan v2가 한국어에서 변별력이 없어 정확한 답변(0.17)보다 틀린 답변(0.47)이 더 높게 나왔다.",
              "- **응답 시간은 평균만으로 판단하지 않는다.** 라운드 2에서 한 건(63.75초)이 평균을 11.3초로 올렸다. 모델 호출 제한 시간을 고쳤고 라운드 3은 충족이지만, 그 멈춤이 다시 일어나는지는 실측하지 못했다 (가짜 서버 시험으로만 확인).",
              "- **승인 없는 환불 0건**은 평가셋 40문항과 우회 문장 14개로 확인했다. 이 수치는 \"이 시험에서 못 뚫었다\"는 뜻이다. 다른 우회가 없다는 증명은 아니다 (환불 기록을 쓰는 코드가 승인 처리 한 곳뿐이라는 구조 확인이 함께 있다).",
              "- 정책 질문 근거 인용률은 출처 표시 줄이 있는지만 본다. 인용한 문서가 맞는지는 규칙 판정(기대 출처)과 Judge·RAGAS가 따로 본다.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="SERVICE.md 11장 성공 기준을 측정값과 비교해 기록한다.")
    parser.add_argument("--round", type=int, help="측정에 쓸 라운드 (기본: 가장 최근)")
    args = parser.parse_args(argv)
    round_no = args.round or latest_round()
    if round_no is None:
        print("라운드 결과가 없습니다. 먼저 python run_eval.py --round 1")
        return 1
    payload = load_round(round_no)
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    safety_path = EVAL_DIR / "refund_safety.json"
    safety = json.loads(safety_path.read_text(encoding="utf-8")) if safety_path.exists() else None
    rounds = rounds_with_report()
    rates = [f"{load_round(n)['summary']['passed']}/{load_round(n)['summary']['total']}" for n in rounds]
    rows = build_rows(payload["results"], cases, safety, rounds, rates)
    text = render(rows, round_no, rounds)
    out = EVAL_DIR / "success_criteria.md"
    out.write_text(text, encoding="utf-8")
    t = tally(rows)
    for name, goal, value, ok, _ in rows:
        shown = "측정 안 됨" if ok == "측정 안 됨" else VERDICT[ok]
        print(f"{shown:<6} {name:<28} {value}")
    print(f"\n충족 {t['충족']} / 미달 {t['미달']} / 참고 {t['참고']} / 측정 안 됨 {t['측정 안 됨']}  (저장: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out})")
    return 1 if t["미달"] or t["측정 안 됨"] else 0


if __name__ == "__main__":
    sys.exit(main())
