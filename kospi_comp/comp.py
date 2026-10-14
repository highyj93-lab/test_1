"""모듈 1: COMP = 순위 모멘텀 40% + 스마트머니 30% + 가격 모멘텀 20% + 밸류에이션 10%."""
import math
from datetime import date

import numpy as np
import pandas as pd

from leader.comp import percentrank

from . import config as C

# (column, higher_is_better) — 순위 모멘텀은 rank_momentum()에서 따로 계산
PILLARS = {
    "smart_money": [("inst_net_20d", True), ("frgn_net_20d", True), ("frgn_ratio_chg", True)],
    "price_mom": [("ret_1w", True), ("ret_4w", True), ("ret_12w", True), ("high52_gap", True)],
    "valuation": [("roe", True), ("fwd_per_12m", False), ("op_growth", True)],
}


def forward_per(s, as_of):
    """12개월 선행 PER = 현재가 ÷ 12M 선행 EPS. 적자면 inf, 데이터 없으면 None.

    컨센서스가 두 해 있으면 올해·내년 EPS를 남은 기간 비율로 섞고,
    한 해만 있으면 그 추정치, 없으면 직전 연도 실적을 쓴다.
    """
    e1, e2, a1 = s.get("eps_e"), s.get("eps_e2"), s.get("eps_a1")
    if e1 is not None and e2 is not None:
        f = (as_of - date(as_of.year, 1, 1)).days / 365
        eps, basis = (1 - f) * e1 + f * e2, "컨센서스 12M"
    elif e1 is not None:
        eps, basis = e1, "컨센서스(당해)"
    elif a1 is not None:
        eps, basis = a1, "직전 실적"
    else:
        return None, "-"
    return (s["price"] / eps if eps > 0 else math.inf), basis


def rank_momentum(df, kospi_ret):
    """기둥 1. 기간별 코스피 대비 상대강도 순위(1=최강)를 두 기준으로 종합.

    ➊ 최근 가중 기하평균  Π R_i^w_i
    ➋ 변동성 벌점        Σ w_i·R_i + λ·σ(R)
    둘 다 낮을수록 좋으므로 각각 PERCENTRANK(낮을수록 높은 점수) 후 평균한다.
    """
    n = len(df)
    ranks = {}
    for p, col in C.RS_PERIODS.items():
        df[f"rs_{p}"] = (1 + df[col].astype(float)) / (1 + kospi_ret[p]) - 1
        # 상장 기간이 짧아 수익률이 없으면 중간 순위(중립)
        ranks[p] = df[f"rs_{p}"].rank(ascending=False, method="average").fillna((n + 1) / 2)
    R = pd.DataFrame(ranks)
    w = pd.Series(C.RANK_WEIGHTS)[R.columns]

    df[[f"R_{p}" for p in R.columns]] = R.to_numpy()
    df["rm_geo"] = np.exp((np.log(R) * w).sum(axis=1))
    df["rm_sigma"] = R.std(axis=1, ddof=0)
    df["rm_penalty"] = (R * w).sum(axis=1) + C.LAMBDA * df["rm_sigma"]
    return pd.concat([percentrank(df["rm_geo"], False), percentrank(df["rm_penalty"], False)], axis=1).mean(axis=1)


def score(universe, kospi_ret, as_of):
    df = pd.DataFrame(universe).set_index("code")
    per = [forward_per(s, as_of) for s in universe]
    df["fwd_per_12m"] = [p for p, _ in per]
    df["fwd_per_12m_basis"] = [b for _, b in per]

    raws = {"rank_mom": rank_momentum(df, kospi_ret)}
    vals = df["fwd_per_12m"].replace(math.inf, 1e9)  # 적자 → 가장 비쌈
    for pillar, items in PILLARS.items():
        cols = [(vals if c == "fwd_per_12m" else df[c]).astype(float) for c, _ in items]
        raws[pillar] = pd.concat([percentrank(s, hib) for s, (_, hib) in zip(cols, items)], axis=1).mean(axis=1)

    for pillar, raw in raws.items():
        df[f"{pillar}_raw"] = raw
        df[pillar] = percentrank(raw) * 100
    df["comp"] = sum(df[p] * w for p, w in C.WEIGHTS.items())
    df["comp_rank"] = df["comp"].rank(ascending=False, method="min").astype(int)
    return df.sort_values("comp", ascending=False)
