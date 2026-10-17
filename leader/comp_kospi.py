"""COMP v2 (KOSPI): 순위 모멘텀 40 · 스마트머니 30 · 가격 모멘텀 20 · 밸류에이션 10."""
import math

import pandas as pd

from .comp import grade, percentrank

RS_PERIODS = [("rs_1m", "ret_4w", 20, 0.40), ("rs_3m", "ret_12w", 60, 0.30),
              ("rs_6m", "ret_25w", 125, 0.20), ("rs_12m", "ret_52w", 250, 0.10)]
LAMBDA = 0.5  # 순위 기복(표준편차) 벌점 계수

PILLARS = {
    "smart_money": [("inst_net_20d", True), ("frgn_net_20d", True), ("frgn_ratio_chg", True)],
    "price_mom": [("ret_1w", True), ("ret_4w", True), ("ret_12w", True), ("high52_gap", True)],
    "valuation": [("roe", True), ("per_12m", False), ("op_yoy", True)],
}
WEIGHTS = {"rank_mom": 0.40, "smart_money": 0.30, "price_mom": 0.20, "valuation": 0.10}


def score(universe, kospi_ret):
    """kospi_ret: {20: r, 60: r, 125: r, 250: r} 코스피 수익률."""
    df = pd.DataFrame(universe).set_index("code")
    df["per_12m"] = df["per_12m"].replace(math.inf, 1e9)  # 적자 → 가장 비쌈

    # 기둥 1: 상대강도 순위(1 = 최강) → Σ wᵢRᵢ + λ·σ(R), 낮을수록 좋음
    rank_cols = []
    for col, ret_col, days, _ in RS_PERIODS:
        df[col] = df[ret_col] - kospi_ret[days] if days in kospi_ret else float("nan")
        df[f"{col}_rank"] = df[col].rank(ascending=False, method="average")
        rank_cols.append(f"{col}_rank")
    ranks = df[rank_cols]
    # 결측 기간(상장 1년 미만 등)은 빼고 남은 기간의 가중치를 합 1로 다시 맞춤
    w = pd.DataFrame([[wt for *_, wt in RS_PERIODS]] * len(df), index=df.index, columns=rank_cols)
    w = w.where(ranks.notna())
    df["rank_weighted"] = (ranks * w).sum(axis=1) / w.sum(axis=1)
    df["rank_std"] = ranks.std(axis=1, ddof=0)
    df["rs_periods"] = ranks.notna().sum(axis=1)
    df["rank_mom_raw"] = df["rank_weighted"] + LAMBDA * df["rank_std"]
    df["rank_mom"] = percentrank(df["rank_mom_raw"], higher_is_better=False) * 100

    for pillar, items in PILLARS.items():
        subs = pd.concat([percentrank(df[c].astype(float), hib) for c, hib in items], axis=1)
        df[f"{pillar}_raw"] = subs.mean(axis=1)
        df[pillar] = percentrank(df[f"{pillar}_raw"]) * 100

    df["comp"] = sum(df[p] * w for p, w in WEIGHTS.items())
    df["grade"] = df["comp"].map(grade)
    df["comp_rank"] = df["comp"].rank(ascending=False, method="min").astype(int)
    return df.sort_values("comp", ascending=False)
