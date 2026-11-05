"""예비 모델로 자동 전환하는 채팅 모델 묶음.

- 기본 모델이 한도 초과(ThrottlingException)·장애 등으로 막히면 다음 모델로 같은 요청을 다시 보낸다.
- 막힌 모델은 cooldown 초 동안 건너뛴다 (매 호출마다 재시도 대기로 느려지는 것을 막는다).
  모든 모델이 쿨다운 중이면 원래 순서대로 다시 시도한다.
- 모두 실패하면 마지막 예외를 그대로 던진다. 잡는 예외는 Bedrock 호출 오류(botocore)뿐이다.
- 에이전트(create_react_agent)에 넣을 수 있게 bind_tools를 지원한다. 상태(쿨다운)는 같은 모델 구성끼리 프로세스 안에서 공유한다.
- 모델 객체는 호출하는 쪽(llm.build_llm_chain)이 만들어 넘긴다. 이 모듈은 모델을 만들지 않는다.
"""
import time

from botocore.exceptions import BotoCoreError, ClientError
from langchain_core.runnables import Runnable

RETRYABLE = (ClientError, BotoCoreError)

# 같은 모델 구성(이름 목록)이면 에이전트를 새로 만들어도 "막힌 모델" 기록을 함께 쓴다.
# 대화마다 에이전트를 새로 만들기 때문에, 이게 없으면 매번 한도 재시도를 기다리게 된다.
_SHARED_STATES = {}


class FallbackChat(Runnable):
    def __init__(self, models, names=None, cooldown=120, _state=None):
        self.models = list(models)
        self.names = list(names) if names else [f"model-{i}" for i in range(len(self.models))]
        self.cooldown = cooldown
        if _state is None:
            _state = _SHARED_STATES.setdefault(tuple(self.names), {"blocked_until": {}, "last_used": None})
        self._state = _state

    @property
    def last_used(self):
        """마지막으로 응답한 모델 이름 (로그·확인용)."""
        return self._state["last_used"]

    def bind_tools(self, tools, **kwargs):
        bound = [m.bind_tools(tools, **kwargs) for m in self.models]
        return FallbackChat(bound, self.names, self.cooldown, self._state)

    def _order(self):
        now = time.monotonic()
        blocked = self._state["blocked_until"]
        ready = [i for i in range(len(self.models)) if blocked.get(i, 0) <= now]
        return ready or list(range(len(self.models)))

    def invoke(self, input, config=None, **kwargs):
        last_error = None
        for i in self._order():
            try:
                result = self.models[i].invoke(input, config, **kwargs)
            except RETRYABLE as e:
                last_error = e
                self._state["blocked_until"][i] = time.monotonic() + self.cooldown
                continue
            self._state["last_used"] = self.names[i]
            return result
        raise last_error
