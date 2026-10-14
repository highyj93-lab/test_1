"""CSV, Markdown (Obsidian) and console outputs for the KOSPI COMP → F-score workflow."""
import os

import pandas as pd

from leader.report import pct

from . import config as C

ICON = {1: "✅", 0: "❌"}
F_COLS = [("f1_rev", "매출"), ("f2_gpm", "GPM"), ("f3_sga", "판관비율"), ("f4_ato", "자산회전율")]


def _na(v):
    return v is None or (isinstance(v, float) and pd.isna(v))


def _icon(v):
    return "N/A" if _na(v) else ICON[int(v)]


def _arrow(prior, cur, fmt):
    if _na(prior) or _na(cur):
        return "-"
    return f"{format(prior, fmt)}→{format(cur, fmt)}"


def factor_cells(r):
    """F 스코어 세부 4칸: 판정 아이콘 + 전년 동기 → 당기 값."""
    if _na(r.get("f_score")):
        return ["-"] * 4
    return [f"{_icon(r['f1_rev'])} {pct(r['rev_growth'])}",
            f"{_icon(r['f2_gpm'])} {_arrow(r['gpm_prior'], r['gpm_cur'], '.1%')}",
            f"{_icon(r['f3_sga'])} {_arrow(r['sga_ratio_prior'], r['sga_ratio_cur'], '.1%')}",
            f"{_icon(r['f4_ato'])} {_arrow(r['ato_prior'], r['ato_cur'], '.2f')}"]


def f_text(r):
    if r["comp"] < C.COMP_FSCORE:
        return "-"
    if _na(r.get("f_score")):
        return "미산출"
    na = 4 - int(r["f_available"])
    return f"**{int(r['f_score'])}**/4" + (f" (N/A {na})" if na else "")


def verdict(r):
    if r["comp"] < C.COMP_FSCORE:
        return f"관찰 (COMP {C.COMP_REPORT}~{C.COMP_FSCORE})"
    if _na(r.get("f_score")):
        return f"F 미산출: {r.get('f_note') or '-'}"
    return "✅ 최종 통과" if r["f_pass"] else f"F {C.F_PASS}점 미달"


def final_table(df, fs):
    """COMP 70 이상 전 종목 + (80 이상이면) F 스코어. COMP 오름차순."""
    t = df[df["comp"] >= C.COMP_REPORT].join(fs, how="left")
    t["verdict"] = [verdict(r) for _, r in t.iterrows()]
    t["final_pass"] = t["verdict"] == "✅ 최종 통과"
    return t.sort_values("comp", ascending=C.FINAL_ASCENDING)


def write_csv(out_dir, df, fs=None, final=None):
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(f"{out_dir}/comp_all.csv", encoding="utf-8-sig")
    df[df["comp"] >= C.COMP_REPORT].to_csv(f"{out_dir}/comp{C.COMP_REPORT}.csv", encoding="utf-8-sig")
    if fs is not None:
        fs.to_csv(f"{out_dir}/fscore.csv", encoding="utf-8-sig")
    if final is not None:
        final.to_csv(f"{out_dir}/final.csv", encoding="utf-8-sig")


def _rs(r):
    return " / ".join(pct(r[f"rs_{p}"]) for p in C.RS_PERIODS)


def _ranks(r):
    return "·".join(f"{r[f'R_{p}']:.0f}" for p in C.RS_PERIODS) + f" (σ {r['rm_sigma']:.0f})"


def markdown(as_of, kospi_ret, notes, df, fs, final, f_status):
    mid = df[df["comp"] >= C.COMP_REPORT]
    cand = df[df["comp"] >= C.COMP_FSCORE]
    passed = final[final["final_pass"]]
    L = ["---", f"date: {as_of}", "tags: [KOSPI, COMP, F스코어, 리포트]", "---",
         f"# KOSPI COMP · 4팩터 F 스코어 ({as_of})", "",
         f"기준일 {as_of} 종가 · 코스피 1/3/6/12개월 "
         + " / ".join(pct(kospi_ret[p]) for p in C.RS_PERIODS) + " · 투자자문 아님", "",
         "## 요약",
         f"- KOSPI 유니버스 {len(df)}종목 → COMP {C.COMP_REPORT}점 이상 {len(mid)}종목 → "
         f"COMP {C.COMP_FSCORE}점 이상 {len(cand)}종목 → F 스코어 {C.F_PASS}점 이상 최종 통과 {len(passed)}종목",
         "- 최종 통과: " + (", ".join(f"{r['name']}(COMP {r['comp']:.1f}, F {int(r['f_score'])})"
                                    for _, r in passed.iterrows()) or "없음"),
         f"- F 스코어: {f_status}", ""]

    L += [f"## 1. 중간 결과 · COMP {C.COMP_REPORT}점 이상 (COMP 내림차순)", "",
          "| 순위 | 종목 | 업종 | COMP | 순위모멘텀 | 스마트머니 | 가격모멘텀 | 밸류 | 코스피 대비 RS 1M/3M/6M/12M | RS 순위 1M·3M·6M·12M | F 대상 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for code, r in mid.iterrows():
        L.append(f"| {r['comp_rank']} | {r['name']} ({code}) | {r['industry']} | **{r['comp']:.1f}** | "
                 f"{r['rank_mom']:.0f} | {r['smart_money']:.0f} | {r['price_mom']:.0f} | {r['valuation']:.0f} | "
                 f"{_rs(r)} | {_ranks(r)} | {'✅' if r['comp'] >= C.COMP_FSCORE else ''} |")
    L.append("")

    L += [f"## 2. 4팩터 F 스코어 · COMP {C.COMP_FSCORE}점 이상", ""]
    rows = cand.join(fs, how="left")
    if len(rows):
        L += ["| 종목 | COMP | 비교 기간 | 기준 | 매출(당기) | 매출 성장 | GPM | 판관비율 | 자산회전율 | F 스코어 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for code, r in rows.iterrows():
            if _na(r.get("f_score")):
                L.append(f"| {r['name']} ({code}) | {r['comp']:.1f} | - | - | - | - | - | - | - | 미산출: {r['f_note']} |")
                continue
            rev = f"{r['rev_cur'] / 1e8:,.0f}억" if not _na(r["rev_cur"]) else "-"
            L.append(f"| {r['name']} ({code}) | {r['comp']:.1f} | {r['f_period']} | {r['fs_div']} | {rev} | "
                     + " | ".join(factor_cells(r)) + f" | {f_text(r)} |")
    else:
        L.append(f"COMP {C.COMP_FSCORE}점 이상 종목이 없음.")
    L.append("")

    order = "오름차순" if C.FINAL_ASCENDING else "내림차순"
    L += [f"## 3. 최종 결과 · COMP {C.COMP_REPORT}점 이상 (COMP {order})", "",
          "| # | 종목 | 업종 | COMP | 순위모멘텀 | 스마트머니 | 가격모멘텀 | 밸류 | F 스코어 | 매출 | GPM | 판관비율 | 자산회전율 | 판정 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, (code, r) in enumerate(final.iterrows(), 1):
        L.append(f"| {i} | {r['name']} ({code}) | {r['industry']} | **{r['comp']:.1f}** | {r['rank_mom']:.0f} | "
                 f"{r['smart_money']:.0f} | {r['price_mom']:.0f} | {r['valuation']:.0f} | {f_text(r)} | "
                 + " | ".join(factor_cells(r)) + f" | {r['verdict']} |")
    L.append("")

    L += ["## 방법과 한계", ""] + [f"- {x}" for x in notes] + [
        "- 유니버스: KOSPI 상장 보통주, 시가총액 300억 이상, 20일 평균 거래대금 10억 이상(우선주·스팩 제외).",
        "- 기둥 1 순위 모멘텀(40%): 기간별 코스피 대비 상대강도 RS = (1+종목 수익률)/(1+코스피 수익률)-1, "
        "유니버스 내 순위 R(1=최강). ➊ Π R^w (w 0.4/0.3/0.2/0.1)와 ➋ Σ w·R + 0.5·σ(R)(4개 순위의 모표준편차)를 "
        "각각 낮을수록 높은 PERCENTRANK로 바꿔 평균. 수익률이 없는 기간(신규 상장)은 중간 순위로 채움.",
        "- 기둥 2 스마트머니(30%): 20일 기관 순매수 금액, 20일 외국인 순매수 금액(일별 순매수 수량 × 종가 합계), "
        "20일 외국인 보유율 변화(%p).",
        "- 기둥 3 가격 모멘텀(20%): 1주·1개월·3개월 수익률, 52주 신고가 괴리율(신고가에 가까울수록 높은 점수).",
        "- 기둥 4 밸류에이션(10%): ROE, 12개월 선행 PER(낮을수록 높은 점수, 적자는 최하위), 영업이익 성장률. "
        "선행 EPS는 컨센서스가 두 해 있으면 올해·내년을 남은 기간 비율로 섞고, 한 해만 있으면 그 해, 없으면 직전 실적.",
        "- 기둥 점수: 하위 지표 PERCENTRANK 평균 → 다시 PERCENTRANK(0~100). COMP = 40/30/20/10 가중합. 결측치는 중립 0.5.",
        "- F 스코어: DART 최신 정기보고서(연결 우선, 없으면 별도)의 기간 누적 손익을 전년 동기와 비교. "
        "총자산회전율 = 누적 매출 ÷ 평균 총자산(기초·기말), 기초 값이 없으면 기말 총자산. 개선 1점, 악화·동일 0점.",
        "- 은행·보험·증권처럼 매출총이익·판관비 계정이 없는 업종은 해당 팩터가 N/A(0점)로 처리돼 통과가 어려움.",
        f"- 최종 통과 = COMP {C.COMP_FSCORE}점 이상 + F 스코어 {C.F_PASS}점 이상(4점 만점). 기준은 kospi_comp/config.py에서 바꿈.",
        "- 네이버 증권 수치는 KRX 공식 수치와 기준이 조금 다를 수 있음. 투자자문 아님.",
    ]
    return "\n".join(L) + "\n"


def print_mid(df):
    mid = df[df["comp"] >= C.COMP_REPORT]
    print(f"\n[중간 결과] COMP {C.COMP_REPORT}점 이상 {len(mid)}종목 (내림차순)")
    for code, r in mid.iterrows():
        mark = "→ F 스코어" if r["comp"] >= C.COMP_FSCORE else ""
        print(f"{r['comp_rank']:4d}. {r['name']:<14} {code}  COMP {r['comp']:5.1f}  "
              f"[{r['rank_mom']:3.0f} {r['smart_money']:3.0f} {r['price_mom']:3.0f} {r['valuation']:3.0f}] {mark}")


def print_final(final):
    order = "오름차순" if C.FINAL_ASCENDING else "내림차순"
    print(f"\n[최종 결과] COMP {C.COMP_REPORT}점 이상 · COMP {order}")
    for i, (code, r) in enumerate(final.iterrows(), 1):
        f = "-" if r["comp"] < C.COMP_FSCORE or _na(r.get("f_score")) else f"{int(r['f_score'])}/4"
        print(f"{i:4d}. {r['name']:<14} {code}  COMP {r['comp']:5.1f}  F {f:<4} {r['verdict']}")
