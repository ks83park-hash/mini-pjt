"""답변 만들기: 검색 결과를 근거로 답하고 출처를 붙인다.

흐름
1. 검색(retrieval.retrieve) → 근거 있음 판정(retrieval.assess_retrieval, Python 규칙)
2. 근거가 없으면 모델을 부르지 않고 고정 거절 문구를 돌려준다.
3. 근거가 있으면 모델이 근거만 보고 답한다. 근거에 답이 없으면 모델이 NO_ANSWER 표지를 낸다
   (예: "해외 배송도 되나요?" — 문서와 가까워 보이지만 답은 없는 경우).
4. 출처는 모델이 쓴 "사용한 문서" 줄을 읽되, 검색된 문서명에 있는 것만 Python이 걸러 붙인다.

llm, db는 주입받을 수 있다 (테스트에서 가짜로 바꾸기 위함).
"""
import re

from llm import build_llm, get_text
from retrieval import assess_retrieval, retrieve

NO_ANSWER_REPLY = (
    "죄송합니다. 문의하신 내용은 정책 문서에서 찾을 수 없습니다. "
    "환불·교환·배송 정책에 관한 내용을 질문해 주세요."
)
NO_ANSWER_MARK = "NO_ANSWER"
SOURCE_LINE = re.compile(r"^\s*사용한 문서\s*:\s*(.+?)\s*$", re.MULTILINE)

SYSTEM_PROMPT = f"""당신은 쇼핑몰 고객센터 상담 봇입니다. 아래 [근거]에 적힌 내용만으로 한국어로 짧고 정확하게 답하세요.

규칙
- [근거]에 질문의 답이 직접 들어 있을 때만 답합니다. 기간·금액·횟수는 근거에 적힌 숫자 그대로 씁니다.
- 근거에 없는 내용은 추측하거나 지어내지 않습니다.
- [근거]에 질문의 답이 없으면 다른 말 없이 {NO_ANSWER_MARK} 한 단어만 출력합니다.
- 답을 했다면 마지막 줄에 "사용한 문서: 문서명" 형식으로 실제로 쓴 문서 이름만 적습니다. 여러 개면 쉼표로 구분합니다.
"""


def format_context(results):
    """검색 결과를 프롬프트에 넣을 [근거] 텍스트로 만든다."""
    blocks = [f"[문서: {doc.metadata['source']}]\n{doc.page_content}" for doc, _ in results]
    return "\n\n".join(blocks)


def parse_reply(text, allowed_sources):
    """모델 출력에서 (답변 본문, 출처 목록)을 뽑는다. NO_ANSWER면 (None, [])."""
    text = text.strip()
    if text.startswith(NO_ANSWER_MARK):
        return None, []
    match = SOURCE_LINE.search(text)
    body = SOURCE_LINE.sub("", text).strip()
    named = [s.strip() for s in match.group(1).split(",")] if match else []
    # 검색된 문서명에 있는 것만 인정하고, 중복은 처음 나온 순서로 하나만 남긴다.
    sources = list(dict.fromkeys(s for s in named if s in allowed_sources))
    return body, sources


def answer_question(question, llm=None, db=None):
    """질문에 답한다. {"answer": str, "status": "ok", "sources": [문서명]}을 돌려준다."""
    has_evidence, usable = assess_retrieval(retrieve(question, db=db))
    if not has_evidence:
        return {"answer": NO_ANSWER_REPLY, "status": "ok", "sources": []}

    llm = llm or build_llm()
    reply = llm.invoke(
        [
            ("system", SYSTEM_PROMPT),
            ("human", f"[근거]\n{format_context(usable)}\n\n[질문]\n{question}"),
        ]
    )
    allowed = {doc.metadata["source"] for doc, _ in usable}
    body, sources = parse_reply(get_text(reply), allowed)
    if body is None or not body:
        return {"answer": NO_ANSWER_REPLY, "status": "ok", "sources": []}
    if not sources:
        # 모델이 출처를 빠뜨렸거나 엉뚱한 이름을 쓴 경우: 근거로 준 문서 중 가장 가까운 것으로 보충한다.
        sources = [usable[0][0].metadata["source"]]
    return {
        "answer": f"{body}\n(출처: {', '.join(sources)})",
        "status": "ok",
        "sources": sources,
    }
