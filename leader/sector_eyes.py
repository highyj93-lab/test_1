"""Step 2: read leading sectors with three eyes (momentum, fundamentals, liquidity)."""
from statistics import mean

from . import config as C
from .naver import hangeul_eok, num

POS, NEU, NEG = "긍정", "중립", "부정"


def _ret(closes, n, end=0):
    i = len(closes) - 1 - end
    if i - n < 0:
        return None
    return closes[i] / closes[i - n] - 1


def _eye(passed, available):
    if available == 0:
        return NEU
    r = passed / available
    return POS if r >= 0.66 else NEU if r >= 0.33 else NEG


def _ranks(values):
    """1 = best. values: {key: score}."""
    order = sorted(values, key=lambda k: values[k], reverse=True)
    return {k: i + 1 for i, k in enumerate(order)}


def analyze(nv, universe, prev_snapshot, log):
    kospi = [p["close"] for p in nv.prices("KOSPI", 3, index=True)]
    k = {n: _ret(kospi, n) for n in (20, 60, 125)}

    rows = []
    for sec in C.SECTORS:
        px = nv.prices(sec["etf"], 3)
        closes = [p["close"] for p in px]
        info = nv.integration(sec["etf"]) or {}
        key = info.get("etfKeyIndicator") or {}
        tr = nv.trend(sec["etf"], 20)
        r = {"sector": sec["name"], "etf": sec["etf"], "etf_name": info.get("stockName", sec["etf"])}
        r.update({f"ret_{n}": _ret(closes, n) for n in (20, 60, 125)})
        r["mom_now"] = mean(x for x in (r["ret_20"], r["ret_60"], r["ret_125"]) if x is not None)
        prev = [_ret(closes, n, end=20) for n in (20, 60, 125)]
        r["mom_prev"] = mean(x for x in prev if x is not None)
        r["excess_1m"] = r["ret_20"] - k[20]
        r["excess_3m"] = r["ret_60"] - k[60]

        values = [p["close"] * p["volume"] for p in px]
        r["value_ratio"] = mean(values[-5:]) / mean(values[-15:-5]) if mean(values[-15:-5]) else None
        r["aum_eok"] = hangeul_eok(key.get("totalNav"))
        r["deviation"] = key.get("deviationRate")
        if r["deviation"] is not None and key.get("deviationSign") == "-":
            r["deviation"] = -r["deviation"]
        inst = sum((num(x.get("organPureBuyQuant")) or 0) * (num(x.get("closePrice")) or 0) for x in tr)
        frgn = sum((num(x.get("foreignerPureBuyQuant")) or 0) * (num(x.get("closePrice")) or 0) for x in tr)
        r["inst_net_20d"], r["frgn_net_20d"] = (inst, frgn) if tr else (None, None)
        prev_aum = (prev_snapshot or {}).get("aum", {}).get(sec["etf"])
        r["aum_change"] = (r["aum_eok"] / prev_aum - 1) if (prev_aum and r["aum_eok"]) else None
        rows.append(r)

    now_rank = _ranks({r["sector"]: r["mom_now"] for r in rows})
    prev_rank = _ranks({r["sector"]: r["mom_prev"] for r in rows})
    n = len(rows)

    prev_eps = (prev_snapshot or {}).get("eps_e", {})
    for r in rows:
        members = [s for s in universe if s["sector"] == r["sector"]]
        op_pairs = [(s["op_e"], s["op_a1"]) for s in members if s["op_e"] is not None and s["op_a1"] is not None]
        base = sum(b for _, b in op_pairs)
        r["sector_op_growth"] = sum(a for a, _ in op_pairs) / base - 1 if len(op_pairs) >= 3 and base > 0 else None
    growths = sorted(r["sector_op_growth"] for r in rows if r["sector_op_growth"] is not None)
    median_growth = growths[len(growths) // 2] if growths else None

    for r in rows:
        r["rank_now"], r["rank_prev"] = now_rank[r["sector"]], prev_rank[r["sector"]]

        # 모멘텀 눈
        m = {
            "1개월 +": r["ret_20"] > 0,
            "3·6개월 +": r["ret_60"] > 0 and r["ret_125"] > 0,
            "코스피 초과(3개월)": r["excess_3m"] > 0,
            "순위 상승": r["rank_now"] < r["rank_prev"],
        }
        r["mom_checks"] = m
        r["eye_momentum"] = _eye(sum(m.values()), len(m))

        # 펀더멘털 눈: 섹터 소속 유니버스 종목의 이익 추정치
        members = [s for s in universe if s["sector"] == r["sector"]]
        f = {}
        if r["sector_op_growth"] is not None:
            f["영업이익 증가율 섹터 중앙값 이상"] = r["sector_op_growth"] > 0 and r["sector_op_growth"] >= median_growth
        eps_pairs = [(s["eps_e"], s["eps_a1"]) for s in members if s["eps_e"] is not None and s["eps_a1"] is not None]
        if len(eps_pairs) >= 3:
            r["eps_up_share"] = sum(a > b for a, b in eps_pairs) / len(eps_pairs)
            f["EPS 증가 종목 50%↑"] = r["eps_up_share"] >= 0.5
        else:
            r["eps_up_share"] = None
        revs = [(s["eps_e"], prev_eps[s["code"]]) for s in members
                if s["eps_e"] is not None and prev_eps.get(s["code"]) is not None]
        if len(revs) >= 3:
            up = sum(a > b * 1.001 for a, b in revs)
            down = sum(a < b * 0.999 for a, b in revs)
            r["eps_revision"] = (up, down)
            f["EPS 추정치 상향 우세"] = up > down
        else:
            r["eps_revision"] = None
        r["fund_checks"] = f
        r["fund_members"] = len(members)
        r["eye_fundamental"] = _eye(sum(f.values()), len(f))

        # 유동성 눈: 자금 유입 신호로 판정하고, 괴리율은 거품 필터로만 씀
        l = {}
        if r["value_ratio"] is not None:
            l["거래대금 +20%"] = r["value_ratio"] >= C.VOLUME_SURGE
        if r["aum_change"] is not None:
            l["순자산 증가"] = r["aum_change"] > 0
        if r["inst_net_20d"] is not None:
            l["외국인·기관 동시 순매수"] = r["inst_net_20d"] > 0 and r["frgn_net_20d"] > 0
        r["liq_checks"] = l
        r["eye_liquidity"] = _eye(sum(l.values()), len(l))
        r["bubble_warning"] = r["deviation"] is not None and abs(r["deviation"]) > C.MAX_DEVIATION_PCT
        if r["bubble_warning"] and r["eye_liquidity"] == POS:
            r["eye_liquidity"] = NEU

        eyes = [r["eye_momentum"], r["eye_fundamental"], r["eye_liquidity"]]
        npos, nneu = eyes.count(POS), eyes.count(NEU)
        if npos == 3:
            r["verdict"], r["verdict_order"] = "강력한 주도 섹터", 0
        elif npos == 2 and nneu == 1:
            r["verdict"], r["verdict_order"] = "유력한 주도 섹터 후보", 1
        elif npos == 2:
            r["verdict"], r["verdict_order"] = "관찰", 2
        else:
            r["verdict"], r["verdict_order"] = "비주도", 3
        r["positives"] = npos

        # 신호가 막 켜지는 섹터
        early = []
        if r["excess_1m"] > 0 and r["excess_3m"] <= 0:
            early.append("코스피 대비 초과상승 시작")
        if r["value_ratio"] and r["value_ratio"] >= C.VOLUME_SURGE:
            early.append(f"거래대금 급증(×{r['value_ratio']:.2f})")
        if r["eps_revision"] and r["eps_revision"][0] > r["eps_revision"][1]:
            early.append("EPS 추정치 상향")
        if r["rank_prev"] > n * 2 / 3 and r["rank_now"] <= n * 2 / 3:
            early.append(f"순위 반등({r['rank_prev']}→{r['rank_now']}위)")
        r["early_signals"] = early

    rows.sort(key=lambda r: (r["verdict_order"], -r["positives"], -r["mom_now"]))
    log(f"섹터 {n}개 분석 완료 · 코스피 1/3/6개월 {k[20]:+.1%} / {k[60]:+.1%} / {k[125]:+.1%}")
    return rows, k
