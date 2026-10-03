"""Connection smoke test using the OpenDartReader library.

Usage:
    cp .env.example .env   # fill in DART_API_KEY
    python examples/test_opendartreader.py
"""
import os

import OpenDartReader
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise SystemExit("DART_API_KEY가 설정되지 않았습니다 (.env 확인).")

    dart = OpenDartReader(api_key)
    df = dart.list(end_de="20250101")
    print(f"연결 성공. {len(df)}건 조회됨.")
    print(df.head())


if __name__ == "__main__":
    main()
