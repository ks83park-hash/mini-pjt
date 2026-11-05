"""모든 확인 스크립트를 한 번에 돌리고, 확인 도중 프로젝트 파일이 바뀌지 않았는지 검사한다.

실행: python check_all.py          (실제 모델을 부르지 않는 확인만)
      python check_all.py --real   (실제 Bedrock 모델을 부르는 check_agent.py, check_composite.py, check_judge_real.py, check_ragas_real.py, check_refund_safety.py도 포함)

확인 스크립트가 임시 경로 대신 프로젝트 경로(approvals.sqlite, logs/, data/)에 쓰는 실수를 잡는다.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
OFFLINE = [
    "check_data", "check_order_tool", "check_shipment_tool", "check_ownership", "check_refund_rule",
    "check_agent_tools", "check_status", "check_approval", "check_approve", "check_input_guard",
    "check_masking", "check_llm_fallback", "check_eval_rules", "check_tracing", "check_judge", "check_ragas", "check_report", "check_success",
]
REAL = ["check_agent", "check_composite", "check_judge_real", "check_ragas_real", "check_refund_safety"]
GUARDED = ["approvals.sqlite", "logs", "data/refunds.json"]  # 확인 도중 바뀌면 안 되는 프로젝트 파일


def snapshot():
    state = {}
    for rel in GUARDED:
        p = ROOT / rel
        state[rel] = (p.read_bytes() if p.is_file() else sorted(x.name for x in p.iterdir()) if p.is_dir() else None)
    return state


def main():
    names = OFFLINE + (REAL if "--real" in sys.argv else [])
    before = snapshot()
    failed = []
    for name in names:
        if not (ROOT / f"{name}.py").exists():
            print(f"건너뜀(파일 없음): {name}")
            continue
        proc = subprocess.run([sys.executable, str(ROOT / f"{name}.py")], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        lines = [l for l in proc.stdout.splitlines() if l.strip()]
        summary = lines[-1] if lines else "(출력 없음)"
        print(f"{'통과' if proc.returncode == 0 else '실패'}  {name}: {summary}")
        if proc.returncode != 0:
            failed.append(name)
    after = snapshot()
    changed = [rel for rel in GUARDED if before[rel] != after[rel]]
    if changed:
        print(f"실패: 확인 도중 프로젝트 파일이 바뀜 -> {changed} (확인 스크립트가 임시 경로를 쓰는지 점검)")
    print(f"\n{len(names) - len(failed)}/{len(names)} 스크립트 통과" + ("" if not changed else ", 파일 변경 감지"))
    return 1 if failed or changed else 0


if __name__ == "__main__":
    sys.exit(main())
