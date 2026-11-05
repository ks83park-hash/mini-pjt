"""ragas를 이 환경에서 쓰기 위한 호환 처리. ragas를 import하기 전에 install()을 부른다.

1) 호환 문제: ragas 0.4.3은 langchain_community에서 이미 제거된 모듈(chat_models.vertexai)을 불러와서, 그대로는
   `import ragas.llms`가 실패한다. 우리는 Vertex AI를 쓰지 않으므로 그 모듈 자리를 비어 있는 클래스로 채운다.
   (라이브러리 파일은 고치지 않는다. 진짜 모듈이 있는 환경이면 아무것도 하지 않는다.)
2) 개인정보: ragas는 기본으로 사용 통계를 외부로 보낸다. 평가 데이터를 내보내지 않도록 끈다 (RAGAS_DO_NOT_TRACK).
3) 경고: ragas의 LangchainLLMWrapper 등은 "곧 사라질 예정" 경고를 낸다. Bedrock은 ragas의 새 방식(instructor 기반)이
   지원하는 제공자(openai, anthropic, google, litellm)에 없어서 이미 설치된 langchain-aws로 연결하는 기존 방식을 쓴다.
   그 경고만 숨긴다 (다른 경고는 그대로 둔다).
"""
import os
import sys
import types
import warnings

_INSTALLED = False


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
    try:
        import langchain_community.chat_models.vertexai  # noqa: F401  (진짜 모듈이 있으면 그대로 쓴다)
    except ImportError:
        stub = types.ModuleType("langchain_community.chat_models.vertexai")
        stub.ChatVertexAI = type("ChatVertexAI", (), {"__doc__": "ragas 호환용 자리 채움 (사용하지 않는다)"})
        sys.modules["langchain_community.chat_models.vertexai"] = stub
    for message in ("LangchainLLMWrapper is deprecated", "LangchainEmbeddingsWrapper is deprecated"):
        warnings.filterwarnings("ignore", message=message, category=DeprecationWarning)
    _INSTALLED = True
