"""설정 읽기.

.env 값을 읽어 dict로 돌려준다. 모델 ID와 리전은 코드에 박지 않고 .env에서만 읽는다
(모델을 바꿔 쓸 수 있게 하기 위함). 모듈 최상단에서는 모델이나 외부 자원을 만들지 않는다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"

# 필수 설정 이름
REQUIRED_KEYS = [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "BEDROCK_MODEL_ID",
    "EMBEDDING_MODEL_ID",
]
# 값을 화면과 로그에 그대로 보여주면 안 되는 설정
SECRET_KEYS = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}


def load_settings():
    """.env를 읽어 {이름: 값} dict를 돌려준다. 없는 값은 빈 문자열이다."""
    load_dotenv(ENV_PATH)
    return {key: os.environ.get(key, "").strip() for key in REQUIRED_KEYS}


def missing_keys(settings):
    """값이 비어 있는 필수 설정 이름 목록."""
    return [key for key in REQUIRED_KEYS if not settings.get(key)]


def mask(key, value):
    """비밀값은 일부만(액세스 키 ID는 앞 4자) 보여주고, 시크릿 키는 아예 가린다."""
    if not value:
        return "(비어 있음)"
    if key == "AWS_SECRET_ACCESS_KEY":
        return "(설정됨, 값은 숨김)"
    if key in SECRET_KEYS:
        return value[:4] + "*" * 8
    return value
