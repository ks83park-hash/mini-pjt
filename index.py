"""정책 문서 청킹과 벡터 인덱스 만들기.

- 문서를 `##` 섹션 단위로 자른다. 청크마다 문서명·섹션명 메타데이터를 붙인다.
- 임베딩 모델과 리전은 .env(config.py)에서 읽는다. 모델은 함수 안에서 만든다.

실행: python index.py   (docs/ 를 읽어 ./chroma_db 를 새로 만든다)
"""
import shutil
import sys
from pathlib import Path

from config import load_settings

ROOT = Path(__file__).parent
DOCS_DIR = ROOT / "docs"
PERSIST_DIR = ROOT / "chroma_db"
COLLECTION_NAME = "cs_policies"

# 파일 이름 → 분류 (메타데이터 category). 문서명(source)은 각 문서의 `# 제목`을 쓴다.
CATEGORY = {
    "refund_policy.md": "환불",
    "exchange_policy.md": "교환",
    "shipping_policy.md": "배송",
}


def build_chunks(docs_dir=DOCS_DIR):
    """docs_dir의 정책 문서를 `##` 섹션 단위 청크(Document)로 나눈다.

    청크 본문 첫 줄에 `문서명 > 섹션명`을 넣어 검색에서 문서·섹션 이름도 단서가 되게 한다.
    메타데이터: source(문서명), section(섹션명), category(분류), file(파일명).
    """
    from langchain_core.documents import Document
    from langchain_text_splitters import MarkdownHeaderTextSplitter

    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "title"), ("##", "section")]
    )
    chunks = []
    for path in sorted(Path(docs_dir).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for part in splitter.split_text(text):
            # `##` 섹션이 없는 조각(제목 아래 안내 문구)은 인덱스에 넣지 않는다.
            if "section" not in part.metadata:
                continue
            title = part.metadata["title"]
            section = part.metadata["section"]
            chunks.append(
                Document(
                    page_content=f"{title} > {section}\n{part.page_content}",
                    metadata={
                        "source": title,
                        "section": section,
                        "category": CATEGORY.get(path.name, ""),
                        "file": path.name,
                    },
                )
            )
    return chunks


def build_embeddings(settings=None):
    """Bedrock 임베딩 모델. 모델 ID와 리전은 .env에서 읽는다."""
    from langchain_aws import BedrockEmbeddings

    settings = settings or load_settings()
    return BedrockEmbeddings(
        model_id=settings["EMBEDDING_MODEL_ID"],
        region_name=settings["AWS_REGION"],
    )


def build_index(embeddings=None, chunks=None, persist_dir=PERSIST_DIR):
    """청크를 임베딩해 Chroma에 저장한다. 기존 인덱스는 지우고 새로 만든다."""
    from langchain_chroma import Chroma

    chunks = chunks if chunks is not None else build_chunks()
    embeddings = embeddings or build_embeddings()
    if Path(persist_dir).exists():
        shutil.rmtree(persist_dir)
    return Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(persist_dir),
    )


def load_index(embeddings=None, persist_dir=PERSIST_DIR):
    """이미 만들어진 Chroma 인덱스를 연다."""
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings or build_embeddings(),
        persist_directory=str(persist_dir),
    )


def main():
    chunks = build_chunks()
    print(f"청크 {len(chunks)}개를 만들었습니다. 임베딩해서 저장합니다...")
    try:
        db = build_index(chunks=chunks)
    except Exception as e:
        print(f"인덱스 생성 실패: {type(e).__name__}: {e}")
        print("Bedrock 임베딩 모델 접근 권한(EMBEDDING_MODEL_ID, 리전)을 확인하세요.")
        return 1
    print(f"저장 완료: {db._collection.count()}개 청크 -> {PERSIST_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
