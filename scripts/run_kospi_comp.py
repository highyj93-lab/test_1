"""Run the KOSPI screening workflow.

KOSPI 유니버스 → 모듈 1 COMP → 중간 결과(COMP 70+) → 모듈 2 4팩터 F 스코어(COMP 80+) → 최종 보고.

Usage:
    python scripts/run_kospi_comp.py        # 결과: data/kospi_comp/<기준일>/, vault/리포트/

F 스코어는 DART 재무제표를 쓰므로 DART_API_KEY(.env 또는 환경변수)가 필요하다.
키가 없거나 DART 호출이 실패하면 COMP 결과만 내고 F 스코어는 '미산출'로 남긴다.
"""
import argparse
import os
import sys
import time
from datetime import date

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dart_api import DartApiClient, DartApiError  # noqa: E402
from kospi_comp import comp, report  # noqa: E402
from kospi_comp import config as C  # noqa: E402
from kospi_comp.fscore import COLUMNS, DartFinancials  # noqa: E402
from leader import universe  # noqa: E402
from leader.naver import Naver  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    load_dotenv()
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
    kospi = nv.prices("KOSPI", universe.HISTORY_PAGES, index=True)
    as_of = kospi[-1]["date"]
    kospi_ret = {p: universe._ret([x["close"] for x in kospi], n) for p, n in C.RS_DAYS.items()}
    log(f"기준일 {as_of}")

    # 모듈 1: COMP
    uni = universe.build(nv, log, markets=C.MARKETS)
    df = comp.score(uni, kospi_ret, date.fromisoformat(as_of))
    n_mid, n_cand = (df["comp"] >= C.COMP_REPORT).sum(), (df["comp"] >= C.COMP_FSCORE).sum()
    log(f"COMP 계산 {len(df)}종목 · {C.COMP_REPORT}점 이상 {n_mid} · {C.COMP_FSCORE}점 이상 {n_cand}")

    out_dir = os.path.join(ROOT, "data", "kospi_comp", as_of)
    report.write_csv(out_dir, df)  # 모듈 2가 실패해도 중간 결과는 남김
    report.print_mid(df)

    # 모듈 2: 4팩터 F 스코어
    cand = df[df["comp"] >= C.COMP_FSCORE]
    fs = pd.DataFrame(index=cand.index, columns=COLUMNS)
    key = os.environ.get("DART_API_KEY")
    if not len(cand):
        f_status = f"COMP {C.COMP_FSCORE}점 이상 종목이 없음"
    elif not key:
        f_status = "DART_API_KEY가 없어 계산하지 않음"
    else:
        try:
            fs = DartFinancials(DartApiClient(key), args.cache).evaluate(cand, date.fromisoformat(as_of), log)
            f_status = f"{fs['f_score'].notna().sum()}/{len(cand)}종목 계산, 통과 기준 {C.F_PASS}점 이상"
        except (DartApiError, requests.RequestException) as e:
            f_status = f"DART 호출 실패로 계산하지 못함 ({e})"
    log(f"F 스코어: {f_status}")
    fs.loc[fs["f_score"].isna() & (fs["f_note"].fillna("") == ""), "f_note"] = f_status

    final = report.final_table(df, fs)
    report.write_csv(out_dir, df, fs, final)
    md = report.markdown(as_of, kospi_ret, notes, df, fs, final, f_status)
    os.makedirs(args.vault, exist_ok=True)
    md_path = os.path.join(args.vault, f"KOSPI COMP F스코어 {as_of}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    report.print_final(final)
    log(f"완료 → {md_path}")


if __name__ == "__main__":
    main()
