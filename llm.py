"""LLM 만들기와 응답 텍스트 꺼내기.

- 모델 ID와 리전은 .env(config.py)에서 읽는다. 코드에 박지 않는다.
- 모듈 최상단에서는 모델을 만들지 않는다. build_llm()을 부를 때 만든다 (lazy import).
- 다른 코드에서는 build_*(llm=None)처럼 llm을 주입받아, 테스트에서 가짜 모델로 바꿀 수 있게 한다.
"""
from config import load_settings


def build_llm(settings=None, model_id=None):
    """Bedrock Converse 모델을 만든다. model_id를 주면 .env의 모델 대신 그 모델을 쓴다."""
    from langchain_aws import ChatBedrockConverse  # 무거운 import는 호출 시점에

    settings = settings or load_settings()
    return ChatBedrockConverse(
        model=model_id or settings["BEDROCK_MODEL_ID"],
        region_name=settings["AWS_REGION"],
        temperature=0,
    )


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
