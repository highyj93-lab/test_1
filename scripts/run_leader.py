"""Run the full workflow: 세 가지 눈 섹터 분석 → COMP 종목 점수 → TOP 10~15 선정.

Usage:
    python scripts/run_leader.py            # 결과: data/leader/<날짜>/, vault/리포트/
"""
import argparse
import glob
import json
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leader import comp, report, sector_eyes, universe  # noqa: E402
from leader import config as C  # noqa: E402
from leader.naver import Naver  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_prev_snapshot(hist_dir, as_of):
    cutoff = (date.fromisoformat(as_of) - timedelta(days=C.HISTORY_MIN_GAP_DAYS)).isoformat()
    files = sorted(f for f in glob.glob(f"{hist_dir}/*.json") if os.path.basename(f)[:-5] <= cutoff)
    if not files:
        return None
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "cache", date.today().isoformat()))
    ap.add_argument("--vault", default=os.path.join(ROOT, "vault", "리포트"))
    args = ap.parse_args()

    t0 = time.time()
    notes = []

    def log(msg):
        notes.append(msg)
        print(f"[{time.time() - t0:5.0f}s] {msg}", flush=True)

    nv = Naver(args.cache)
    as_of = nv.prices("KOSPI", 1, index=True)[-1]["date"]
    hist_dir = os.path.join(ROOT, "data", "leader", "history")
    prev = load_prev_snapshot(hist_dir, as_of)
    log(f"기준일 {as_of}" + (f", 비교 스냅샷 {prev['as_of']}" if prev else ", 비교할 과거 기록 없음(첫 실행)"))

    uni = universe.build(nv, log)
    sectors, kospi = sector_eyes.analyze(nv, uni, prev, log)
    df = comp.score(uni)
    picks, lead, watch = comp.pick(df, sectors)
    log(f"COMP 계산 {len(df)}종목 · 주도 섹터 {len(lead)}개 · 후보 {len(picks)}종목")

    out_dir = os.path.join(ROOT, "data", "leader", as_of)
    report.write_csv(out_dir, sectors, df, picks)
    md = report.markdown(as_of, kospi, notes, sectors, df, picks, lead, watch, prev is not None)
    os.makedirs(args.vault, exist_ok=True)
    md_path = os.path.join(args.vault, f"주도섹터 COMP {as_of}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    os.makedirs(hist_dir, exist_ok=True)
    snap = {"as_of": as_of,
            "aum": {s["etf"]: s["aum_eok"] for s in sectors},
            "eps_e": {s["code"]: s["eps_e"] for s in uni if s["eps_e"] is not None}}
    with open(os.path.join(hist_dir, f"{as_of}.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)

    log(f"완료 → {md_path}")
    print("\n주도 섹터:", ", ".join(lead) or "없음")
    for i, (code, r) in enumerate(picks.iterrows(), 1):
        print(f"{i:2d}. {r['name']:<14} {r['sector']:<10} COMP {r['comp']:5.1f} {r['grade']}")


if __name__ == "__main__":
    main()
