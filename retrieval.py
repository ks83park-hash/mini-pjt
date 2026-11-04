"""검색 함수와 "근거 없음" 판정.

- retrieve(): 질문과 가까운 청크 상위 k개를 (청크, 거리)로 가져온다.
- assess_retrieval(): 거리 기준(Python 규칙)으로 쓸 만한 결과만 남기고, 하나도 없으면 "근거 없음"으로 판정한다.
  LLM은 이 판정에 쓰지 않는다.
- 청크가 문서에 근접해 보여도 질문에 답이 없을 수 있다(예: "해외 배송도 되나요?").
  그런 경우는 답변을 만드는 단계(1-6)의 프롬프트가 "근거에 없으면 찾을 수 없음"으로 처리한다.
"""
from index import load_index

# 청크가 9개뿐이라 5개를 가져온다. 3개로는 "돌려보낼 수 있나요?" 같은 바꿔 말한 질문에서
# 환불 정책/신청 기간이 5위로 밀려 빠졌다(측정: 거리 1.523).
TOP_K = 5

# Chroma 거리(L2)가 이 값 이하인 청크만 쓸 만하다고 본다. (작을수록 가깝다)
# 2026-11 측정(청크 9개): 정책 관련 질문 최대 약 1.38, 정책과 무관한 질문 최소 약 1.74.
# 두 구간 사이인 1.6으로 정했다. 문서나 임베딩 모델이 바뀌면 다시 측정해야 한다.
MAX_DISTANCE = 1.6


def retrieve(question, k=TOP_K, db=None):
    """질문과 가까운 순서로 [(Document, 거리)] k개를 돌려준다."""
    db = db or load_index()
    return db.similarity_search_with_score(question, k=k)


def assess_retrieval(results, max_distance=MAX_DISTANCE):
    """쓸 만한 검색 결과만 걸러 (근거 있음 여부, 쓸 만한 결과 목록)을 돌려준다.

    규칙: 거리가 max_distance 이하인 결과만 남긴다. 하나도 없으면 근거 없음이다.
    """
    usable = [(doc, dist) for doc, dist in results if dist <= max_distance]
    return bool(usable), usable
