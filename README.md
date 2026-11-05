# 고객센터 FAQ·주문 봇

환불·교환·배송 정책을 근거로 답하고, 주문 조회·배송 추적·환불 접수까지 처리하는 고객센터 AI 상담 봇입니다. 교육용 프로젝트이며 모든 데이터(고객, 주문, 배송, 환불, 정책 수치)는 직접 만든 가상 값입니다.

- 정책 질문: 정책 문서(환불·교환·배송)를 검색해 근거가 있을 때만 답하고, 답 끝에 `(출처: 문서명)`을 붙입니다. 근거가 없으면 지어내지 않고 "찾을 수 없음"으로 답합니다.
- 주문·배송: 로그인한 고객 본인의 주문만 조회합니다 (타인 주문은 차단).
- 환불: 접수만 하며, 상담원이 승인(`approve`), 수정 승인(`modify`, 금액을 낮춤), 거절(`reject`)해야 환불 기록이 생깁니다. 한 대화에서 3건째부터, 또는 합계 50만 원을 넘으면 접수를 막습니다.
- 가드레일: 프롬프트 인젝션·대량 환불 지시 차단, 개인정보(전화번호·이메일·주소) 마스킹, 차단 사유는 감사 로그에만 기록.

기획은 [SERVICE.md](SERVICE.md), 구현 순서와 진행 상황은 [TASKS.md](TASKS.md)에 있습니다.

## 현재 상태

필수 작업(묶음 1~5)을 마쳤습니다. 에이전트는 1개이며 도구 3종(주문 조회, 배송 추적, 환불 접수)과 정책 검색을 모두 씁니다. 다음은 시간이 되면 하는 선택 작업입니다: 주문·배송·환불 에이전트 분리(Supervisor), MCP 서버, BM25·형태소 분석 검색, LLM 인젝션 판별, 출력 가드.

40문항 평가(3라운드)의 성공 기준 점검 결과는 [evaluation/success_criteria.md](evaluation/success_criteria.md)에 있고, 라운드별 레포트는 [evaluation/round1_report.md](evaluation/round1_report.md), [round2](evaluation/round2_report.md), [round3](evaluation/round3_report.md)입니다. 수치를 읽을 때의 주의점(작은 평가셋, 포화된 점수, 자기 심사 편향 등)이 그 문서에 함께 적혀 있습니다.

## 설치

Python 3.14에서 만들고 확인했습니다. AWS Bedrock(리전 `us-west-2`)의 Claude Sonnet 4.6과 Titan 임베딩 v2를 호출할 수 있는 키가 필요합니다.

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

`.env`에 AWS 키를 채웁니다. 모델 ID와 리전도 여기서 읽으며 코드에 적혀 있지 않습니다. `.env`는 저장소에 올라가지 않습니다.

| 항목 | 설명 |
|------|------|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | Bedrock 호출용 |
| `BEDROCK_MODEL_ID` | 답변 모델 (`us.anthropic.claude-sonnet-4-6`) |
| `EMBEDDING_MODEL_ID` | 임베딩 모델 (`amazon.titan-embed-text-v2:0`) |
| `FALLBACK_MODEL_IDS` | (선택) 답변 모델이 막히면 자동으로 넘어갈 모델 |
| `JUDGE_MODEL_ID` | (선택) 평가 심사 모델. 비우면 답변 모델과 같은 모델 |

설정이 맞는지는 `python check_env.py`로 볼 수 있습니다 (비밀값은 가려서 보여줍니다).

## 실행

처음 한 번, 정책 문서를 검색 인덱스로 만듭니다 (`chroma_db/`가 생깁니다).

```
python index.py
```

서버를 띄웁니다. 프로젝트 폴더에서 실행해야 합니다.

```
python -m uvicorn api:app --port 8000
```

브라우저에서 `http://127.0.0.1:8000/docs`를 열면 API를 직접 시험해 볼 수 있습니다.

### POST /query

```json
{"question": "환불은 수령 후 며칠 이내에 가능한가요?", "customer_id": "C001", "conversation_id": "chat-1"}
```

`customer_id`는 로그인한 고객입니다(더미 고객 `C001`~`C005`). `conversation_id`가 같은 요청끼리 환불 접수 한도(2건, 합계 50만 원)를 공유합니다. 응답:

```json
{"answer": "...", "status": "ok", "tools_called": [], "trace_id": "TR-..."}
```

`status`는 `ok`, `blocked`(가드·본인 확인·한도에서 차단), `approval_required`(환불 접수됨, 승인 대기), `error` 중 하나입니다. `approval_required`이면 `approval_id`가 함께 옵니다.

### POST /approve

```json
{"approval_id": "APV-XXXXXXXX", "decision": "approve", "approver_id": "A001"}
```

`decision`은 `approve`, `modify`(`amount`에 요청보다 낮은 금액), `reject`입니다. 승인자는 더미 상담원 `A001`, `A002`만 인정합니다. 환불 기록(`data/refunds.json`)은 `approve`와 `modify`에서만 생깁니다. `make_data.py`를 실행하면 데이터가 처음 상태로 돌아갑니다.

> 터미널(curl)로 한글을 보낼 때 인코딩 문제로 요청이 거부될 수 있습니다. `/docs` 화면이나 파이썬으로 보내면 됩니다.

## 평가

평가셋은 `tests/eval_set.json`의 40문항입니다 (정책 질문 12, 답변 불가 6, 도구 14, 가드레일 8). 서비스가 처리해야 하는 질문(인 세트 28)과 막거나 거절해야 하는 질문(아웃 세트 12)으로 나눠 집계합니다.

```
python run_eval.py --round 1        # 40문항을 임시 서버로 평가하고 규칙으로 채점 (실제 모델 호출)
python llm_judge.py --round 1       # 정책 질문 답변을 LLM이 심사
python ragas_eval.py --round 1      # RAGAS 지표 (faithfulness, context precision/recall 등)
python eval_report.py --round 1     # evaluation/round1_report.md 생성
python success_criteria.py          # 성공 기준 점검 -> evaluation/success_criteria.md
python check_refund_safety.py       # 승인 없는 환불 0건 확인
```

평가는 임시 데이터와 임시 승인 DB로 돌아서 프로젝트의 `data/`, `approvals.sqlite`를 바꾸지 않습니다.

## 확인 스크립트

```
python check_all.py            # 실제 모델을 부르지 않는 확인 전체 (확인 도중 프로젝트 파일이 바뀌었는지도 검사)
python check_all.py --real     # 실제 모델을 부르는 확인까지 포함
```

## 폴더 구성

| 경로 | 역할 |
|------|------|
| `api.py` | `POST /query`, `POST /approve` |
| `agent.py`, `agent_tools.py`, `tools.py` | 에이전트, 도구 3종, 도구 함수 |
| `ownership.py`, `refund.py`, `approvals.py`, `approval_flow.py` | 본인 확인, 환불 접수와 한도 규칙, 승인 대기 저장, 승인 처리 |
| `guards_input.py`, `guards_refusal.py`, `masking.py` | 입력 가드, 고정 거절 문구와 감사 로그, 개인정보 마스킹 |
| `index.py`, `retrieval.py`, `answer.py` | 정책 문서 인덱스, 검색, 답변 생성 |
| `llm.py`, `llm_fallback.py`, `config.py` | 모델 생성(제한 시간·재시도), 예비 모델 자동 전환, 설정 읽기 |
| `tracing.py` | 실행 기록(`logs/trace.log`) |
| `run_eval.py`, `eval_rules.py`, `llm_judge.py`, `ragas_eval.py`, `ragas_compat.py`, `eval_report.py`, `success_criteria.py` | 평가 |
| `docs/` | 정책 문서 3종 |
| `data/`, `make_data.py` | 가상 데이터와 그 생성기 |
| `evaluation/` | 라운드별 결과·레포트, 성공 기준 점검 |
| `tests/` | 평가셋과 pytest용 테스트 (`pytest`는 설치하지 않았고 실행해 보지 않았습니다) |
| `check_*.py` | 작업별 확인 스크립트 |

## 알려진 한계

- 환불 상태를 고객에게 알려 주는 경로가 없습니다. 승인 결과는 `POST /approve` 응답에만 있고, 고객이 같은 대화에서 받아보는 기능은 아직 없습니다.
- 승인자 인증은 더미입니다. 실서비스에서는 쓸 수 없습니다.
- 대화 한도 집계(`RefundSession`)는 메모리에만 있어 서버를 다시 띄우면 초기화됩니다. 승인 대기는 DB에 남습니다.
- 입력 가드와 마스킹은 정규식 기반이라 모든 변형을 잡지 못합니다. 뚫려도 도구 단계의 한도 규칙과 승인 흐름이 환불 실행을 막습니다.
- 정책 문서가 3개(섹션 9개)라 검색 설정은 이 규모에 맞춰져 있습니다. 문서가 늘면 근거 판정의 거리 기준을 다시 재야 합니다.
- 평가셋이 작고 점수가 포화되어, 성공 기준을 넘었다는 것이 서비스가 충분히 좋다는 뜻은 아닙니다.
