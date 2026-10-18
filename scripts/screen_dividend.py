"""시가배당률 스크리닝: 네이버 배당수익률이 기준(기본 7%) 이상인 종목 + 배당 지속성 지표.

Usage:
    python scripts/screen_dividend.py [--min 7]
"""
import argparse
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leader.naver import Naver, num  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def annual(nv, code):
    d = nv.finance_annual(code)
    if not d or not d.get("financeInfo"):
        return {}
    fi = d["financeInfo"]
    keys = [(c["key"], c.get("isConsensus") == "Y") for c in fi["trTitleList"]]
    rows = {r["title"]: {k: num(v.get("value")) for k, v in r["columns"].items()} for r in fi["rowList"]}
    out = {}
    actual = [k for k, e in keys if not e]
    cons = [k for k, e in keys if e]
    dps, eps = rows.get("주당배당금", {}), rows.get("EPS", {})
    for i, k in enumerate(reversed(actual[-3:])):
        out[f"dps_{k[:4]}"] = dps.get(k)
    if actual:
        out["eps_last"] = eps.get(actual[-1])
        out["dps_last"] = dps.get(actual[-1])
    if cons:
        out["dps_e"] = dps.get(cons[0])
        out["eps_e"] = eps.get(cons[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=float, default=7.0, help="시가배당률 하한(%)")
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "cache", date.today().isoformat()))
    args = ap.parse_args()
    nv = Naver(args.cache)

    groups = nv.industries()
    names = {g["no"]: g["name"] for g in groups}
    stocks = {}
    for no, lst in nv.pmap(lambda no: (no, nv.industry_stocks(no)), list(names)):
        for s in lst:
            if s.get("stockEndType") == "stock" and "스팩" not in s["stockName"]:
                stocks[s["itemCode"]] = {"code": s["itemCode"], "name": s["stockName"], "industry": names[no],
                                         "market": "KOSPI" if s.get("sosok") == "0" else "KOSDAQ",
                                         "mcap_eok": num(s.get("marketValue")),
                                         "value_eok": (num(s.get("accumulatedTradingValue")) or 0) / 100}
    print(f"상장 주식 {len(stocks):,}개 배당수익률 조회 중...", flush=True)

    def info(code):
        d = nv.integration(code) or {}
        t = {x["code"]: x.get("value") for x in d.get("totalInfos", [])}
        return {"yield": num(t.get("dividendYieldRatio")), "dps": num(t.get("dividend")),
                "price": num(t.get("lastClosePrice")), "high52": num(t.get("highPriceOf52Weeks")),
                "per": num(t.get("per")), "pbr": num(t.get("pbr"))}

    codes = list(stocks)
    for code, x in zip(codes, nv.pmap(info, codes)):
        stocks[code].update(x)
    hits = [s for s in stocks.values() if (s["yield"] or 0) >= args.min]
    print(f"시가배당률 {args.min}% 이상: {len(hits)}종목", flush=True)

    for s, a in zip(hits, nv.pmap(lambda s: annual(nv, s["code"]), hits)):
        s.update(a)
        s["preferred"] = not s["code"].endswith("0")
        s["payout"] = s["dps_last"] / s["eps_last"] if s.get("dps_last") and s.get("eps_last") and s["eps_last"] > 0 else None
        s["from_high"] = s["price"] / s["high52"] - 1 if s.get("price") and s.get("high52") else None
        s["yield_e"] = s["dps_e"] / s["price"] * 100 if s.get("dps_e") and s.get("price") else None

    df = pd.DataFrame(hits).set_index("code").sort_values("yield", ascending=False)
    out_dir = os.path.join(ROOT, "data", "dividend")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"high_yield_{date.today().isoformat()}.csv")
    df.to_csv(path, encoding="utf-8-sig")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
