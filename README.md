# DART API Connector

OpenDART(금융감독원 전자공시시스템) Open API를 호출하는 파이썬 클라이언트입니다.

## 설정

```bash
pip install -r requirements.txt
cp .env.example .env   # DART_API_KEY 값을 본인 발급 키로 채워 넣기
```

API 키는 코드에 하드코딩하지 않고 `.env`(gitignore 처리됨) 또는 환경변수 `DART_API_KEY`로만 전달합니다.

## 사용법

```python
from dart_api import DartApiClient

client = DartApiClient()  # DART_API_KEY 환경변수 사용
result = client.search_disclosures(page_count=10)       # 공시검색
company = client.get_company("00126380")                 # 기업개황
xml_bytes = client.download_corp_codes()                  # 고유번호 전체 목록
```

## 연결 테스트

```bash
python examples/test_connection.py        # 직접 작성한 dart_api 클라이언트
python examples/test_opendartreader.py    # OpenDartReader 라이브러리
```

`OpenDartReader`는 DART Open API의 거의 모든 엔드포인트(재무제표, 지분공시, 사업보고서 등)를
감싸는 서드파티 라이브러리로, `requirements.txt`에 포함되어 있습니다.
