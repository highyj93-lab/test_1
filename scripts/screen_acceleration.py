"""실적 가속 스크리닝: 분기 매출·영업이익의 증가폭(1차 미분)이 커지는(2차 미분 > 0) 종목.

판정 (확정 5개 분기):
  - 2차 곡선 y = a·t² + b·t + c 를 최소제곱으로 맞춰 a > 0(위로 휨)이고 최근 기울기 > 0
  - 최근 2개 분기 모두 증가(Δ₃, Δ₄ > 0)하고 전년 동기 대비(YoY) 증가 → 급락 후 반등(V자)은 제외
  - 곡률 = 2a ÷ 평균 수준(%). 클수록 가속이 강함
  - 참고: Δ₂ < Δ₃ < Δ₄ (증가폭 3분기 연속 확대), 다음 분기 컨센서스가 가속을 이어가는지

Usage:
    python scripts/screen_acceleration.py
"""
import argparse
import os
import sys
from datetime import date
from statistics import mean

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leader import config as C  # noqa: E402
from leader.naver import Naver, num  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def series(d, title):
    """-> (actual [(key, value)], consensus (key, value) or None)."""
    fi = d["financeInfo"]
    row = next((r for r in fi["rowList"] if r["title"] == title), None)
    if not row:
        return [], None
    vals = {k: num(v.get("value")) for k, v in row["columns"].items()}
    actual = [(c["key"], vals.get(c["key"])) for c in fi["trTitleList"] if c.get("isConsensus") == "N"]
    cons = [(c["key"], vals.get(c["key"])) for c in fi["trTitleList"] if c.get("isConsensus") == "Y"]
    return actual, (cons[0] if cons and cons[0][1] is not None else None)


def analyze(actual, cons):
    vals = [v for _, v in actual]
    if len(vals) < 5 or any(v is None for v in vals[-5:]):
        return None
    v = vals[-5:]
    d = [v[i + 1] - v[i] for i in range(4)]  # Δ₁..Δ₄
    a, b, _ = np.polyfit(range(5), v, 2)
    level = mean(abs(x) for x in v) or None
    yoy = v[-1] / v[0] - 1 if v[0] > 0 else (1.0 if v[-1] > 0 else None)  # 5개 분기 전 = 전년 동기
    out = {
        "q_keys": [k for k, _ in actual[-5:]],
        "values": v,
        "diffs": d,
        "curvature": 2 * a / level if level else None,
        "slope_now": (8 * a + b) / level if level else None,
        "latest": v[-1],
        "qoq": v[-1] / v[-2] - 1 if v[-2] > 0 else None,
        "yoy": yoy,
        "strict": d[1] > 0 and d[1] < d[2] < d[3],
    }
    out["accel"] = bool(a > 0 and 8 * a + b > 0 and d[2] > 0 and d[3] > 0 and (yoy or 0) > 0)
    if cons:
        out["cons_key"], out["cons"] = cons
        out["cons_accel"] = (cons[1] - v[-1]) > d[3]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "cache", date.today().isoformat()))
    ap.add_argument("--min-curvature", type=float, default=0.03, help="매출 곡률(2a/평균) 하한")
    ap.add_argument("--min-yoy", type=float, default=0.30, help="매출·영업이익 YoY 하한")
    args = ap.parse_args()
    nv = Naver(args.cache)

    names = {g["no"]: g["name"] for g in nv.industries()}
    stocks = {}
    for no, lst in nv.pmap(lambda no: (no, nv.industry_stocks(no)), list(names)):
        for s in lst:
            if (s.get("stockEndType") == "stock" and "스팩" not in s["stockName"] and s["itemCode"].endswith("0")
                    and (num(s.get("marketValue")) or 0) >= C.MIN_MCAP_EOK):
                stocks[s["itemCode"]] = {"code": s["itemCode"], "name": s["stockName"], "industry": names[no],
                                         "market": "KOSPI" if s.get("sosok") == "0" else "KOSDAQ",
                                         "mcap_eok": num(s.get("marketValue"))}
    cands = list(stocks.values())
    px = nv.pmap(lambda s: nv.prices(s["code"], 1), cands)
    uni = []
    for s, p in zip(cands, px):
        if len(p) >= 20 and mean(x["close"] * x["volume"] for x in p[-20:]) >= C.MIN_AVG_VALUE_WON:
            s["ret_3m"] = p[-1]["close"] / p[0]["close"] - 1 if p[0]["close"] else None
            uni.append(s)
    print(f"유니버스 {len(uni)}종목 (시총 300억↑, 20일 평균 거래대금 10억↑) · 분기 실적 조회 중...", flush=True)

    rows = []
    for s, d in zip(uni, nv.pmap(lambda s: nv.finance_quarter(s["code"]), uni)):
        if not d or not d.get("financeInfo"):
            continue
        r = dict(s)
        for title, p in (("매출액", "rev"), ("영업이익", "op")):
            a = analyze(*series(d, title))
            if a:
                r.update({f"{p}_{k}": v for k, v in a.items()})
        rows.append(r)
    df = pd.DataFrame(rows).set_index("code")
    for p in ("rev", "op"):
        if f"{p}_accel" not in df:
            df[f"{p}_accel"] = False
        df[f"{p}_accel"] = df[f"{p}_accel"].map(lambda x: x is True)
    print(f"분기 실적 확보 {len(df)}종목 · 매출 가속 {df.rev_accel.sum()} · 영업이익 가속 {df.op_accel.sum()} · "
          f"둘 다 {(df.rev_accel & df.op_accel).sum()}")

    # 의미 있는 가속만: 매출 곡률 ≥ 3%, 매출·영업이익 YoY ≥ 30%, 다음 분기 매출 컨센서스도 증가(있을 때)
    m = (df.rev_accel & df.op_accel & (df.rev_curvature >= args.min_curvature)
         & (df.rev_yoy >= args.min_yoy) & (df.op_yoy >= args.min_yoy))
    if "rev_cons" in df:
        m &= df.rev_cons.isna() | (df.rev_cons > df.rev_latest)
    picks = df[m].copy()
    picks["financial"] = picks.industry.isin(FINANCIAL) | picks.name.isin(HOLDING_LIKE)
    picks["score"] = (picks.rev_curvature.rank(pct=True) + picks.op_curvature.rank(pct=True)
                      + picks.rev_yoy.rank(pct=True))
    picks = picks.sort_values(["financial", "score"], ascending=[True, False])

    out_dir = os.path.join(ROOT, "data", "acceleration")
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(os.path.join(out_dir, f"all_{date.today().isoformat()}.csv"), encoding="utf-8-sig")
    path = os.path.join(out_dir, f"picks_{date.today().isoformat()}.csv")
    picks.to_csv(path, encoding="utf-8-sig")
    print(f"가속 기준 통과 {len(picks)}종목 (금융·지주 {picks.financial.sum()}) → {path}")


FINANCIAL = {"증권", "창업투자", "생명보험", "손해보험", "은행", "기타금융", "카드"}
HOLDING_LIKE = {"SK스퀘어", "다우기술"}  # 지분법 이익·금융 자회사 실적이 매출에 섞이는 지주형


if __name__ == "__main__":
    main()
