"""Step 1: build the stock universe and collect per-stock raw metrics."""
from statistics import mean

from . import config as C
from .naver import num

SECTOR_OF_INDUSTRY = {no: s["name"] for s in C.SECTORS for no in s["industries"]}
HISTORY_PAGES = 5  # 300 trading days covers the 52-week window


def _ret(closes, n):
    if len(closes) <= n or not closes[-1 - n]:
        return None
    return closes[-1] / closes[-1 - n] - 1


def parse_finance(d):
    """-> dict with latest actual (A) and consensus (E) year values, or {}."""
    if not d or not d.get("financeInfo"):
        return {}
    fi = d["financeInfo"]
    cols = fi["trTitleList"]
    actual = [c["key"] for c in cols if c.get("isConsensus") == "N"]
    cons = [c["key"] for c in cols if c.get("isConsensus") == "Y"]
    rows = {r["title"]: {k: num(v.get("value")) for k, v in r["columns"].items()} for r in fi["rowList"]}

    def val(title, key):
        return rows.get(title, {}).get(key) if key else None

    a1 = actual[-1] if actual else None          # 최근 확정 연도
    a0 = actual[-2] if len(actual) > 1 else None  # 그 전 연도
    e1 = cons[0] if cons else None                # 컨센서스 연도
    e2 = cons[1] if len(cons) > 1 else None       # 그다음 컨센서스 연도(있을 때만)
    out = {"year_a": a1, "year_e": e1, "year_e2": e2}
    for t, k in (("영업이익", "op"), ("EPS", "eps"), ("ROE", "roe")):
        out[f"{k}_a0"], out[f"{k}_a1"], out[f"{k}_e"] = val(t, a0), val(t, a1), val(t, e1)
        out[f"{k}_e2"] = val(t, e2)
    return out


def _growth(new, old):
    if new is None or old is None:
        return None
    if old > 0:
        return new / old - 1
    return 1.0 if new > 0 else -1.0  # 흑자전환은 +100%, 적자 지속·전환은 -100%로 취급


def build(nv, log, markets=None):
    """markets: None = KOSPI+KOSDAQ, or e.g. {"KOSPI"} to keep only those markets."""
    groups = nv.industries()
    names = {g["no"]: g["name"] for g in groups}
    stocks = {}
    for no, lst in nv.pmap(lambda no: (no, nv.industry_stocks(no)), list(names)):
        for s in lst:
            if s.get("stockEndType") != "stock":
                continue
            stocks[s["itemCode"]] = {
                "code": s["itemCode"], "name": s["stockName"],
                "market": "KOSPI" if s.get("sosok") == "0" else "KOSDAQ",
                "industry_no": no, "industry": names[no],
                "sector": SECTOR_OF_INDUSTRY.get(no, "미분류"),
                "mcap_eok": num(s.get("marketValue")),
            }
    log(f"상장 주식 {len(stocks):,}개 (업종 {len(names)}개)")

    cands = [s for s in stocks.values()
             if (markets is None or s["market"] in markets)
             and (s["mcap_eok"] or 0) >= C.MIN_MCAP_EOK
             and "스팩" not in s["name"]
             and not (C.EXCLUDE_PREFERRED and not s["code"].endswith("0"))]
    scope = "·".join(sorted(markets)) + " " if markets else ""
    log(f"{scope}시가총액 {C.MIN_MCAP_EOK}억 이상(우선주·스팩 제외): {len(cands):,}개")

    first = nv.pmap(lambda s: nv.prices(s["code"], 1), cands)
    universe = []
    for s, px in zip(cands, first):
        last20 = px[-20:]
        if len(last20) < 20:
            continue
        s["avg_value_20d"] = mean(p["close"] * p["volume"] for p in last20)
        if s["avg_value_20d"] >= C.MIN_AVG_VALUE_WON:
            universe.append(s)
    log(f"20일 평균 거래대금 10억 이상: {len(universe):,}개 → 유니버스")

    hist = nv.pmap(lambda s: nv.prices(s["code"], HISTORY_PAGES), universe)
    trends = nv.pmap(lambda s: nv.trend(s["code"], 20), universe)
    fins = nv.pmap(lambda s: parse_finance(nv.finance_annual(s["code"])), universe)

    for s, px, tr, fin in zip(universe, hist, trends, fins):
        closes = [p["close"] for p in px]
        price = closes[-1]
        win = px[-250:]
        high52 = max((p["high"] or p["close"]) for p in win)
        s.update({
            "price": price,
            "days": len(px),
            "ret_1w": _ret(closes, 5), "ret_4w": _ret(closes, 20), "ret_12w": _ret(closes, 60),
            "ret_25w": _ret(closes, 125), "ret_52w": _ret(closes, 250),
            "high52_gap": price / high52 - 1 if high52 else None,  # 0 이면 신고가
        })
        inst = frgn = 0.0
        for row in tr:
            c = num(row.get("closePrice")) or price
            inst += (num(row.get("organPureBuyQuant")) or 0) * c
            frgn += (num(row.get("foreignerPureBuyQuant")) or 0) * c
        s["inst_net_20d"] = inst if tr else None
        s["frgn_net_20d"] = frgn if tr else None
        s["frgn_ratio"] = num(tr[0].get("foreignerHoldRatio")) if tr else None
        old_ratio = num(tr[-1].get("foreignerHoldRatio")) if tr else None
        s["frgn_ratio_chg"] = (s["frgn_ratio"] - old_ratio  # 20일간 보유율 변화(%p)
                               if s["frgn_ratio"] is not None and old_ratio is not None else None)

        eps_fwd = fin.get("eps_e") if fin.get("eps_e") is not None else fin.get("eps_a1")
        s["fwd_per"] = (price / eps_fwd if eps_fwd and eps_fwd > 0 else float("inf")) if eps_fwd is not None else None
        s["fwd_per_basis"] = "컨센서스" if fin.get("eps_e") is not None else ("직전 실적" if eps_fwd is not None else "-")
        s["roe"] = fin.get("roe_e") if fin.get("roe_e") is not None else fin.get("roe_a1")
        if fin.get("op_e") is not None:
            s["op_growth"] = _growth(fin["op_e"], fin.get("op_a1"))
        else:
            s["op_growth"] = _growth(fin.get("op_a1"), fin.get("op_a0"))
        s["eps_a1"], s["eps_e"], s["eps_e2"] = fin.get("eps_a1"), fin.get("eps_e"), fin.get("eps_e2")
        s["op_a1"], s["op_e"] = fin.get("op_a1"), fin.get("op_e")
    return universe
