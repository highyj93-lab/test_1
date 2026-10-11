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

## 주도 섹터 · COMP 파이프라인

```bash
python scripts/run_leader.py
```

네이버 증권 모바일 API(m.stock.naver.com) 데이터로 아래 과정을 한 번에 실행합니다.

1. **유니버스**: 시가총액 300억 이상, 20일 평균 거래대금 10억 이상(우선주·스팩 제외)
2. **세 가지 눈**: 섹터 ETF 22개를 모멘텀·펀더멘털·유동성으로 판정 → 주도 섹터 선정
3. **COMP**: 순위 모멘텀 40% · 스마트머니 30% · 가격 모멘텀 20% · 밸류에이션 10% (PERCENTRANK)
4. **선정**: 주도 섹터 안에서 COMP 상위, 섹터당 최대 3종목, TOP 10~15

결과는 `data/leader/<기준일>/`(CSV)와 `vault/리포트/주도섹터 COMP <기준일>.md`(옵시디언)에 저장됩니다.
`data/leader/history/`에 순자산총액과 EPS 추정치를 기록해, 다음 실행 때 '순자산 증가'와
'EPS 추정치 상향'을 판단합니다. 섹터 정의와 기준값은 `leader/config.py`에서 바꿀 수 있습니다.
