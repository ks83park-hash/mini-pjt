"""설정 확인: .env 값을 읽어 출력한다 (비밀키는 마스킹)."""
import sys

from config import ENV_PATH, load_settings, mask, missing_keys


def main():
    if not ENV_PATH.exists():
        print(f".env 파일이 없습니다: {ENV_PATH}")
        print(".env.example을 복사해 .env를 만든 뒤 값을 채우세요.")
        return 1

    settings = load_settings()
    for key, value in settings.items():
        print(f"{key} = {mask(key, value)}")

    missing = missing_keys(settings)
    if missing:
        print("\n비어 있는 항목: " + ", ".join(missing))
        return 1
    print("\n필수 설정이 모두 채워져 있습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
