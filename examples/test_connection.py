"""Quick smoke test: verifies the DART API key works.

Usage:
    cp .env.example .env   # fill in DART_API_KEY
    python examples/test_connection.py
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dart_api import DartApiClient, DartApiError  # noqa: E402

load_dotenv()


def main() -> None:
    client = DartApiClient()
    try:
        result = client.search_disclosures(page_count=5)
    except DartApiError as e:
        print(f"DART API 연결 실패: {e}")
        raise

    print(f"연결 성공. status={result['status']}, message={result['message']}")
    for item in result.get("list", []):
        print(f"- [{item['rcept_dt']}] {item['corp_name']}: {item['report_nm']}")


if __name__ == "__main__":
    main()
