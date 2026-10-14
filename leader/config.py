"""Sector definitions, thresholds and weights for the leader-sector / COMP workflow."""

# Each sector: one representative ETF (for the three eyes) and the Naver industry
# numbers whose stocks belong to it (for sector fundamentals and stock selection).
SECTORS = [
    {"name": "반도체", "etf": "091160", "industries": [278]},
    {"name": "IT하드웨어", "etf": "266370", "industries": [282, 269, 327, 292, 293, 294, 307, 338]},
    {"name": "소프트웨어·인터넷", "etf": "157490", "industries": [287, 267, 300]},
    {"name": "2차전지", "etf": "305720", "industries": [283]},
    {"name": "전력설비", "etf": "487240", "industries": [306]},
    {"name": "자동차", "etf": "091180", "industries": [273, 270]},
    {"name": "조선", "etf": "466920", "industries": [291]},
    {"name": "방산·우주", "etf": "449450", "industries": [284]},
    {"name": "기계장비", "etf": "102960", "industries": [299]},
    {"name": "건설", "etf": "117700", "industries": [279, 289, 320]},
    {"name": "철강·비철", "etf": "117680", "industries": [304, 322]},
    {"name": "에너지화학", "etf": "117460", "industries": [272, 313, 295, 312, 325, 331]},
    {"name": "운송", "etf": "140710", "industries": [305, 323, 326, 329, 296]},
    {"name": "은행", "etf": "091170", "industries": [301, 337, 319]},
    {"name": "증권", "etf": "102970", "industries": [321, 277]},
    {"name": "보험", "etf": "140700", "industries": [315, 330]},
    {"name": "헬스케어", "etf": "143860", "industries": [261, 262, 281, 286, 288, 316]},
    {"name": "미디어·엔터", "etf": "228810", "industries": [285, 310, 314]},
    {"name": "게임", "etf": "300950", "industries": [263]},
    {"name": "화장품", "etf": "228790", "industries": [266]},
    {"name": "필수소비재", "etf": "266410", "industries": [268, 309, 275, 302, 297]},
    {"name": "경기소비재", "etf": "266390", "industries": [264, 265, 274, 271, 308, 317, 328, 303, 298]},
]

# Universe filter (step 1)
MIN_MCAP_EOK = 300          # 시가총액 300억 이상
MIN_AVG_VALUE_WON = 1e9     # 20일 평균 거래대금 10억 이상
EXCLUDE_PREFERRED = True    # 우선주(종목코드 끝자리 ≠ 0) 제외

# Sector eyes
VOLUME_SURGE = 1.20         # 최근 5일 평균 거래대금 / 직전 10일 평균
MAX_DEVIATION_PCT = 1.0     # 괴리율 1% 이내가 정상
HISTORY_MIN_GAP_DAYS = 5    # 순자산·EPS 비교에 쓸 과거 스냅샷 최소 간격

# COMP
WEIGHTS = {"rank_mom": 0.40, "smart_money": 0.30, "price_mom": 0.20, "valuation": 0.10}
GRADES = [(90, "★★★★ 강력 매수"), (80, "★★★ 매수"), (65, "★★ 보유"), (0, "★ 매도 검토")]
SECTOR_CAP = 3

# KOSPI COMP → F 스코어 워크플로우
COMP_REPORT_MIN = 70     # 중간 결과 출력 기준
COMP_FSCORE_MIN = 80     # F 스코어 입력 기준
F_PASS_MIN = 3           # 최종 통과: F 스코어 4점 만점 중 3점 이상 (계산 가능한 팩터 3개 이상일 때)
TOP_N = 15
MIN_PICKS = 10
