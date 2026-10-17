"""KOSPI 유니버스 → COMP(v2) → COMP 70↑ 중간 출력 → COMP 80↑ F 스코어 → 최종 통과 종목.

Usage:
    python scripts/run_comp_fscore.py                       # 오늘 데이터로 실행
    python scripts/run_comp_fscore.py --cache data/cache/2026-10-11   # 받아둔 캐시로 재계산
"""
import argparse
import os
import sys
import time
from datetime import date

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leader import comp_kospi, universe  # noqa: E402
from leader import config as C  # noqa: E402
from leader.fscore import DartBlocked, FScore  # noqa: E402
from leader.naver import Naver  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pct(v, signed=True):
    if v is None or pd.isna(v):
        return "-"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def eok(v):
    return "-" if v is None or pd.isna(v) else f"{v / 1e8:+,.0f}억"


def f_cell(r, k):
    v = r.get(k)
    return "-" if v is None or pd.isna(v) else ("1" if v == 1 else "0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "cache", date.today().isoformat()))
    ap.add_argument("--vault", default=os.path.join(ROOT, "vault", "리포트"))
    args = ap.parse_args()
    load_dotenv(os.path.join(ROOT, ".env"))

    t0 = time.time()
    notes = []

    def log(msg):
        notes.append(msg)
        print(f"[{time.time() - t0:5.0f}s] {msg}", flush=True)

    nv = Naver(args.cache)
    kospi_px = nv.prices("KOSPI", 5, index=True)
    if not kospi_px:
        sys.exit("코스피 지수 시세를 받지 못했습니다(네트워크 또는 캐시 없음).")
    as_of = kospi_px[-1]["date"]
    kc = [p["close"] for p in kospi_px]
    kospi_ret = {n: kc[-1] / kc[-1 - n] - 1 for n in (20, 60, 125, 250) if len(kc) > n}
    log(f"기준일 {as_of} · 코스피 1/3/6/12개월 " + " / ".join(pct(kospi_ret.get(n)) for n in (20, 60, 125, 250)))

    uni = universe.build(nv, log, markets={"KOSPI"}, quarterly=True)
    if nv.misses:
        log(f"⚠️ 네이버 접속이 막혀 캐시에 없는 요청 {nv.misses}건은 건너뜀(분기 실적 등은 연간 자료로 대체)")
    df = comp_kospi.score(uni, kospi_ret)
    mid = df[df["comp"] >= C.COMP_REPORT_MIN]
    top = df[df["comp"] >= C.COMP_FSCORE_MIN]
    log(f"COMP 계산 {len(df)}종목 · {C.COMP_REPORT_MIN}점↑ {len(mid)}종목 · {C.COMP_FSCORE_MIN}점↑ {len(top)}종목")

    # 모듈 2: F 스코어 (COMP 80↑)
    fs_rows, fs_status = {}, "ok"
    key = os.environ.get("DART_API_KEY")
    if not key:
        fs_status = "DART_API_KEY 없음(.env)"
    else:
        fs = FScore(key, os.path.join(args.cache, "dart"))
        try:
            for code in top.index:
                fs_rows[code] = fs.score(code, today=date.fromisoformat(as_of))
        except DartBlocked:
            fs_status = "DART(opendart.fss.or.kr) 접속이 네트워크 정책에 막힘"
    log(f"F 스코어: {len(fs_rows)}종목 계산" + ("" if fs_status == "ok" else f" · {fs_status}"))
    fdf = pd.DataFrame.from_dict(fs_rows, orient="index")
    out = mid.join(fdf, how="left") if len(fdf) else mid.copy()
    for col in ("f_score", "f_available", "f_sales", "f_gpm", "f_sga", "f_turnover", "f_basis", "f_note"):
        if col not in out:
            out[col] = None

    def verdict(r):
        if r["comp"] < C.COMP_FSCORE_MIN:
            return "COMP 70~80 (F 미적용)"
        if pd.isna(r["f_score"]):
            return "F 계산 불가"
        if (r["f_available"] or 0) >= 3 and r["f_score"] >= C.F_PASS_MIN:
            return "✅ 최종 통과"
        return "탈락"

    out["verdict"] = out.apply(verdict, axis=1)
    final = out.sort_values("comp", ascending=True)

    out_dir = os.path.join(ROOT, "data", "comp_f", as_of)
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(f"{out_dir}/comp_all.csv", encoding="utf-8-sig")
    final.to_csv(f"{out_dir}/comp70_fscore.csv", encoding="utf-8-sig")

    passed = final[final["verdict"] == "✅ 최종 통과"]
    L = ["---", f"date: {as_of}", "tags: [COMP, F스코어, 리포트]", "---",
         f"# KOSPI COMP · F 스코어 ({as_of})", "",
         f"기준일 {as_of} 종가 · 유니버스 KOSPI {len(df)}종목 · 투자자문 아님", "",
         "## 요약",
         f"- COMP {C.COMP_REPORT_MIN}점 이상 {len(mid)}종목, 그중 {C.COMP_FSCORE_MIN}점 이상 {len(top)}종목에 F 스코어 적용",
         f"- 최종 통과({C.COMP_FSCORE_MIN}점↑ & F {C.F_PASS_MIN}/4↑): " + (", ".join(passed["name"]) if len(passed) else "없음")]
    if fs_status != "ok":
        L.append(f"- ⚠️ F 스코어 미계산: {fs_status}")
    L += ["", f"## 최종 결과 · COMP {C.COMP_REPORT_MIN}점 이상 (COMP 오름차순)", "",
          "| COMP | 종목 | 업종 | 순위모멘텀 | 스마트머니 | 가격모멘텀 | 밸류 | 등급 | F 매출 | F 총이익률 | F 판관비 | F 자산회전 | F 합계 | 판정 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for code, r in final.iterrows():
        ftot = "-" if pd.isna(r["f_score"]) else f"{int(r['f_score'])}/{int(r['f_available'])}"
        L.append(f"| **{r['comp']:.1f}** | {r['name']} ({code}) | {r['industry']} | {r['rank_mom']:.0f} | "
                 f"{r['smart_money']:.0f} | {r['price_mom']:.0f} | {r['valuation']:.0f} | {r['grade']} | "
                 f"{f_cell(r, 'f_sales')} | {f_cell(r, 'f_gpm')} | {f_cell(r, 'f_sga')} | {f_cell(r, 'f_turnover')} | "
                 f"{ftot} | {r['verdict']} |")

    L += ["", "## 세부 지표 (COMP 오름차순)", "",
          "| 종목 | 상대강도 1M/3M/6M/12M | 가중순위+벌점 | 기관 20일 | 외국인 20일 | 외국인 보유율 Δ | 1주/1개월/3개월 | 신고가 괴리 | ROE | 12M 선행 PER | 영업이익 YoY |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for code, r in final.iterrows():
        per = "-" if pd.isna(r["per_12m"]) else ("적자" if r["per_12m"] >= 1e8 else f"{r['per_12m']:.1f}")
        fchg = "-" if pd.isna(r["frgn_ratio_chg"]) else f"{r['frgn_ratio_chg']:+.2f}%p"
        roe = "-" if pd.isna(r["roe"]) else f"{r['roe']:.1f}%"
        L.append(f"| {r['name']} | {pct(r['rs_1m'])} / {pct(r['rs_3m'])} / {pct(r['rs_6m'])} / {pct(r['rs_12m'])} | "
                 f"{r['rank_weighted']:.0f}+{0.5 * r['rank_std']:.0f} | {eok(r['inst_net_20d'])} | {eok(r['frgn_net_20d'])} | "
                 f"{fchg} | {pct(r['ret_1w'])} / {pct(r['ret_4w'])} / {pct(r['ret_12w'])} | {pct(r['high52_gap'])} | "
                 f"{roe} | {per} | {pct(r['op_yoy'])} |")

    ftab = final[final["comp"] >= C.COMP_FSCORE_MIN]
    if len(ftab) and fs_status == "ok":
        L += ["", "## F 스코어 근거 (COMP 80점 이상)", "",
              "| 종목 | 비교 기준 | 매출 증가율 | 매출총이익률 | 판관비율 | 총자산회전율 |", "|---|---|---|---|---|---|"]
        for code, r in ftab.iterrows():
            def pair(a, b):
                return "-" if pd.isna(r.get(a)) or pd.isna(r.get(b)) else f"{r[b]:.1%} → {r[a]:.1%}"
            basis = r["f_basis"] if isinstance(r.get("f_basis"), str) else (r.get("f_note") or "-")
            turnover = ("-" if pd.isna(r.get("asset_turnover"))
                        else f"{r['asset_turnover_prev']:.2f} → {r['asset_turnover']:.2f}")
            L.append(f"| {r['name']} | {basis} | {pct(r.get('sales_growth'))} | {pair('gpm', 'gpm_prev')} | "
                     f"{pair('sga_ratio', 'sga_ratio_prev')} | {turnover} |")

    L += ["", "## 방법", ""] + [f"- {x}" for x in notes] + [
        "- 유니버스: KOSPI, 시가총액 300억 이상, 20일 평균 거래대금 10억 이상, 우선주·스팩 제외.",
        "- 기둥 1 순위 모멘텀(40%): 코스피 대비 1·3·6·12개월 상대강도 순위 Rᵢ로 Σwᵢ·Rᵢ(0.4/0.3/0.2/0.1) + 0.5·σ(R). 값이 작을수록 좋고, 이를 PERCENTRANK로 0~100점 환산.",
        "- 기둥 2 스마트머니(30%): 기관·외국인 20거래일 순매수 금액(일별 수량×종가), 외국인 보유율 20거래일 증가폭.",
        "- 기둥 3 가격 모멘텀(20%): 1주·1개월·3개월 수익률, 52주 신고가 괴리율(작을수록 높은 점수).",
        "- 기둥 4 밸류에이션(10%): ROE, 12개월 선행 PER(낮을수록 좋음, 적자는 최하점), 영업이익 YoY.",
        "  - 12개월 선행 EPS = 최근 3개 분기 실적 + 다음 분기 컨센서스. 분기 컨센서스가 없으면 올해 연간 컨센서스, 그것도 없으면 직전 연도 실적.",
        "  - 영업이익 YoY = 최근 분기 vs 전년 같은 분기. 분기 자료가 없으면 연간 비교.",
        "- 기둥 2~4는 세부지표 PERCENTRANK 평균을 다시 PERCENTRANK(0~100). 결측은 중립 0.5.",
        "- F 스코어: DART 정기보고서(연결 우선, 없으면 별도)의 누적 실적을 전년 같은 보고서와 비교. 매출 증가, 매출총이익률 상승, 판관비/매출 하락, 매출/자산총계 상승 각 1점.",
        f"- 최종 통과: COMP {C.COMP_FSCORE_MIN}점 이상이면서 F 스코어 {C.F_PASS_MIN}점 이상(계산 가능한 팩터 3개 이상). 금융업처럼 매출총이익이 없는 업종은 해당 팩터를 빼고 계산.",
    ]
    os.makedirs(args.vault, exist_ok=True)
    md_path = os.path.join(args.vault, f"KOSPI COMP F스코어 {as_of}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    log(f"완료 → {md_path}")

    print(f"\n[중간 결과] COMP {C.COMP_REPORT_MIN}점 이상 {len(mid)}종목 (오름차순)")
    for code, r in final.iterrows():
        ftot = "-" if pd.isna(r["f_score"]) else f"{int(r['f_score'])}/{int(r['f_available'])}"
        print(f"  {r['comp']:5.1f}  {r['name']:<14} F {ftot:<4} {r['verdict']}")


if __name__ == "__main__":
    main()
