"""Weights and thresholds for the KOSPI COMP → F-score workflow.

Universe filters (시가총액·거래대금·우선주/스팩 제외) are shared with leader/config.py.
"""

MARKETS = {"KOSPI"}

# 모듈 1: COMP = 기둥별 점수(0~100)의 가중합
WEIGHTS = {"rank_mom": 0.40, "smart_money": 0.30, "price_mom": 0.20, "valuation": 0.10}

# 기둥 1 순위 모멘텀: 코스피 대비 상대강도 순위의 기간별 가중치(최근일수록 큼)
RS_PERIODS = {"1m": "ret_4w", "3m": "ret_12w", "6m": "ret_25w", "12m": "ret_52w"}
RS_DAYS = {"1m": 20, "3m": 60, "6m": 125, "12m": 250}  # leader/universe.py 수익률과 같은 거래일 수
RANK_WEIGHTS = {"1m": 0.40, "3m": 0.30, "6m": 0.20, "12m": 0.10}
LAMBDA = 0.5  # 순위 변동성(표준편차) 벌점 계수

# 단계별 컷
COMP_REPORT = 70   # 중간 결과 출력
COMP_FSCORE = 80   # F 스코어 입력 (통과 기준 3.0은 kospi_comp/fscore.py PASS)

# 최종 보고 정렬: COMP 오름차순
FINAL_ASCENDING = True
