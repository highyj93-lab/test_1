"""4팩터 F 스코어 (DART 재무제표): 매출 성장 · 매출총이익률 · 판관비율 · 총자산회전율, 전년 동기 대비."""
import io
import json
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import date

import requests

DART = "https://opendart.fss.or.kr/api"
# 최신 보고서부터: 3분기, 반기, 1분기, (작년) 사업보고서
REPORTS = [("11014", "3분기"), ("11012", "반기"), ("11013", "1분기"), ("11011", "사업")]

ACCOUNTS = {
    "revenue": (["ifrs-full_Revenue", "ifrs_Revenue"], ["매출액", "수익(매출액)", "영업수익", "매출", "총매출액"]),
    "gross_profit": (["ifrs-full_GrossProfit", "ifrs_GrossProfit"], ["매출총이익", "매출총이익(손실)"]),
    "cogs": (["ifrs-full_CostOfSales", "ifrs_CostOfSales"], ["매출원가"]),
    "sga": (["dart_TotalSellingGeneralAdministrativeExpenses"], ["판매비와관리비", "판매비와 관리비", "판매비 및 관리비"]),
    "assets": (["ifrs-full_Assets", "ifrs_Assets"], ["자산총계"]),
}


class DartBlocked(Exception):
    pass


def _amount(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


class FScore:
    def __init__(self, api_key, cache_dir):
        self.key = api_key
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.session = requests.Session()
        self._corp = None

    def _get(self, endpoint, cache_name=None, **params):
        fp = os.path.join(self.cache_dir, cache_name) if cache_name else None
        if fp and os.path.exists(fp):
            with open(fp, "rb") as f:
                return f.read()
        try:
            r = self.session.get(f"{DART}/{endpoint}", params={"crtfc_key": self.key, **params}, timeout=60)
        except requests.exceptions.ProxyError as e:
            raise DartBlocked(str(e)) from e
        r.raise_for_status()
        if fp:
            with open(fp, "wb") as f:
                f.write(r.content)
        return r.content

    def corp_code(self, stock_code):
        if self._corp is None:
            raw = self._get("corpCode.xml", "corpCode.zip")
            z = zipfile.ZipFile(io.BytesIO(raw))
            root = ET.fromstring(z.read(z.namelist()[0]))
            self._corp = {e.findtext("stock_code").strip(): e.findtext("corp_code")
                          for e in root.iter("list") if (e.findtext("stock_code") or "").strip()}
        return self._corp.get(stock_code)

    def statements(self, corp, year, reprt):
        for fs in ("CFS", "OFS"):
            raw = self._get("fnlttSinglAcntAll.json", f"fs_{corp}_{year}_{reprt}_{fs}.json",
                            corp_code=corp, bsns_year=year, reprt_code=reprt, fs_div=fs)
            d = json.loads(raw)
            if d.get("status") == "000" and d.get("list"):
                return d["list"], fs
        return None, None

    @staticmethod
    def extract(rows):
        """보고서 1건 → 누적 기준 매출·매출총이익·판관비, 기말 자산총계."""
        out = {}
        for key, (ids, names) in ACCOUNTS.items():
            want_bs = key == "assets"
            for r in rows:
                is_bs = r.get("sj_div") == "BS"
                if is_bs != want_bs:
                    continue
                if r.get("account_id") in ids or r.get("account_nm", "").replace(" ", "") in [n.replace(" ", "") for n in names]:
                    v = _amount(r.get("thstrm_add_amount")) if not want_bs else None
                    if v is None:
                        v = _amount(r.get("thstrm_amount"))
                    if v is not None:
                        out[key] = v
                        break
        if "gross_profit" not in out and "revenue" in out and "cogs" in out:
            out["gross_profit"] = out["revenue"] - out["cogs"]
        return out

    def score(self, stock_code, today=None):
        corp = self.corp_code(stock_code)
        if not corp:
            return {"f_note": "DART 고유번호 없음"}
        y = (today or date.today()).year
        candidates = [(y, code, label) for code, label in REPORTS if code != "11011"] + [(y - 1, "11011", "사업")]
        for yr, reprt, label in candidates:
            cur, fs = self.statements(corp, str(yr), reprt)
            if not cur:
                continue
            prev, _ = self.statements(corp, str(yr - 1), reprt)
            if not prev:
                continue
            a, b = self.extract(cur), self.extract(prev)
            return self._factors(a, b, f"{yr} {label} vs {yr - 1} {label} ({'연결' if fs == 'CFS' else '별도'})")
        return {"f_note": "비교 가능한 재무제표 없음"}

    @staticmethod
    def _factors(a, b, basis):
        res = {"f_basis": basis}

        def ratio(x, k1, k2):
            return x[k1] / x[k2] if x.get(k1) is not None and x.get(k2) else None

        f = {}
        if a.get("revenue") is not None and b.get("revenue") is not None:
            f["f_sales"] = int(a["revenue"] > b["revenue"])
            res["sales_growth"] = a["revenue"] / b["revenue"] - 1 if b["revenue"] else None
        gpm_a, gpm_b = ratio(a, "gross_profit", "revenue"), ratio(b, "gross_profit", "revenue")
        if gpm_a is not None and gpm_b is not None:
            f["f_gpm"] = int(gpm_a > gpm_b)
            res["gpm"], res["gpm_prev"] = gpm_a, gpm_b
        sga_a, sga_b = ratio(a, "sga", "revenue"), ratio(b, "sga", "revenue")
        if sga_a is not None and sga_b is not None:
            f["f_sga"] = int(sga_a < sga_b)
            res["sga_ratio"], res["sga_ratio_prev"] = sga_a, sga_b
        at_a, at_b = ratio(a, "revenue", "assets"), ratio(b, "revenue", "assets")
        if at_a is not None and at_b is not None:
            f["f_turnover"] = int(at_a > at_b)
            res["asset_turnover"], res["asset_turnover_prev"] = at_a, at_b
        res.update(f)
        res["f_available"] = len(f)
        res["f_score"] = sum(f.values()) if f else None
        return res
