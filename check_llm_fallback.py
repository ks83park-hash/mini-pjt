"""예비 모델 자동 전환 확인 (실제 호출 없이 가짜 모델로 검사)."""
import socket
import sys
import threading
import time

from botocore.exceptions import BotoCoreError, ClientError

from llm_fallback import _SHARED_STATES, FallbackChat

THROTTLE = ClientError({"Error": {"Code": "ThrottlingException", "Message": "Too many tokens per day"}}, "Converse")


class Fake:
    def __init__(self, name, error=None):
        self.name, self.error, self.calls, self.tools = name, error, 0, None

    def invoke(self, input, config=None, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return f"{self.name}-응답"

    def bind_tools(self, tools, **kw):
        self.tools = tools
        return self


def fresh(names):
    _SHARED_STATES.pop(tuple(names), None)


def main():
    tests = {}

    def test(fn):
        tests[fn.__name__] = fn
        return fn

    @test
    def 기본_모델이_되면_예비를_쓰지_않는다():
        fresh(["a", "b"]); a, b = Fake("a"), Fake("b")
        chat = FallbackChat([a, b], ["a", "b"])
        assert chat.invoke("x") == "a-응답" and b.calls == 0 and chat.last_used == "a"

    @test
    def 한도_오류가_나면_예비_모델로_전환한다():
        fresh(["a2", "b2"]); a, b = Fake("a", THROTTLE), Fake("b")
        chat = FallbackChat([a, b], ["a2", "b2"])
        assert chat.invoke("x") == "b-응답" and chat.last_used == "b2"

    @test
    def 막힌_모델은_쿨다운_동안_건너뛴다():
        fresh(["a3", "b3"]); a, b = Fake("a", THROTTLE), Fake("b")
        chat = FallbackChat([a, b], ["a3", "b3"])
        chat.invoke("x"); chat.invoke("y"); chat.invoke("z")
        assert a.calls == 1 and b.calls == 3, (a.calls, b.calls)

    @test
    def 새로_만든_묶음도_막힌_기록을_공유한다():
        fresh(["a4", "b4"]); a, b = Fake("a", THROTTLE), Fake("b")
        FallbackChat([a, b], ["a4", "b4"]).invoke("x")
        FallbackChat([a, b], ["a4", "b4"]).invoke("y")   # 에이전트를 새로 만든 상황
        assert a.calls == 1

    @test
    def 쿨다운이_지나면_기본_모델로_돌아온다():
        fresh(["a5", "b5"]); a, b = Fake("a", THROTTLE), Fake("b")
        chat = FallbackChat([a, b], ["a5", "b5"], cooldown=0)
        chat.invoke("x"); a.error = None
        assert chat.invoke("y") == "a-응답"

    @test
    def 모두_막히면_마지막_오류를_던진다():
        fresh(["a6", "b6"])
        chat = FallbackChat([Fake("a", THROTTLE), Fake("b", THROTTLE)], ["a6", "b6"])
        try:
            chat.invoke("x"); raise AssertionError("예외가 나와야 함")
        except ClientError:
            pass

    @test
    def 호출_오류가_아닌_예외는_전환하지_않는다():
        fresh(["a7", "b7"]); b = Fake("b")
        chat = FallbackChat([Fake("a", ValueError("코드 버그")), b], ["a7", "b7"])
        try:
            chat.invoke("x"); raise AssertionError("예외가 나와야 함")
        except ValueError:
            assert b.calls == 0

    @test
    def 도구를_묶어도_전환이_동작한다():
        fresh(["a8", "b8"]); a, b = Fake("a", THROTTLE), Fake("b")
        bound = FallbackChat([a, b], ["a8", "b8"]).bind_tools(["t"])
        assert b.tools == ["t"] and bound.invoke("x") == "b-응답"

    # ---------------------------------------------------------------- 응답 시간 (멈춘 호출 대응)
    def hung_server():
        """연결은 받지만 응답을 주지 않는 서버 (모델 호출이 멈추는 상황). (포트, 종료 함수)를 돌려준다."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        held, stop = [], threading.Event()

        def accept_loop():
            srv.settimeout(0.2)
            while not stop.is_set():
                try:
                    held.append(srv.accept()[0])   # 받아 두기만 하고 답하지 않는다
                except OSError:
                    continue

        threading.Thread(target=accept_loop, daemon=True).start()

        def close():
            stop.set()
            for c in held:
                c.close()
            srv.close()
        return srv.getsockname()[1], close

    @test
    def 답변용_모델은_짧은_제한_시간과_재시도_횟수를_쓴다():
        import llm
        cfg = llm.build_llm().client.meta.config
        assert cfg.read_timeout == llm.ANSWER_READ_TIMEOUT_S == 15 and cfg.connect_timeout == llm.CONNECT_TIMEOUT_S == 5,             (cfg.read_timeout, cfg.connect_timeout)
        assert cfg.retries == {"total_max_attempts": 3, "mode": "standard"}, cfg.retries
        judge = llm.build_llm(read_timeout=llm.JUDGE_READ_TIMEOUT_S).client.meta.config
        assert judge.read_timeout == 60, "심사 모델은 기다릴 수 있다"

    @test
    def 예비_모델이_있으면_앞_모델은_한_번만_재시도한다():
        import llm
        settings = {"AWS_REGION": "us-west-2", "BEDROCK_MODEL_ID": "a-model", "FALLBACK_MODEL_IDS": "b-model,c-model"}
        chain = llm.build_llm_chain(settings)
        attempts = [m.client.meta.config.retries["total_max_attempts"] for m in chain.models]
        assert attempts == [2, 2, 3], f"앞 모델 둘은 2회, 마지막은 3회여야 함: {attempts}"
        single = llm.build_llm_chain({"AWS_REGION": "us-west-2", "BEDROCK_MODEL_ID": "a-model", "FALLBACK_MODEL_IDS": ""})
        assert single.client.meta.config.retries["total_max_attempts"] == 3, "예비 모델이 없으면 유일한 모델이 끝까지 재시도"

    @test
    def 멈춘_모델_호출은_제한_시간_안에_끊긴다():
        import llm
        port, close = hung_server()
        try:
            model = llm.build_llm(read_timeout=1, max_attempts=2, endpoint_url=f"http://127.0.0.1:{port}")
            started = time.time()
            try:
                model.invoke("안녕")
                raise AssertionError("멈춘 서버인데 응답이 옴")
            except BotoCoreError:
                pass   # ReadTimeoutError는 BotoCoreError라서 FallbackChat이 잡는다
            elapsed = time.time() - started
            assert elapsed < 8, f"제한 시간 1초, 총 2회 시도인데 {elapsed:.1f}초 걸림"
            assert elapsed >= 1.5, f"제한 시간이 적용되지 않은 것 같음 ({elapsed:.1f}초)"
        finally:
            close()

    @test
    def 멈춘_모델은_예비_모델로_넘어가고_다음_호출은_기다리지_않는다():
        import llm
        fresh(["hung", "backup"])
        port, close = hung_server()
        try:
            hung = llm.build_llm(read_timeout=1, max_attempts=2, endpoint_url=f"http://127.0.0.1:{port}")
            chain = FallbackChat([hung, Fake("backup")], ["hung", "backup"], cooldown=60)
            started = time.time()
            assert chain.invoke("안녕") == "backup-응답" and chain.last_used == "backup"
            first = time.time() - started
            assert first < 8, f"첫 호출이 {first:.1f}초 걸림 (기존에는 60초 제한이라 1분 이상)"
            started = time.time()
            assert chain.invoke("또") == "backup-응답"
            second = time.time() - started
            assert second < 0.5, f"쿨다운 중인 멈춘 모델을 또 기다림 ({second:.1f}초)"
        finally:
            close()

    @test
    def 쿨다운_기본값은_길지_않다():
        assert FallbackChat([Fake("x")]).cooldown == 120, "일시적인 멈춤에 10분이나 약한 모델로 떨어지면 안 됨"

    failed = 0
    for name, fn in tests.items():
        try:
            fn(); print("통과:", name)
        except AssertionError as e:
            failed += 1; print("실패:", name, e)
    print(f"{len(tests) - failed}/{len(tests)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
