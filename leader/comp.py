"""Step 3: COMP score = 순위 모멘텀 40% + 스마트머니 30% + 가격 모멘텀 20% + 밸류에이션 10%."""
import math

import pandas as pd

from . import config as C

# (column, higher_is_better)
PILLARS = {
    "rank_mom": [("ret_4w", True), ("ret_12w", True), ("ret_25w", True), ("ret_52w", True)],
    "smart_money": [("inst_net_20d", True), ("frgn_net_20d", True), ("frgn_ratio", True)],
    "price_mom": [("ret_1w", True), ("ret_4w", True), ("ret_12w", True), ("high52_gap", True)],
    "valuation": [("roe", True), ("fwd_per", False), ("op_growth", True)],
}


def percentrank(s, higher_is_better=True):
    """(N - rank) / N, rank 1 = best. Missing values get the neutral 0.5."""
    valid = s.dropna()
    n = len(valid)
    if n == 0:
        return pd.Series(0.5, index=s.index)
    rank = valid.rank(ascending=not higher_is_better, method="average")
    return ((n - rank) / n).reindex(s.index).fillna(0.5)


def grade(score):
    return next(label for cut, label in C.GRADES if score >= cut)


def score(universe):
    df = pd.DataFrame(universe).set_index("code")
    df["fwd_per"] = df["fwd_per"].replace(math.inf, 1e9)  # 적자 → 가장 비쌈
    for pillar, items in PILLARS.items():
        subs = pd.concat([percentrank(df[c].astype(float), hib) for c, hib in items], axis=1)
        df[f"{pillar}_raw"] = subs.mean(axis=1)
        df[pillar] = percentrank(df[f"{pillar}_raw"]) * 100
    df["comp"] = sum(df[p] * w for p, w in C.WEIGHTS.items())
    df["grade"] = df["comp"].map(grade)
    df["comp_rank"] = df["comp"].rank(ascending=False, method="min").astype(int)
    return df.sort_values("comp", ascending=False)


def pick(df, sectors):
    """주도 섹터 안에서 COMP 상위, 업종(섹터)당 최대 SECTOR_CAP 종목."""
    lead = [s["sector"] for s in sectors if s["verdict_order"] <= 1]
    watch = [s["sector"] for s in sectors if s["verdict_order"] == 2]

    def take(pool, picked, limit):
        counts = picked["sector"].value_counts().to_dict() if len(picked) else {}
        rows = []
        for code, r in pool.iterrows():
            if len(picked) + len(rows) >= limit:
                break
            if counts.get(r["sector"], 0) >= C.SECTOR_CAP or code in picked.index:
                continue
            counts[r["sector"]] = counts.get(r["sector"], 0) + 1
            rows.append(code)
        return pd.concat([picked, pool.loc[rows]])

    picks = take(df[df["sector"].isin(lead)].assign(pick_basis="주도 섹터"), df.iloc[0:0], C.TOP_N)
    if len(picks) < C.MIN_PICKS and watch:
        picks = take(df[df["sector"].isin(watch)].assign(pick_basis="관찰 섹터(보충)"), picks, C.MIN_PICKS)
    return picks, lead, watch
