"""모듈 2: 한국시장용 섹터별 4·5팩터 F 스코어 (Piotroski F 스코어와 별개 체계).

모든 재무 수치는 DART 단일회사 전체 재무제표(fnlttSinglAcntAll)에서 가져온다.
현재 TTM(최근 4개 분기 합)을 1년 앞선 같은 4개 분기 합(전년 동기 TTM)과 비교한다.

공통 4팩터 : 매출성장 · 매출총이익률(GPM) 개선 · 판관비 효율 · 총자산회전율 개선
소재 5팩터 : 공통 4팩터 + 발생액 (WICS 대분류 '소재'만)

결측(null)은 0점으로 바꾸지 않는다. 원점수는 유효 팩터 점수의 합, 정규화 점수는
원점수 / 유효지표 수 × 섹터 기준 팩터 수(소재 외 4, 소재 5)다. 판정은 반올림 전 원값으로 한다.
"""
import json
import os
import re
import time
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from dart_api import DartApiError

REPORT_CODE = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}  # 회계 분기 → 보고서
REPORT_NAME = {1: "1분기", 2: "반기", 3: "3분기", 4: "사업"}
NO_DATA = "013"
NETWORK = "network"
PASS = 3.0
COMPLETE_PASS, COMPLETE_FAIL = "완결·통과", "완결·미통과"
LIMITED_PASS, LIMITED_FAIL = "제한적 참고 통과", "제한적·미통과"
NOT_SCORED = "산정 불가"
FATAL = {"010", "011", "012", "020", "800", "901"}  # 키·IP·한도·점검: 다른 종목도 실패하므로 전체 중단
MATERIALS = "소재"
UNVERIFIED = "검증 필요"

COMMON = ["revenue_growth", "gpm", "sga", "asset_turnover"]
FACTORS = COMMON + ["accruals"]
FACTOR_NAME = {"revenue_growth": "매출성장", "gpm": "GPM", "sga": "SGA", "asset_turnover": "총자산회전율",
               "accruals": "발생액"}

# key: (값의 성격, sj_div 우선순위, 표준 account_id, 회사 고유 계정일 때 의미를 확정할 수 있는 계정명)
#   flow       손익: 분기보고서 thstrm_amount = 당기 3개월, thstrm_add_amount = 누적
#   cumulative 현금흐름: 누적으로만 공시 → 분기 값은 차감으로
#   balance    재무상태: 기간 말 잔액
ACCOUNTS = {
    "revenue": ("flow", ("IS", "CIS"), "ifrs-full_Revenue", ("매출액", "수익(매출액)", "매출")),
    "gross_profit": ("flow", ("IS", "CIS"), "ifrs-full_GrossProfit", ("매출총이익", "매출총이익(손실)")),
    "sga": ("flow", ("IS", "CIS"), "dart_TotalSellingGeneralAdministrativeExpenses", ("판매비와관리비",)),
    "assets": ("balance", ("BS",), "ifrs-full_Assets", ("자산총계",)),
    "net_income": ("flow", ("IS", "CIS"), "ifrs-full_ProfitLoss",
                   ("당기순이익", "당기순이익(손실)", "분기순이익", "분기순이익(손실)", "반기순이익", "반기순이익(손실)")),
    "ocf": ("cumulative", ("CF",), "ifrs-full_CashFlowsFromUsedInOperatingActivities",
            ("영업활동현금흐름", "영업활동으로인한현금흐름")),
}
# 지정 표준 ID가 없을 때 쓰는 같은 개념의 다른 표준 ID (IFRS 핵심 택소노미의 판관비 요소). 사용 시 표 아래에 적는다.
EQUIVALENT_IDS = {"sga": ("ifrs-full_SellingGeneralAndAdministrativeExpense",)}
ACCOUNT_NAME = {"revenue": "매출", "gross_profit": "매출총이익", "sga": "판관비", "assets": "총자산",
                "net_income": "당기순이익", "ocf": "영업활동현금흐름"}
STANDARD_PREFIXES = ("ifrs-full_", "ifrs_", "dart_")
_KISU = re.compile(r"제\s*(\d+)\s*기")
_ENUM = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|[IVX]+\.|\d+\.|\(\d+\)|[가-하]\.)\s*")


def _norm(name):
    """'Ⅰ. 매출액' / '판매비와 관리비' → '매출액' / '판매비와관리비'."""
    return re.sub(r"\s+", "", _ENUM.sub("", name or ""))


def _amt(row, field):
    v = (row.get(field) or "").replace(",", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


# --- 분기 ---------------------------------------------------------------
def shift(fq, n):
    """(회계연도, 분기)를 n분기 이동."""
    i = fq[0] * 4 + fq[1] - 1 + n
    return i // 4, i % 4 + 1


def window(end):
    """end로 끝나는 4개 분기, 오래된 순."""
    return [shift(end, -k) for k in (3, 2, 1, 0)]


def qlabel(fq):
    return f"{fq[0]}.{fq[1]}Q"


def span(end):
    return f"{qlabel(shift(end, -3))}~{qlabel(end)}"


def required_reports(latest):
    """latest 분기 기준 계산에 필요한 정기보고서 [(회계연도, 분기)], 오래된 순.

    손익: 현재·전년 동기 TTM 8개 분기(4분기는 같은 해 3분기 누적도), 현금흐름: 현재 TTM 4개 분기와
    각 분기 직전 누적, 총자산: latest·1년 전·2년 전 기간 말.
    """
    cur, prior = window(latest), window(shift(latest, -4))
    need = set(cur) | set(prior) | {shift(latest, -8)}
    need |= {(fy, 3) for fy, q in cur + prior if q == 4}
    need |= {(fy, q - 1) for fy, q in cur if q > 1}
    return sorted(need)


def expected_latest(as_of):
    """12월 결산 법인이 as_of까지 공시를 마쳤을 최신 분기(법정 제출기한 기준 추정, 안내 문구용)."""
    y, md = as_of.year, (as_of.month, as_of.day)
    if md >= (11, 15):
        return y, 3
    if md >= (8, 15):
        return y, 2
    if md >= (5, 16):
        return y, 1
    if md >= (4, 1):
        return y - 1, 4
    return y - 1, 3


# --- 계정 식별 ------------------------------------------------------------
def find(rows, key):
    """-> (행, 고유 계정 메모 또는 None) / (None, 결측 이유).

    표준 account_id를 먼저 찾고, 없을 때만 표준 ID가 아닌 회사 고유 계정 중 계정명과
    재무제표 위치(sj_div)로 의미가 확정되는 행을 쓴다. 매출총이익·판관비를 다른 항목으로
    재구성하지 않는다.
    """
    _, sj_divs, std_id, names = ACCOUNTS[key]
    std_ids = {std_id, std_id.replace("ifrs-full_", "ifrs_")}  # 2019년 상반기 이전 공시는 ifrs_ 접두어
    for sj in sj_divs:
        hits = [r for r in rows if r.get("sj_div") == sj and r.get("account_id") in std_ids]
        if hits:
            return hits[0], None
    for alt in EQUIVALENT_IDS.get(key, ()):
        for sj in sj_divs:
            hits = [r for r in rows if r.get("sj_div") == sj and r.get("account_id") == alt]
            if hits:
                return hits[0], f'{ACCOUNT_NAME[key]}: 같은 개념의 IFRS 표준 ID {alt}("{hits[0].get("account_nm")}") 사용'
    wanted = {_norm(n) for n in names}
    named = [r for r in rows if r.get("sj_div") in sj_divs and _norm(r.get("account_nm")) in wanted]
    own = [r for r in named if not (r.get("account_id") or "").startswith(STANDARD_PREFIXES)]
    for sj in sj_divs:
        cands = [r for r in own if r["sj_div"] == sj]
        if len({r.get("thstrm_amount") for r in cands}) > 1:
            return None, f"{ACCOUNT_NAME[key]} 회사 고유 계정이 여러 개라 식별 불가"
        if cands:
            r = cands[0]
            return r, f'{ACCOUNT_NAME[key]}: 회사 고유 계정 "{r.get("account_nm")}"({sj}) 사용'
    if named:
        return None, (f'{ACCOUNT_NAME[key]} 표준 ID({std_id}) 없음 — 같은 이름의 다른 표준 계정 '
                      f'{named[0].get("account_id")}만 있어 의미 확정 불가')
    if key in ("gross_profit", "sga"):
        return None, f"{ACCOUNT_NAME[key]} 계정 없음(비용 성격별 분류 등)"
    return None, f"{ACCOUNT_NAME[key]} 계정 없음"


# --- 회사별 계산 ------------------------------------------------------------
def kisu(rows):
    """보고서 행의 당기명('제 57 기 3분기', '제 57 기')에서 기수. 없으면 None."""
    for r in rows or []:
        m = _KISU.search(r.get("thstrm_nm") or "")
        if m:
            return int(m.group(1))
    return None


class Company:
    """한 종목의 정기보고서 묶음. fs_div 하나(CFS 또는 OFS)로만 읽는다.

    분기는 (fy, q)로 다룬다. fy는 그 회계연도 1분기·반기·3분기 보고서의 bsns_year다. 사업보고서의
    bsns_year는 결산월이 12월이 아닌 회사에서 공시마다 다르게 붙어 있어, fy와 fy+1 중 1~3분기
    보고서와 기수(제 N 기)가 같은 것을 고른다. 기수로 같은 회계연도임을 확인할 수 없으면 쓰지 않는다.
    as_of가 오늘보다 이전이면 그 날짜 뒤에 접수된 보고서(rcept_no 앞 8자리)는 없는 것으로 본다.
    """

    def __init__(self, fetch, corp, fs_div, latest, acc_mt="12", as_of=None):
        self.fetch, self.corp, self.fs_div, self.latest = fetch, corp, fs_div, latest
        self.acc_mt = acc_mt
        self.december = acc_mt == "12"
        self.cutoff = as_of.strftime("%Y%m%d") if as_of and as_of < date.today() else None
        self.notes = set()     # 회사 고유 계정 사용 메모
        self.reports = {}      # 사용한 보고서 → 접수번호(rcept_no, DART가 주는 최신 정정본)
        self._raw, self._memo, self._why = {}, {}, {}

    def _fetch(self, bsns, q, fs_div=None):
        key = (bsns, q, fs_div or self.fs_div)
        if key not in self._raw:
            self._raw[key] = self.fetch(self.corp, bsns, REPORT_CODE[q], key[2])
        return self._raw[key]

    def year_kisu(self, fy):
        """회계연도 fy의 기수 (1분기·반기·3분기 보고서 중 먼저 확인되는 것)."""
        for q in (1, 2, 3):
            k = kisu(self._fetch(fy, q))
            if k is not None:
                return k
        return None

    def continuity(self, first, last):
        """회계연도 first~last가 끊김 없이 이어지는지(기수가 1씩 증가) -> 문제가 있으면 이유."""
        ks = [self.year_kisu(fy) for fy in range(first, last + 1)]
        if not self.december and None in ks:
            return "결산월이 12월이 아닌데 기수를 확인할 수 없어 회계분기 연속성 확인 불가"
        for fy, (a, b) in zip(range(first + 1, last + 1), zip(ks, ks[1:])):
            if a is not None and b is not None and b - a != 1:
                return f"제{a}기 → 제{b}기: 결산기 변경 등으로 회계분기가 이어지지 않아 TTM 구성 불가"
        return None

    def _missing(self, bsns, q):
        name = f"{bsns} {REPORT_NAME[q]}보고서"
        if self.fs_div == "CFS" and self._fetch(bsns, q, "OFS"):
            return f"{name} 연결재무제표 없음(별도만 공시 — 연결·별도를 섞지 않음)"
        return f"{name} 없음"

    def rows(self, fq):
        if fq in self._memo:
            return self._memo[fq]
        fy, q = fq
        rows, why = None, None
        if q < 4:
            rows = self._fetch(fy, q)
            if not rows:
                why = self._missing(fy, q)
        else:
            ref = self.year_kisu(fy)
            for bsns in ((fy,) if self.december else (fy, fy + 1)):
                cand = self._fetch(bsns, 4)
                if not cand:
                    continue
                k = kisu(cand)
                if ref is not None and k is not None:
                    if k == ref:
                        rows = cand
                        break
                    why = "사업보고서의 기수가 같은 해 분기보고서와 달라 회계연도 확인 불가"
                elif self.december:  # 12월 결산: bsns_year가 곧 회계연도
                    rows = cand
                    break
                else:
                    why = "사업보고서의 회계연도를 기수로 확인할 수 없음"
            if rows is None and why is None:
                why = self._missing(fy, 4)
        if rows and self.cutoff and (rows[0].get("rcept_no") or "")[:8] > self.cutoff:
            rows, why = None, f"{self.label(fq)} 보고서가 기준일 이후 접수됨(정정본 포함)"
        if rows:
            self.reports[self.label(fq)] = rows[0].get("rcept_no")
        else:
            rows = None
            self._why[fq] = why
        self._memo[fq] = rows
        return rows

    def label(self, fq):
        if self.december:
            return qlabel(fq)
        k = self.year_kisu(fq[0])
        return f"제{k}기 {fq[1]}Q" if k is not None else f"{fq[0]}.{fq[1]}Q"

    def span(self, end):
        return f"{self.label(shift(end, -3))}~{self.label(end)}"

    def _row(self, key, fq):
        rows = self.rows(fq)
        if not rows:
            return None, self._why[fq]
        row, memo = find(rows, key)
        if row is None:
            return None, f"{self.label(fq)} {memo}"
        if memo:
            self.notes.add(memo)
        return row, row.get("currency") or "KRW"

    @staticmethod
    def _amount(key, row, field):
        v = _amt(row, field)
        if v is not None and key == "sga":  # 판관비가 음수로 표시되면 절댓값 — 차감·합산 전에 일관되게
            v = abs(v)
        return v

    def _field(self, key, fq, field, what):
        row, info = self._row(key, fq)
        if row is None:
            return None, info, None
        v = self._amount(key, row, field)
        if v is None:
            return None, f"{self.label(fq)} {ACCOUNT_NAME[key]} {what} 없음", None
        return v, None, info

    def cumulative(self, key, fq):
        """회계연도 시작부터 fq 말까지 누적 -> (값, 결측 이유, 통화)."""
        kind = ACCOUNTS[key][0]
        if kind == "flow" and fq[1] in (2, 3):
            return self._field(key, fq, "thstrm_add_amount", "누적값")
        return self._field(key, fq, "thstrm_amount", "누적값" if fq[1] < 4 else "연간 값")

    def quarter(self, key, fq):
        """분기 단독 값 -> (값, 결측 이유, 통화)."""
        kind = ACCOUNTS[key][0]
        fy, q = fq
        if kind == "balance":
            return self._field(key, fq, "thstrm_amount", "기간 말 잔액")
        if kind == "flow" and q in (1, 2, 3):
            if q == 1:  # 1분기는 3개월 값 = 누적값
                v, why, ccy = self._field(key, fq, "thstrm_amount", "3개월 값")
                return (v, why, ccy) if v is not None else self._field(key, fq, "thstrm_add_amount", "3개월 값")
            row, info = self._row(key, fq)
            if row is None:
                return None, info, None
            three, cum = self._amount(key, row, "thstrm_amount"), self._amount(key, row, "thstrm_add_amount")
            if cum is None:  # 누적값이 없으면 thstrm_amount가 3개월인지 누적인지 구분할 수 없음
                return None, f"{self.label(fq)} {ACCOUNT_NAME[key]} 3개월·누적 구분 불가", None
            if three is not None:
                return three, None, info
        # 4분기 손익, 누락된 3개월 값, 현금흐름: 누적 차감
        cur, why, ccy = self.cumulative(key, fq)
        if cur is None:
            return None, why, None
        if q == 1:
            return cur, None, ccy
        prev, why, pccy = self.cumulative(key, (fy, q - 1))
        if prev is None:
            return None, why, None
        if pccy != ccy:
            return None, f"{self.label(fq)} {ACCOUNT_NAME[key]} 통화 단위 불일치", None
        return cur - prev, None, ccy

    def restatement(self, key, threshold=0.005):
        """최신 보고서의 전년 동기 비교값이 처음 공시한 값과 다르면 설명 문구(표시 방법 변경·중단영업 등).

        점수는 각 보고서의 당기 값으로 계산하고 바꾸지 않는다. 비교성 확인이 필요하다는 표시만 한다.
        """
        fy, q = self.latest
        row, _ = self._row(key, self.latest)
        if row is None:
            return None
        restated = self._amount(key, row, "frmtrm_amount" if q == 4 else "frmtrm_q_amount")
        original, _, _ = (self._field(key, (fy - 1, 4), "thstrm_amount", "연간 값") if q == 4
                          else self.quarter(key, (fy - 1, q)))
        if restated is None or not original or abs(restated / original - 1) <= threshold:
            return None
        prior = self.label((fy - 1, q))
        return (f"{ACCOUNT_NAME[key]} {prior} 값이 {self.label(self.latest)} 보고서에서 재작성됨"
                f"(처음 공시 {original / 1e8:,.0f}억 → {restated / 1e8:,.0f}억, {restated / original - 1:+.1%}) — "
                "표시 방법 변경·중단영업 재분류 등으로 TTM 비교성 확인 필요")

    def ttm(self, key, end):
        """end로 끝나는 4개 분기 합 -> (값, 결측 이유, 통화)."""
        vals, ccys = [], set()
        for fq in window(end):
            v, why, ccy = self.quarter(key, fq)
            if v is None:
                return None, why, None
            vals.append(v)
            ccys.add(ccy)
        if len(ccys) > 1:
            return None, f"{self.span(end)} {ACCOUNT_NAME[key]} 통화 단위 불일치", None
        return sum(vals), None, ccys.pop()


def _point(change, higher_is_better=True):
    if change is None:
        return None
    return int(change > 0) if higher_is_better else int(change < 0)


def compute(co):
    """-> (지표 dict, 팩터 점수 dict, 결측 이유 dict).

    통화는 창(현재·전년 동기 TTM) 안에서 같아야 하고, 두 창의 금액을 직접 비교하는 매출성장과
    총자산회전율은 두 창의 통화도 같아야 한다. GPM·판관비율은 한 창 안의 비율이라 창끼리는 무관.
    """
    cur, prior, prior2 = co.latest, shift(co.latest, -4), shift(co.latest, -8)
    m, why = {}, {}
    gap = co.continuity(prior2[0], cur[0])
    if gap:
        why = {f: gap for f in FACTORS}
        return m, {f: None for f in FACTORS}, why

    rev_c, r1, c_c = co.ttm("revenue", cur)
    rev_p, r2, c_p = co.ttm("revenue", prior)
    rev_reason = r1 or r2
    if rev_reason is None and (rev_c <= 0 or rev_p <= 0):
        rev_reason = "TTM 매출이 0 이하라 비율의 경제적 의미 확인 불가"
    m["rev_cur"], m["rev_prior"] = rev_c, rev_p
    cross = "현재·전년 동기 TTM 매출 통화 단위 불일치" if rev_reason is None and c_c != c_p else None

    # 1. 매출성장
    if rev_reason or cross:
        why["revenue_growth"] = rev_reason or cross
    else:
        m["revenue_growth"] = (rev_c / rev_p - 1) * 100

    # 2. GPM 개선 / 3. 판관비 효율 (판관비는 읽을 때 이미 절댓값)
    for key, factor, metric in (("gross_profit", "gpm", "gpm"), ("sga", "sga", "sga_ratio")):
        a_c, ra, ac = co.ttm(key, cur)
        a_p, rb, ap = co.ttm(key, prior)
        reason = rev_reason or ra or rb
        if reason is None and (ac != c_c or ap != c_p):
            reason = f"{ACCOUNT_NAME[key]}와 매출의 통화 단위 불일치"
        if reason:
            why[factor] = reason
            continue
        m[f"{metric}_cur"], m[f"{metric}_prior"] = a_c / rev_c * 100, a_p / rev_p * 100
        m[f"{metric}_change"] = m[f"{metric}_cur"] - m[f"{metric}_prior"]

    # 4. 총자산회전율 개선: 기간 말 총자산 세 시점
    pts = [co.quarter("assets", fq) for fq in (cur, prior, prior2)]
    bad = next((w for _, w, _ in pts if w), None)
    if bad is None and len({c for _, _, c in pts} | {c_c, c_p}) > 1:
        bad = "매출·총자산 통화 단위 불일치"
    if bad is None and any(v <= 0 for v, _, _ in pts):
        bad = "총자산이 0 이하"
    reason = rev_reason or bad
    if reason:
        why["asset_turnover"] = reason
    else:
        a0, a1, a2 = (v for v, _, _ in pts)
        m["assets"] = (a0, a1, a2)
        m["ato_cur"], m["ato_prior"] = rev_c / ((a0 + a1) / 2), rev_p / ((a1 + a2) / 2)
        m["ato_change"] = m["ato_cur"] - m["ato_prior"]

    # 5. 발생액 = TTM 당기순이익(연결 전체, ifrs-full_ProfitLoss) − TTM 영업활동현금흐름
    ni, ra, nc = co.ttm("net_income", cur)
    ocf, rb, oc = co.ttm("ocf", cur)
    if ra or rb:
        why["accruals"] = ra or rb
    elif nc != oc:
        why["accruals"] = "당기순이익과 영업활동현금흐름의 통화 단위 불일치"
    else:
        m["net_income"], m["ocf"], m["accruals"], m["accruals_currency"] = ni, ocf, ni - ocf, nc

    m["restated"] = [msg for key in ("revenue", "gross_profit", "sga") if (msg := co.restatement(key))]

    points = {
        "revenue_growth": _point(m.get("revenue_growth")),
        "gpm": _point(m.get("gpm_change")),
        "sga": _point(m.get("sga_ratio_change"), higher_is_better=False),
        "asset_turnover": _point(m.get("ato_change")),
        "accruals": _point(m.get("accruals"), higher_is_better=False),
    }
    return m, points, why


def judge(points, factors):
    """적용 팩터 목록으로 원점수·유효지표·정규화·상태·판정."""
    base = len(factors)
    valid = [points[f] for f in factors if points[f] is not None]
    n, raw = len(valid), sum(valid)
    if n == 0:
        return {"raw": 0, "valid": 0, "base": base, "norm": None, "status": NOT_SCORED, "verdict": NOT_SCORED}
    norm = raw / n * base
    if n == base:
        status, verdict = "완결", (COMPLETE_PASS if raw >= PASS else COMPLETE_FAIL)
    else:
        status, verdict = "제한적", (LIMITED_PASS if norm >= PASS else LIMITED_FAIL)
    return {"raw": raw, "valid": n, "base": base, "norm": norm, "status": status, "verdict": verdict}


def score(co, sector):
    """sector: WICS 대분류명 또는 None(확인 불가)."""
    m, points, why = compute(co)
    out = {"metrics": m, "points": points, "missing": why, "company_accounts": sorted(co.notes),
           "sector": sector or UNVERIFIED, "latest": co.latest,
           "period_cur": co.span(co.latest), "period_prior": co.span(shift(co.latest, -4)),
           "fs_div": co.fs_div, "fs_label": "연결" if co.fs_div == "CFS" else "별도 기준",
           "currency": m.get("accruals_currency"),
           "reports": dict(sorted(co.reports.items()))}
    if sector is None:  # 소재 여부를 모르면 두 경우를 함께 보여주고 완결로 단정하지 않음
        out.update(judge(points, COMMON))
        out["alt"] = {"소재 외": judge(points, COMMON), "소재": judge(points, FACTORS)}
        out["factors"] = COMMON
        out["status"], out["verdict"] = UNVERIFIED, f"{UNVERIFIED}(WICS 미확인)"
    else:
        out["factors"] = FACTORS if sector == MATERIALS else COMMON
        out.update(judge(points, out["factors"]))
    return out


# --- DART 수집 --------------------------------------------------------------
def write_atomic(fp, data):
    """임시 파일에 쓴 뒤 바꿔치기 — 중단·동시 실행에도 반쯤 쓰인 캐시가 남지 않게."""
    tmp = f"{fp}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, fp)


class DartData:
    """fnlttSinglAcntAll·corpCode·company 조회와 디스크 캐시.

    받은 자료만 data/cache/<날짜>/dart에 저장한다. '조회된 데이터 없음(013)'은 그날 늦게 공시될 수
    있으므로 디스크에 남기지 않고 실행 중에만 기억한다. refresh=True면 디스크 캐시를 읽지 않는다.
    """

    def __init__(self, client, cache_dir, refresh=False):
        self.client = client
        self.cache_dir = os.path.join(cache_dir, "dart")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.refresh = refresh
        self._none = set()

    def _cached(self, name, call):
        fp = os.path.join(self.cache_dir, name)
        if name in self._none:
            return None
        if os.path.exists(fp) and not self.refresh:
            try:
                with open(fp, encoding="utf-8") as f:
                    return json.load(f)
            except (ValueError, OSError):
                os.remove(fp)  # 깨진 캐시는 지우고 다시 받음
        for attempt in range(3):
            try:
                data = call()
                break
            except DartApiError as e:
                if e.status == NO_DATA:
                    data = None
                    break
                if e.status != NETWORK or attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        if data is None:
            self._none.add(name)
        else:
            write_atomic(fp, json.dumps(data, ensure_ascii=False).encode("utf-8"))
        return data

    def corp_list(self):
        """상장 종목(stock_code 있음) [{corp_code, corp_name, stock_code}]."""
        fp = os.path.join(self.cache_dir, "corpCode.xml")
        root = None
        if os.path.exists(fp) and not self.refresh:
            try:
                root = ET.parse(fp).getroot()
            except (ET.ParseError, OSError):
                os.remove(fp)
        if root is None:
            data = self.client.download_corp_codes()
            root = ET.fromstring(data)
            write_atomic(fp, data)
        out = []
        for el in root.iter("list"):
            stock = (el.findtext("stock_code") or "").strip()
            if stock:
                out.append({"corp_code": el.findtext("corp_code").strip(),
                            "corp_name": (el.findtext("corp_name") or "").strip(), "stock_code": stock})
        return out

    def statements(self, corp, fy, reprt, fs_div):
        return self._cached(f"{corp}_{fy}_{reprt}_{fs_div}.json",
                            lambda: self.client.financial_statements(corp, fy, reprt, fs_div).get("list") or None)

    def company(self, corp):
        return self._cached(f"{corp}_company.json", lambda: self.client.get_company(corp)) or {}

    def locate(self, corp, as_of, acc_mt="12", max_back=12):
        """가장 최근 정기보고서 분기와 재무제표 구분.

        분기마다 연결(CFS)을 먼저 찾고, 연결이 없을 때만 별도(OFS)를 쓴다. 최근 보고서에는
        별도만 있는데 직전 분기나 전년 동기에는 연결이 있었다면 연결·별도를 섞지 않도록 "MIXED".
        -> (fs_div, (회계연도, 분기)) 또는 None.
        """
        cos = {fs: Company(self.statements, corp, fs, None, acc_mt, as_of) for fs in ("CFS", "OFS")}
        fq = (as_of.year if acc_mt == "12" else as_of.year + 1, 4)
        for _ in range(max_back):
            if cos["CFS"].rows(fq):
                return "CFS", fq
            if cos["OFS"].rows(fq):
                had_cfs = any(cos["CFS"].rows(p) for p in (shift(fq, -1), shift(fq, -4)))
                return ("MIXED" if had_cfs else "OFS"), fq
            fq = shift(fq, -1)
        return None


def resolve(inputs, corps):
    """종목코드·종목명 입력 → ([{code, name, corp_code}], [{input, candidates}]).

    입력에 6자리 숫자가 있으면 종목코드를 우선하고, 종목명은 corpCode의 회사명과 정확히
    같을 때만 확정한다. 동명이거나 정확히 같은 이름이 없으면 후보를 돌려 사용자 확인을 받는다.
    """
    by_code = {c["stock_code"]: c for c in corps}
    found, ask = [], []
    for raw in inputs:
        m = re.search(r"(?<!\d)(\d{6})(?!\d)", raw)
        if m:
            c = by_code.get(m.group(1))
            if c:
                found.append({"code": c["stock_code"], "name": c["corp_name"], "corp_code": c["corp_code"]})
            else:
                ask.append({"input": raw, "candidates": [], "reason": "DART 상장 종목코드 목록에 없음"})
            continue
        key = _norm(raw)
        exact = [c for c in corps if _norm(c["corp_name"]) == key]
        if len(exact) == 1:
            c = exact[0]
            found.append({"code": c["stock_code"], "name": c["corp_name"], "corp_code": c["corp_code"]})
            continue
        cands = exact or [c for c in corps if key and key in _norm(c["corp_name"])][:10]
        ask.append({"input": raw, "candidates": [(c["corp_name"], c["stock_code"]) for c in cands],
                    "reason": "동명 회사가 여러 개" if exact else "정확히 일치하는 회사명이 없음"})
    seen, uniq = set(), []
    for f in found:
        if f["code"] not in seen:
            seen.add(f["code"])
            uniq.append(f)
    return uniq, ask


def evaluate(data, stocks, sectors, as_of, workers=4):
    """stocks: resolve() 결과. sectors: {종목코드: WICS 대분류명}. -> 결과 dict 목록(입력 순서).

    종목은 동시에 workers개씩 조회한다. 한 종목의 DART 오류는 그 종목만 '산정 불가'로 남긴다.
    키·IP·한도·점검 오류는 모든 종목에 해당하므로 DartApiError를 그대로 올린다.
    """
    def one(s):
        base = {"code": s["code"], "name": s["name"], "sector": sectors.get(s["code"]) or UNVERIFIED}
        try:
            return {**base, **_evaluate_one(data, s, sectors, as_of)}
        except DartApiError as e:
            if e.status in FATAL:
                raise
            return {**base, "error": f"DART 조회 실패({e.status}: {e.message})"}

    with ThreadPoolExecutor(max(1, workers)) as ex:
        return list(ex.map(one, stocks))


def _prefetch(data, corp, fs_div, latest, workers=4):
    """12월 결산 법인의 계산에 필요한 보고서를 미리 병렬로 받아 캐시에 둔다(값 계산은 Company가 함)."""
    fqs = required_reports(latest) + [(fy, 1) for fy in {fy for fy, q in required_reports(latest) if q == 4}]
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda fq: data.statements(corp, fq[0], REPORT_CODE[fq[1]], fs_div), sorted(set(fqs))))


def _evaluate_one(data, s, sectors, as_of):
    raw_mt = (data.company(s["corp_code"]) or {}).get("acc_mt")
    acc_mt = str(raw_mt).strip().zfill(2) if raw_mt else None  # 결산월(MM), 모르면 None
    loc = data.locate(s["corp_code"], as_of, acc_mt)
    if loc is None:
        return {"error": "최근 정기보고서 재무제표(fnlttSinglAcntAll)가 DART에 없음"}
    fs_div, latest = loc
    if fs_div == "MIXED":
        return {"error": f"{qlabel(latest)} 보고서에 연결재무제표가 없지만 이전 보고서는 연결 공시 — "
                         "연결·별도를 섞지 않으려고 산정 보류(검증 필요)"}
    if acc_mt == "12" and hasattr(data, "cache_dir"):
        _prefetch(data, s["corp_code"], fs_div, latest)
    co = Company(data.statements, s["corp_code"], fs_div, latest, acc_mt, as_of)
    return {**score(co, sectors.get(s["code"])), "acc_mt": acc_mt, "error": None}
