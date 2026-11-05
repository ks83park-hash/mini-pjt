"""LLM 만들기와 응답 텍스트 꺼내기.

- 모델 ID와 리전은 .env(config.py)에서 읽는다. 코드에 박지 않는다.
- 모듈 최상단에서는 모델을 만들지 않는다. build_llm()을 부를 때 만든다 (lazy import).
- 다른 코드에서는 build_*(llm=None)처럼 llm을 주입받아, 테스트에서 가짜 모델로 바꿀 수 있게 한다.

응답 시간 (라운드 2에서 문항 하나가 63.75초 걸렸다: 서버 처리 63,749ms 중 도구는 4ms)
- botocore의 기본값은 읽기 제한 60초, 연결 제한 60초, 최대 5회 재시도라서, 모델 호출이 한 번 멈추면 사용자가 1분을 기다린다
  (첫 시도가 60초 제한에 걸려 끊기고 재시도가 3.7초에 성공한 것과 숫자가 맞는다).
- 그래서 답변용 모델은 읽기 제한 15초(정상 응답은 길어도 8초 안팎), 연결 제한 5초로 둔다. 멈춘 호출을 빨리 끊고
  재시도하거나 예비 모델로 넘어간다. 예비 모델이 있으면 앞 모델은 시도 2회(한 번만 재시도), 마지막 모델은 3회다.
- 평가 심사(Judge, RAGAS)는 사람이 기다리지 않는 작업이고 출력이 길 수 있어 읽기 제한을 60초로 둔다.
"""
from config import fallback_model_ids, load_settings

ANSWER_READ_TIMEOUT_S = 15
JUDGE_READ_TIMEOUT_S = 60
CONNECT_TIMEOUT_S = 5
LAST_MODEL_ATTEMPTS = 3   # 더 넘길 곳이 없는 마지막(또는 유일한) 모델의 총 시도 횟수
FALLBACK_FRONT_ATTEMPTS = 2   # 예비 모델이 뒤에 있는 모델의 총 시도 횟수


def bedrock_config(read_timeout, max_attempts):
    """botocore 클라이언트 설정: 제한 시간과 총 시도 횟수(첫 시도 포함)를 정한다."""
    from botocore.config import Config

    return Config(read_timeout=read_timeout, connect_timeout=CONNECT_TIMEOUT_S,
                  retries={"total_max_attempts": max_attempts, "mode": "standard"})


def build_llm(settings=None, model_id=None, read_timeout=ANSWER_READ_TIMEOUT_S, max_attempts=LAST_MODEL_ATTEMPTS,
              endpoint_url=None):
    """Bedrock Converse 모델을 만든다. model_id를 주면 .env의 모델 대신 그 모델을 쓴다.

    read_timeout(초)과 max_attempts(총 시도 횟수)로 멈춘 호출을 얼마나 기다릴지 정한다.
    endpoint_url은 가짜 서버를 가리키는 시험용이다 (평소에는 쓰지 않는다).
    """
    from langchain_aws import ChatBedrockConverse  # 무거운 import는 호출 시점에

    settings = settings or load_settings()
    extra = {"endpoint_url": endpoint_url} if endpoint_url else {}
    return ChatBedrockConverse(
        model=model_id or settings["BEDROCK_MODEL_ID"],
        region_name=settings["AWS_REGION"],
        temperature=0,
        config=bedrock_config(read_timeout, max_attempts),
        **extra,
    )


def build_llm_chain(settings=None, llm=None):
    """기본 모델 + 예비 모델(.env의 FALLBACK_MODEL_IDS)을 묶어, 막히면 자동 전환하는 모델을 만든다.

    예비 모델이 없으면 기본 모델 하나만 쓴다. llm을 주면(테스트용) 그대로 돌려준다.
    """
    if llm is not None:
        return llm
    settings = settings or load_settings()
    ids = [settings["BEDROCK_MODEL_ID"]] + [m for m in fallback_model_ids(settings) if m != settings["BEDROCK_MODEL_ID"]]
    if len(ids) == 1:
        return build_llm(settings)
    from llm_fallback import FallbackChat  # 예비 모델이 있을 때만 불러온다

    # 앞 모델은 한 번만 재시도하고 막히면 바로 다음 모델로 넘어간다. 마지막 모델만 끝까지 재시도한다.
    models = [build_llm(settings, model_id=m, max_attempts=FALLBACK_FRONT_ATTEMPTS if i < len(ids) - 1 else LAST_MODEL_ATTEMPTS)
              for i, m in enumerate(ids)]
    return FallbackChat(models, names=ids)


def get_text(message):
    """응답 content가 문자열이든 블록 리스트든 텍스트만 모아 돌려준다."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)
