"""Markdown (Obsidian) and CSV outputs."""
import os

import pandas as pd

from . import config as C


def pct(v, signed=True):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def eok(v):
    if v is None or pd.isna(v):
        return "-"
    return f"{v / 1e8:+,.0f}억"


def checks(d):
    return " · ".join(("✅" if ok else "❌") + k for k, ok in d.items()) or "데이터 없음"


def write_csv(out_dir, sectors, df, picks):
    os.makedirs(out_dir, exist_ok=True)
    flat = []
    for s in sectors:
        x = {k: v for k, v in s.items() if not k.endswith("_checks")}
        for k in ("mom_checks", "fund_checks", "liq_checks"):
            x.update({f"{k[:-7]}:{name}": ok for name, ok in s[k].items()})
        x["early_signals"] = " | ".join(s["early_signals"])
        flat.append(x)
    pd.DataFrame(flat).to_csv(f"{out_dir}/sectors.csv", index=False, encoding="utf-8-sig")
    df.to_csv(f"{out_dir}/comp_all.csv", encoding="utf-8-sig")
    picks.to_csv(f"{out_dir}/picks.csv", encoding="utf-8-sig")


def markdown(as_of, kospi, universe_log, sectors, df, picks, lead, watch, has_history):
    L = ["---", f"date: {as_of}", "tags: [주도섹터, COMP, 리포트]", "---",
         f"# 주도 섹터 · COMP 리포트 ({as_of})", "",
         f"기준일 {as_of} 종가 · 코스피 1/3/6개월 {pct(kospi[20])} / {pct(kospi[60])} / {pct(kospi[125])} · 투자자문 아님", ""]
    L += ["## 요약"]
    L.append(f"- 주도 섹터: {', '.join(lead) if lead else '없음'}")
    L.append(f"- 관찰 섹터(두 눈 긍정·한 눈 부정): {', '.join(watch) if watch else '없음'}")
    if len(picks):
        L.append(f"- 포트폴리오 후보 {len(picks)}종목: " + ", ".join(picks["name"].tolist()))
    early = [s for s in sectors if s["early_signals"]]
    if early:
        L.append("- 신호가 막 켜지는 섹터: " + ", ".join(f"{s['sector']}({len(s['early_signals'])})" for s in early))
    if not has_history:
        L.append("- ⚠️ 첫 실행이라 '순자산 증가'와 'EPS 추정치 상향'은 판단하지 못함. 다음 실행부터 이번 기록과 비교함.")
    L.append("")

    L += ["## 1단계 · 세 가지 눈으로 본 섹터", "",
          "| 순위 | 섹터 | ETF | 모멘텀 | 펀더멘털 | 유동성 | 판정 | 1M | 3M | 6M | 3M 초과 | 모멘텀 순위 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(sectors, 1):
        L.append(f"| {i} | **{s['sector']}** | {s['etf_name']} | {s['eye_momentum']} | {s['eye_fundamental']} | "
                 f"{s['eye_liquidity']} | {s['verdict']} | {pct(s['ret_20'])} | {pct(s['ret_60'])} | "
                 f"{pct(s['ret_125'])} | {pct(s['excess_3m'])} | {s['rank_prev']}→{s['rank_now']} |")
    L += ["", "### 섹터별 체크 세부", ""]
    for s in sectors:
        L.append(f"**{s['sector']}** ({s['verdict']})")
        L.append(f"- 모멘텀: {checks(s['mom_checks'])}")
        fund_extra = []
        if s["sector_op_growth"] is not None:
            fund_extra.append(f"섹터 영업이익 증가율 {pct(s['sector_op_growth'])}")
        if s["eps_up_share"] is not None:
            fund_extra.append(f"EPS 증가 종목 비중 {pct(s['eps_up_share'], False)}")
        if s["eps_revision"]:
            fund_extra.append(f"추정치 상향 {s['eps_revision'][0]} / 하향 {s['eps_revision'][1]}")
        L.append(f"- 펀더멘털 (유니버스 {s['fund_members']}종목): {checks(s['fund_checks'])}"
                 + (f" — {', '.join(fund_extra)}" if fund_extra else ""))
        liq_extra = [f"거래대금 ×{s['value_ratio']:.2f}" if s["value_ratio"] else None,
                     f"괴리율 {s['deviation']:+.2f}%" if s["deviation"] is not None else None,
                     f"순자산 {s['aum_eok']:,.0f}억" + (f" ({pct(s['aum_change'])})" if s["aum_change"] is not None else ""),
                     f"20일 기관 {eok(s['inst_net_20d'])} · 외국인 {eok(s['frgn_net_20d'])}"]
        L.append(f"- 유동성: {checks(s['liq_checks'])} — {', '.join(x for x in liq_extra if x)}")
        if s["bubble_warning"]:
            L.append(f"- ⚠️ 괴리율 {s['deviation']:+.2f}%로 1% 초과: 거품 가능성, 유동성 긍정 판정 보류")
        if s["early_signals"]:
            L.append(f"- 🔔 막 켜지는 신호: {', '.join(s['early_signals'])}")
        L.append("")

    L += ["## 2단계 · 포트폴리오 후보 (주도 섹터 내 COMP 상위, 섹터당 최대 3종목)", ""]
    if len(picks):
        L += ["| # | 종목 | 섹터 | COMP | 등급 | 순위모멘텀 | 스마트머니 | 가격모멘텀 | 밸류 | 4주 | 52주 | 신고가 괴리 | 근거 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for i, (code, r) in enumerate(picks.iterrows(), 1):
            L.append(f"| {i} | {r['name']} ({code}) | {r['sector']} | **{r['comp']:.1f}** | {r['grade']} | "
                     f"{r['rank_mom']:.0f} | {r['smart_money']:.0f} | {r['price_mom']:.0f} | {r['valuation']:.0f} | "
                     f"{pct(r['ret_4w'])} | {pct(r['ret_52w'])} | {pct(r['high52_gap'])} | {r['pick_basis']} |")
    else:
        L.append("주도 섹터와 관찰 섹터가 없어 이번에는 후보를 고르지 않음.")
    L.append("")

    L += ["## 참고 · 전체 유니버스 COMP 상위 30 (섹터 무관)", "",
          "| 순위 | 종목 | 섹터 | 업종 | COMP | 등급 | 주도 섹터 |", "|---|---|---|---|---|---|---|"]
    for code, r in df.head(30).iterrows():
        L.append(f"| {r['comp_rank']} | {r['name']} ({code}) | {r['sector']} | {r['industry']} | {r['comp']:.1f} | "
                 f"{r['grade']} | {'✅' if r['sector'] in lead else ''} |")
    grade_counts = df["grade"].value_counts()
    L += ["", "등급 분포: " + " · ".join(f"{g} {grade_counts.get(g, 0)}개" for _, g in C.GRADES), ""]

    L += ["## 방법과 한계", ""] + [f"- {x}" for x in universe_log] + [
        "- 섹터 눈: 섹터 ETF 1개로 모멘텀·유동성, 해당 업종(네이버 분류) 유니버스 종목으로 펀더멘털을 판단.",
        "- 각 눈은 체크 통과 비율 2/3 이상 긍정, 1/3 이상 중립, 그 미만 부정.",
        "- 펀더멘털: 섹터 합산 영업이익(컨센서스) 증가율이 섹터 중앙값 이상, EPS 증가 종목 50% 이상, (기록이 쌓이면) EPS 추정치 상향 우세.",
        "- 유동성: 거래대금 +20%(최근 5일 vs 직전 10일), 외국인·기관 20일 동시 순매수, (기록이 쌓이면) 순자산 증가. 괴리율 1% 초과 시 긍정 판정 보류.",
        "- 판정: 세 눈 긍정 = 강력한 주도 섹터, 두 눈 긍정 + 한 눈 중립 = 유력 후보. 포트폴리오는 이 두 등급 섹터에서만 고름.",
        "- COMP: 하위 지표 PERCENTRANK 평균 → 기둥별 다시 PERCENTRANK(0~100) → 40/30/20/10 가중 평균. 결측치는 중립 0.5.",
        "- 선행 PER은 현재가 ÷ 컨센서스 EPS(없으면 직전 연도 EPS). 네이버 컨센서스는 올해(2026E)까지만 있어 '내년' 대신 올해 추정치를 씀.",
        "- 영업이익 성장률은 컨센서스 대비 직전 연도, 컨센서스가 없으면 최근 두 해 실적으로 계산. 흑자전환 +100%, 적자 -100%로 취급.",
        "- 스마트머니 순매수 금액은 일별 순매수 수량 × 종가 합계(근사치).",
        "- 네이버 업종 '기타' 등 섹터에 매핑되지 않은 종목은 COMP는 계산하지만 포트폴리오 후보에서 빠짐.",
        "- 4~6주마다 다시 실행해 신호 변화를 확인하고 교체. 투자자문 아님.",
    ]
    return "\n".join(L) + "\n"
