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

## KOSPI COMP → 4팩터 F 스코어

```bash
python scripts/run_kospi_comp.py
```

KOSPI 유니버스 구축 → 모듈 1 COMP 채점 → 중간 결과(COMP 70점 이상) → COMP 80점 이상만 모듈 2 F 스코어 →
최종 보고 순서로 실행합니다. 시세·수급·컨센서스는 네이버 증권, F 스코어 재무제표는 DART(`DART_API_KEY` 필요)를 씁니다.

1. **유니버스**: KOSPI 보통주, 시가총액 300억 이상, 20일 평균 거래대금 10억 이상(우선주·스팩 제외)
2. **모듈 1 COMP** = 순위 모멘텀 40% + 스마트머니 30% + 가격 모멘텀 20% + 밸류에이션 10%
   - 순위 모멘텀: 1/3/6/12개월 코스피 대비 상대강도 순위 R을 ➊ Π R^w(w 0.4/0.3/0.2/0.1)와
     ➋ Σ w·R + 0.5·σ(R) 두 기준으로 종합
   - 스마트머니: 20일 기관·외국인 순매수 금액, 20일 외국인 보유율 증가폭
   - 가격 모멘텀: 1주·1개월·3개월 수익률, 52주 신고가 괴리율
   - 밸류에이션: ROE, 12개월 선행 PER, 영업이익 성장률
3. **모듈 2 섹터별 4·5팩터 F 스코어**(COMP 80점 이상, 아래 `/fscore`와 같은 계산)
4. **최종 보고**: COMP 70점 이상 전 종목을 COMP 오름차순으로, 80점 이상은 F 스코어 값을 함께 표시.
   COMP 80점 이상이면서 F 스코어 **완결·통과**면 최종 통과. **제한적 참고 통과**는 따로 표시

결과는 `data/kospi_comp/<기준일>/`(`comp_all.csv`, `comp70.csv`, `fscore.csv`, `final.csv`)와
`vault/리포트/KOSPI COMP F스코어 <기준일>.md`에 저장됩니다. 컷 점수·가중치·λ·정렬 방향은
`kospi_comp/config.py`에서 바꿀 수 있습니다. `DART_API_KEY`가 없으면 COMP까지만 계산하고 F 스코어는 '미산출'로 남깁니다.

## `/fscore` — 한국시장용 섹터별 4·5팩터 F 스코어

Piotroski F 스코어와 별개 체계입니다. Claude Code에서 `/fscore 005930 SK하이닉스`처럼 입력하면
`.claude/skills/fscore/SKILL.md`의 정의대로 아래 스크립트를 실행해 결과를 보여줍니다. 직접 실행해도 됩니다.

```bash
python scripts/fscore.py 005930 "SK하이닉스" "POSCO홀딩스(005490)"
python scripts/fscore.py 005490 --wics 005490=소재   # WICS 대분류를 직접 지정
python scripts/fscore.py 005930 --refresh            # 오늘 받은 DART 캐시를 무시하고 다시 조회
python -m unittest discover -s tests                  # 테스트(네트워크 불필요)
```

- **데이터**: DART 단일회사 전체 재무제표(`fnlttSinglAcntAll`)만 사용. 연결(CFS) 고정, 연결재무제표가 없는 회사만
  별도(OFS) — 한 종목 안에서 섞지 않음. 계정은 표준 `account_id` 우선, 회사 고유 계정은 계정명·위치로 의미가
  확정될 때만 쓰고 표 아래에 적음. 매출총이익·판관비를 다른 항목으로 재구성하지 않음.
- **TTM**: 최근 4개 분기 합 vs 1년 앞선 4개 분기 합. 손익은 분기 3개월 값, 4분기 = 연간 − 3분기 누적,
  현금흐름은 누적 차감. 만들 수 없는 분기가 하나라도 있으면 그 항목은 결측.
- **팩터**: 매출성장 · GPM 개선 · 판관비율 하락 · 총자산회전율(기간 말 총자산 세 시점) 개선, WICS 대분류
  **소재**만 발생액(TTM 연결 당기순이익 − TTM 영업활동현금흐름 < 0)을 더해 5개.
- **판정**: 결측은 0점이 아니라 제외. 정규화 = 원점수 ÷ 유효지표 수 × 4(소재 5). 모든 팩터가 유효하면
  완결(원점수 3.0 이상 **완결·통과**), 일부 결측이면 제한적(정규화 3.0 이상 **제한적 참고 통과**), 0개면 산정 불가.
- **섹터**: WISEindex의 WICS 대분류 구성종목으로 확인. 확인되지 않으면 "검증 필요"로 두고 완결로 단정하지 않음.
- **출력**: [1] 대화창용 Markdown 표(앞에 비교 기준 한 줄, 아래에 결측·고유 계정 설명) → [2] 같은 값의 탭 구분 텍스트.
- `DART_API_KEY`가 없거나 DART에 접속할 수 없으면 수치를 추정하지 않고 필요한 보고서·계정·기간 목록만 출력합니다
  (종료 코드 4). 종목명이 모호하면 고르지 않고 후보를 보여줍니다(3). API 키는 출력·오류 메시지에서 가립니다.
- 결산월이 12월이 아닌 회사는 회계분기 기준으로 계산하고, 보고서의 기수(제 N 기)로 같은 회계연도인지와
  회계연도가 끊김 없이 이어지는지 확인합니다. 결산기 변경 등으로 이어지지 않으면 산정하지 않습니다.
- `--as-of`를 과거 날짜로 주면 그 뒤에 접수된 보고서는 쓰지 않습니다. 통화가 창 사이에 바뀌면 금액 비교 팩터는 결측.
