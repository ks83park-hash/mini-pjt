"""LLM 한 번 호출 확인: python first_call.py [질문]"""
import sys

from llm import build_llm, get_text


def main():
    question = " ".join(sys.argv[1:]) or "안녕"
    llm = build_llm()
    try:
        reply = llm.invoke(question)
    except Exception as e:  # 인증·권한·리전 문제를 알아보기 쉽게 안내
        print(f"호출 실패: {type(e).__name__}: {e}")
        print(".env의 AWS 키·리전·모델 ID, Bedrock 모델 접근 권한을 확인하세요.")
        return 1
    print(get_text(reply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
