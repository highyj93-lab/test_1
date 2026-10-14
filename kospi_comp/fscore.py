"""모듈 2: 4팩터 F 스코어 — DART 정기보고서로 전년 동기 대비 4가지 개선 여부를 채점.

팩터 1 매출 성장    : 매출액 > 전년 동기
팩터 2 GPM 개선     : 매출총이익 / 매출액 > 전년 동기
팩터 3 판관비 효율  : 판관비 / 매출액 < 전년 동기
팩터 4 자산회전율   : 매출액 / 평균 총자산 > 전년 동기

손익은 보고서 기간 누적(1분기·반기·3분기 누적, 사업보고서는 연간) 기준으로 비교한다.
"""
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import requests

from dart_api import DartApiError

from . import config as C

REPORT_NAME = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "사업"}
PERIOD_END = {"11013": (3, 31), "11012": (6, 30), "11014": (9, 30), "11011": (12, 31)}
NO_DATA = "013"
COLUMNS = ["f_period", "fs_div", "rev_cur", "rev_prior", "rev_growth", "gpm_cur", "gpm_prior",
           "sga_ratio_cur", "sga_ratio_prior", "ato_cur", "ato_prior", "assets_basis",
           "f1_rev", "f2_gpm", "f3_sga", "f4_ato", "f_available", "f_score", "f_pass", "f_note"]

# key: (sj_div 우선순위, account_id 집합, 한글만 남긴 계정명 집합)
ACCOUNTS = {
    "revenue": (("IS", "CIS"), {"ifrs-full_Revenue", "ifrs_Revenue"},
                {"매출액", "매출", "수익매출액", "매출수익", "영업수익", "수익"}),
    "gross_profit": (("IS", "CIS"), {"ifrs-full_GrossProfit", "ifrs_GrossProfit"},
                     {"매출총이익", "매출총이익손실", "매출총손익"}),
    "cost_of_sales": (("IS", "CIS"), {"ifrs-full_CostOfSales", "ifrs_CostOfSales"}, {"매출원가"}),
    "sga": (("IS", "CIS"),
            {"dart_TotalSellingGeneralAdministrativeExpenses",
             "ifrs-full_SellingGeneralAndAdministrativeExpense", "ifrs_SellingGeneralAndAdministrativeExpense"},
            {"판매비와관리비", "판매비및관리비", "판매비와일반관리비", "판매및일반관리비", "판관비"}),
    "assets": (("BS",), {"ifrs-full_Assets", "ifrs_Assets"}, {"자산총계"}),
}


def _num(v):
    v = (v or "").replace(",", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def find(rows, key):
    sj_divs, ids, names = ACCOUNTS[key]
    for sj in sj_divs:
        part = [r for r in rows if r.get("sj_div") == sj]
        for r in part:
            if r.get("account_id") in ids:
                return r
        for r in part:
            if re.sub(r"[^가-힣]", "", r.get("account_nm", "")) in names:
                return r
    return None


def _flow(row, annual):
    """손익 계정 -> (당기 누적, 전년 동기 누적)."""
    if row is None:
        return None, None
    if annual:
        return _num(row.get("thstrm_amount")), _num(row.get("frmtrm_amount"))
    if _num(row.get("thstrm_add_amount")) is not None:
        return _num(row["thstrm_add_amount"]), _num(row.get("frmtrm_add_amount"))
    return _num(row.get("thstrm_amount")), _num(row.get("frmtrm_q_amount"))


def _items(cur_rows, prev_rows, annual):
    """{계정: (당기, 전년 동기)}. 비교 수치가 없으면 전년 같은 보고서의 당기 값으로 채운다."""
    out = {}
    for key in ("revenue", "gross_profit", "cost_of_sales", "sga"):
        cur, prior = _flow(find(cur_rows, key), annual)
        if prior is None and prev_rows:
            prior = _flow(find(prev_rows, key), annual)[0]
        out[key] = (cur, prior)
    for i in range(2):  # 매출총이익이 없으면 매출액 - 매출원가
        if out["gross_profit"][i] is None and None not in (out["revenue"][i], out["cost_of_sales"][i]):
            gp = list(out["gross_profit"])
            gp[i] = out["revenue"][i] - out["cost_of_sales"][i]
            out["gross_profit"] = tuple(gp)

    a = find(cur_rows, "assets") or {}
    end_c, begin_c = _num(a.get("thstrm_amount")), _num(a.get("frmtrm_amount"))
    if annual:
        end_p, begin_p = begin_c, _num(a.get("bfefrmtrm_amount"))
    else:
        p = find(prev_rows or [], "assets") or {}
        end_p, begin_p = _num(p.get("thstrm_amount")), _num(p.get("frmtrm_amount"))
    if None not in (end_c, begin_c, end_p, begin_p):
        out["assets"] = ((end_c + begin_c) / 2, (end_p + begin_p) / 2)
        out["assets_basis"] = "평균 총자산"
    else:
        out["assets"] = (end_c, end_p)
        out["assets_basis"] = "기말 총자산"
    return out


def _ratio(a, b):
    return a / b if a is not None and b else None


def _point(cur, prior, higher_is_better=True):
    """1 = 개선, 0 = 악화·동일, None = 계산 불가."""
    if cur is None or prior is None:
        return None
    return int(cur > prior) if higher_is_better else int(cur < prior)


def factors(cur_rows, prev_rows, reprt):
    it = _items(cur_rows, prev_rows, reprt == "11011")
    rev_c, rev_p = it["revenue"]
    if rev_c is not None and rev_c <= 0 or rev_p is not None and rev_p <= 0:
        rev_c = rev_p = None  # 매출이 없으면 비율 계산 불가
    r = {
        "rev_cur": rev_c, "rev_prior": rev_p,
        "rev_growth": rev_c / rev_p - 1 if rev_c is not None and rev_p else None,
        "gpm_cur": _ratio(it["gross_profit"][0], rev_c), "gpm_prior": _ratio(it["gross_profit"][1], rev_p),
        "sga_ratio_cur": _ratio(it["sga"][0], rev_c), "sga_ratio_prior": _ratio(it["sga"][1], rev_p),
        "ato_cur": _ratio(rev_c, it["assets"][0]), "ato_prior": _ratio(rev_p, it["assets"][1]),
        "assets_basis": it["assets_basis"],
    }
    r["f1_rev"] = _point(rev_c, rev_p)
    r["f2_gpm"] = _point(r["gpm_cur"], r["gpm_prior"])
    r["f3_sga"] = _point(r["sga_ratio_cur"], r["sga_ratio_prior"], higher_is_better=False)
    r["f4_ato"] = _point(r["ato_cur"], r["ato_prior"])
    pts = [r[k] for k in ("f1_rev", "f2_gpm", "f3_sga", "f4_ato")]
    r["f_available"] = sum(p is not None for p in pts)
    r["f_score"] = sum(p for p in pts if p is not None)
    r["f_pass"] = r["f_score"] >= C.F_PASS
    return r


def report_candidates(as_of, limit=4):
    """기간이 끝난 정기보고서를 최신순으로: [(사업연도, 보고서 코드), ...]."""
    out = []
    for y in (as_of.year, as_of.year - 1):
        for reprt in ("11011", "11014", "11012", "11013"):
            if date(y, *PERIOD_END[reprt]) < as_of:
                out.append((y, reprt))
    return out[:limit]


class DartFinancials:
    def __init__(self, client, cache_dir, workers=4):
        self.client = client
        self.cache_dir = os.path.join(cache_dir, "dart")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.workers = workers

    def corp_codes(self):
        """종목코드 -> DART 고유번호."""
        fp = os.path.join(self.cache_dir, "corpCode.xml")
        if not os.path.exists(fp):
            with open(fp, "wb") as f:
                f.write(self.client.download_corp_codes())
        out = {}
        for el in ET.parse(fp).getroot().iter("list"):
            stock = (el.findtext("stock_code") or "").strip()
            if stock:
                out[stock] = el.findtext("corp_code").strip()
        return out

    def statements(self, corp, year, reprt, fs_div):
        """전체 재무제표 행 목록. 해당 보고서가 없으면 None."""
        fp = os.path.join(self.cache_dir, f"{corp}_{year}_{reprt}_{fs_div}.json")
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as f:
                return json.load(f)
        for attempt in range(3):
            try:
                rows = self.client.financial_statements(corp, year, reprt, fs_div).get("list") or None
                break
            except DartApiError as e:
                if e.status != NO_DATA:
                    raise
                rows = None
                break
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        return rows

    def latest(self, corp, as_of):
        """-> (사업연도, 보고서, 연결/별도, 당기 행, 전년 같은 보고서 행) 또는 None."""
        for year, reprt in report_candidates(as_of):
            for fs_div in ("CFS", "OFS"):
                rows = self.statements(corp, year, reprt, fs_div)
                if rows:
                    return year, reprt, fs_div, rows, self.statements(corp, year - 1, reprt, fs_div)
        return None

    def evaluate(self, df, as_of, log):
        """df(index=종목코드) 각 종목의 F 스코어 → DataFrame."""
        codes = self.corp_codes()

        def one(code):
            base = {"code": code}
            corp = codes.get(code)
            if not corp:
                return {**base, "f_note": "DART 고유번호 없음"}
            found = self.latest(corp, as_of)
            if not found:
                return {**base, "f_note": "정기보고서 재무제표 없음"}
            year, reprt, fs_div, cur, prev = found
            label = f"{year} {REPORT_NAME[reprt]} vs {year - 1} {REPORT_NAME[reprt]}"
            return {**base, "f_period": label, "fs_div": "연결" if fs_div == "CFS" else "별도",
                    **factors(cur, prev, reprt), "f_note": ""}

        with ThreadPoolExecutor(self.workers) as ex:
            rows = list(ex.map(one, list(df.index)))
        out = pd.DataFrame(rows, columns=["code"] + COLUMNS).set_index("code")
        log(f"F 스코어 계산 {out['f_score'].notna().sum()}/{len(out)}종목")
        return out
