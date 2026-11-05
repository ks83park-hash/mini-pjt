"""평가 실행기: tests/eval_set.json의 문항을 POST /query로 보내 규칙으로 채점하고 결과를 저장한다.

사용
    python run_eval.py --round 1                 # 임시 서버를 이 프로세스 안에서 띄워 평가 (기본)
    python run_eval.py --round 2 --url http://127.0.0.1:8000/query     # 이미 떠 있는 서버로 평가
    python run_eval.py --round 1 --only e01,e07  # 일부 문항만

동작
- 기본 모드는 임시 데이터 복사본·임시 승인 DB·임시 감사 로그를 쓰는 서버를 띄운다. 프로젝트의 data/, approvals.sqlite,
  logs/는 바뀌지 않는다. (--url 모드는 그 서버의 상태를 그대로 쓰므로 환불 접수가 쌓일 수 있다.)
- 문항마다 대화 번호(conversation_id)를 새로 만들어 대량 환불 집계가 문항 사이에 섞이지 않게 한다. 로그인 고객은 C001이다.
- 응답의 trace_id로 실행 기록(tracing.py)을 찾아, 문항마다 서버 처리 시간(server_ms)·거친 단계(steps)·검색해서 근거로 쓴
  문서 내용(contexts)·응답한 모델을 결과에 담는다. contexts는 5-4의 RAGAS 지표가 쓴다. 기록 파일을 읽을 수 있어야 하므로
  임시 서버 모드에서는 자동으로, --url 모드에서는 --trace-file로 서버의 기록 파일 경로를 줄 때만 담긴다.
- 채점은 eval_rules.py의 규칙 판정이다. 결과는 evaluation/roundN_results.json에 저장한다
  (라운드 레포트 roundN_report.md는 5-5에서 이 결과로 만든다).
- 문항 하나가 실패하거나 요청이 오류여도 멈추지 않고 그 문항을 불합격으로 기록한 뒤 계속한다.
"""
import argparse
import json
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from eval_rules import SETS, judge_case, summarize
from tracing import load_traces

ROOT = Path(__file__).parent
EVAL_SET = ROOT / "tests" / "eval_set.json"
OUT_DIR = ROOT / "evaluation"
CUSTOMER_ID = "C001"
TIMEOUT_S = 120


def load_cases(only=None):
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    if only:
        wanted = {x.strip() for x in only.split(",") if x.strip()}
        cases = [c for c in cases if c["id"] in wanted]
    return cases


def ask(url, question, conversation_id):
    body = json.dumps({"question": question, "customer_id": CUSTOMER_ID, "conversation_id": conversation_id}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def start_temp_server():
    """임시 상태(데이터 복사본·승인 DB·감사 로그·실행 기록)로 서버를 띄우고 (url, 종료 함수, 실행 기록 경로)를 돌려준다."""
    import uvicorn

    from api import build_app

    root = Path(tempfile.mkdtemp(prefix="eval_"))
    shutil.copytree(ROOT / "data", root / "data")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = build_app(data_dir=root / "data", approval_path=root / "approvals.sqlite", audit_path=root / "audit.log", trace_path=root / "trace.log")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):  # 서버가 뜰 때까지 최대 10초
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return f"http://127.0.0.1:{port}/query", lambda: setattr(server, "should_exit", True), root / "trace.log"


def run_cases(cases, url, round_no, trace_path=None, log=print):
    results = []
    for i, case in enumerate(cases, 1):
        started = time.time()
        try:
            resp = ask(url, case["question"], f"eval-r{round_no}-{case['id']}")
            error = None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            resp, error = {}, f"요청 실패: {type(e).__name__}"
        latency = round(time.time() - started, 2)
        if error:
            passed, reasons = False, [error]
        else:
            passed, reasons = judge_case(case, resp)
        trace = (load_traces(trace_path).get(resp.get("trace_id")) if trace_path and resp.get("trace_id") else None) or {}
        steps = trace.get("steps", [])
        results.append({
            "id": case["id"], "type": case["type"], "set": case.get("set", "in"), "question": case["question"],
            "answer": resp.get("answer"), "status": resp.get("status"), "tools_called": resp.get("tools_called"),
            "latency_s": latency, "passed": passed, "reasons": reasons,
            # 실행 기록에서 가져온 것 (기록을 읽을 수 없으면 None)
            "trace_id": resp.get("trace_id"), "server_ms": trace.get("total_ms"), "model": trace.get("model"),
            "steps": [{k: s[k] for k in ("tool", "outcome", "ms") if k in s} for s in steps] if trace else None,
            "contexts": [text for s in steps if s.get("tool") == "search_policy" for text in s.get("contexts", [])] if trace else None,
        })
        log(f"[{i:2d}/{len(cases)}] {'통과' if passed else '실패'} {case['id']} ({case['type']}, {case.get('set', 'in')}) "
            f"{latency:.1f}s" + ("" if passed else f" - {'; '.join(reasons)}"))
    return results


def print_summary(summary, log=print):
    log("")
    log(f"전체: {summary['passed']}/{summary['total']} 통과 ({summary['rate'] * 100:.0f}%)")
    log("유형별:")
    for name, row in summary["by_type"].items():
        log(f"  {name:<12} {row['passed']}/{row['total']}")
    log("세트별:")
    for name in SETS:
        if name in summary["by_set"]:
            row = summary["by_set"][name]
            label = "인(in)  처리해야 하는 질문" if name == "in" else "아웃(out) 막거나 거절할 질문"
            log(f"  {label:<24} {row['passed']}/{row['total']}")
    log(f"응답 시간: 평균 {summary['latency_avg_s']}초, 최대 {summary['latency_max_s']}초")


def save_results(round_no, results, summary, mode, out_dir=OUT_DIR):
    from config import fallback_model_ids, load_settings

    settings = load_settings()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"round{round_no}_results.json"
    payload = {
        "round": round_no,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "models": {"answer": settings["BEDROCK_MODEL_ID"], "fallback": fallback_model_ids(settings), "region": settings["AWS_REGION"]},
        "summary": summary,
        "results": results,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="평가셋을 POST /query로 보내 규칙으로 채점한다.")
    parser.add_argument("--round", type=int, required=True, help="라운드 번호 (결과 파일 이름에 쓰인다)")
    parser.add_argument("--url", help="이미 떠 있는 서버의 /query 주소. 없으면 임시 서버를 띄운다")
    parser.add_argument("--only", help="쉼표로 구분한 문항 id만 실행 (예: e01,e07)")
    parser.add_argument("--trace-file", help="--url 모드에서 서버의 실행 기록 파일(logs/trace.log) 경로. 주면 contexts 등을 결과에 담는다")
    args = parser.parse_args(argv)

    cases = load_cases(args.only)
    if not cases:
        print("실행할 문항이 없습니다. --only 값을 확인하세요.")
        return 1
    stop, trace_path = None, args.trace_file
    if args.url:
        url, mode = args.url, "external"
    else:
        url, stop, trace_path = start_temp_server()
        mode = "temp_server"
    try:
        print(f"라운드 {args.round}: {len(cases)}문항 평가 ({mode})")
        results = run_cases(cases, url, args.round, trace_path)
    finally:
        if stop:
            stop()
    summary = summarize(results)
    print_summary(summary)
    path = save_results(args.round, results, summary, mode)
    print(f"\n결과 저장: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
