"""/fscore 출력: 대화창용 Markdown 표 + 표 아래 설명 + 엑셀용 탭 구분 텍스트.

두 출력은 같은 cells()에서 만들어 값·판정·열 순서가 항상 같다.
"""
import pandas as pd

from .fscore import COMMON, FACTOR_NAME, MATERIALS, REPORT_NAME, UNVERIFIED

DASH = "—"
COLUMNS = ["종목", "섹터", "원점수/유효지표", "정규화", "팩터 점수", "판정",
           "매출성장 YoY", "GPM(%p)", "SGA Ratio(%p)", "총자산회전율(x)", "발생액"]
METRIC_FACTOR = [("revenue_growth", "revenue_growth", "{:+.1f}%"), ("gpm_change", "gpm", "{:+.2f}"),
                 ("sga_ratio_change", "sga", "{:+.2f}"), ("ato_change", "asset_turnover", "{:+.3f}")]


def _fmt(v, spec):
    return DASH if v is None else spec.format(v)


def _money(v, currency):
    """원 → 억원(1억 이상) / 만원 / 원, 외화는 백만 단위. 작은 금액도 부호가 보이게."""
    if v is None:
        return DASH
    if currency is None:
        return f"{v:+,.0f}(통화 미확인)"
    if currency != "KRW":
        return f"{v / 1e6:+,.1f}백만 {currency}"
    if abs(v) >= 1e8:
        return f"{v / 1e8:+,.0f}억"
    if abs(v) >= 1e4:
        return f"{v / 1e4:+,.0f}만원"
    return f"{v:+,.0f}원"


def cells(r):
    """결과 한 건 → COLUMNS 순서의 문자열 11개."""
    stock = f"{r['name']} ({r['code']})"
    factors = r.get("factors") or (COMMON + ["accruals"] if r["sector"] == MATERIALS else COMMON)
    if r.get("error"):
        return [stock, r["sector"], "0점/0개", DASH, "·".join(DASH for _ in factors), "산정 불가"] + [DASH] * 5
    m, p = r["metrics"], r["points"]
    digits = "·".join(DASH if p[f] is None else str(p[f]) for f in factors)
    norm = DASH if r["norm"] is None else f"{r['norm']:.2f}"
    metrics = [_fmt(m.get(k), spec) for k, _, spec in METRIC_FACTOR]
    if r["sector"] == MATERIALS:
        accruals = _money(m.get("accruals"), m.get("accruals_currency"))
    elif r["sector"] == UNVERIFIED:
        accruals = UNVERIFIED
    else:
        accruals = DASH  # 소재 외: 미적용
    return [stock, r["sector"], f"{r['raw']}점/{r['valid']}개", norm, digits, r["verdict"]] + metrics + [accruals]


def basis_line(results):
    """표 앞 한 줄: 비교 기준 TTM 기간과 재무제표 구분."""
    groups = {}
    for r in results:
        if r.get("error"):
            continue
        mt = r.get("acc_mt")
        fiscal = "" if mt == "12" else (f", 회계분기·결산 {int(mt)}월" if mt else ", 결산월 미확인·기수 기준")
        key = f"현재 TTM {r['period_cur']} vs 전년 동기 TTM {r['period_prior']} · {r['fs_label']}{fiscal}"
        groups.setdefault(key, []).append(r["name"])
    if not groups:
        return "비교 기준: 산정 가능한 종목 없음"
    if len(groups) == 1:
        return "비교 기준: " + next(iter(groups))
    return "비교 기준: " + " / ".join(f"{k} ({', '.join(v)})" for k, v in groups.items())


def stock_note(r):
    """종목 한 건의 설명: 결측 이유, 회사 고유 계정, 별도 기준, 섹터 미확인 시 두 경우의 판정."""
    if r.get("error"):
        return f"산정 불가 — {r['error']}"
    items = []
    if r["fs_div"] == "OFS":
        items.append("연결재무제표가 없어 별도 기준")
    for f in r["factors"]:
        if r["points"][f] is None:
            items.append(f"{FACTOR_NAME[f]} 결측 — {r['missing'].get(f, '값 없음')}")
    if r["company_accounts"]:
        items.append("계정 식별: " + "; ".join(r["company_accounts"]))
    for msg in r["metrics"].get("restated", []):
        items.append("비교성 확인 필요: " + msg)
    if r["sector"] == UNVERIFIED:
        a, b = r["alt"]["소재 외"], r["alt"]["소재"]
        acc = r["metrics"].get("accruals")
        items.append(f"WICS 대분류 미확인으로 완결 판정 보류 — 소재 외라면 {a['raw']}점/{a['valid']}개 {a['verdict']}, "
                     f"소재라면 {b['raw']}점/{b['valid']}개 {b['verdict']}"
                     + (f" (발생액 {_money(acc, r['metrics'].get('accruals_currency'))})"
                        if acc is not None else ""))
    return " / ".join(items)


def notes(results, wics_source):
    """표 아래 설명 줄 목록."""
    out = [f"{r['name']} ({r['code']}): {n}" for r in results if (n := stock_note(r))]
    out.append(f"섹터: {wics_source}")
    out.append("재무 수치: DART fnlttSinglAcntAll이 제공하는 보고서(정정공시가 있으면 DART가 주는 최신 정정본) 기준.")
    out.append("판정은 반올림 전 원값 기준, 통과 기준 3.0. 결측은 0점이 아니라 '—'이며 원점수·정규화에서 제외. "
               "팩터 점수 순서: 매출성장·GPM·SGA·총자산회전율(소재는 ·발생액). Piotroski F 스코어와 별개 체계.")
    return out


FRAME_COLUMNS = {"섹터": "f_sector", "원점수/유효지표": "f_score", "정규화": "f_norm", "팩터 점수": "f_digits",
                 "판정": "f_verdict", "매출성장 YoY": "f_rev", "GPM(%p)": "f_gpm", "SGA Ratio(%p)": "f_sga",
                 "총자산회전율(x)": "f_ato", "발생액": "f_accruals"}


def frame(results):
    """파이프라인용: 종목코드 index, 표와 같은 셀 문자열(열 제목으로 매핑) + 비교 기준 + 설명."""
    rows = []
    for r in results:
        c = dict(zip(COLUMNS, cells(r)))
        basis = "" if r.get("error") else f"{r['period_cur']} vs {r['period_prior']} · {r['fs_label']}"
        rows.append({"code": r["code"], **{v: c[k] for k, v in FRAME_COLUMNS.items()},
                     "f_basis": basis, "f_note": stock_note(r)})
    cols = ["code", *FRAME_COLUMNS.values(), "f_basis", "f_note"]
    return pd.DataFrame(rows, columns=cols).set_index("code")


def markdown(results, wics_source):
    rows = [cells(r) for r in results]
    lines = [basis_line(results), "", "| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    lines += ["| " + " | ".join(c) + " |" for c in rows]
    lines += [""] + [f"- {n}" for n in notes(results, wics_source)]
    return "\n".join(lines)


def tsv(results):
    rows = [COLUMNS] + [cells(r) for r in results]
    return "\n".join("\t".join(c) for c in rows)


def render(results, wics_source, unresolved=()):
    """[1] Markdown 표 → [2] 엑셀용 탭 구분 텍스트. 확인이 필요한 입력은 맨 앞에."""
    parts = []
    if unresolved:
        parts.append("**종목 확인 필요** — 임의로 고르지 않았습니다.")
        for u in unresolved:
            cands = ", ".join(f"{n} ({c})" for n, c in u["candidates"]) or "후보 없음"
            parts.append(f"- \"{u['input']}\": {u['reason']} → {cands}")
        parts.append("")
    if results:
        parts += ["[1] 대화창용 표", "", markdown(results, wics_source), "",
                  "[2] 엑셀용 탭 구분 텍스트", "", "```", tsv(results), "```"]
    return "\n".join(parts)


def quarter_list(fqs):
    """[(2025, 3), ...] → '2025 3분기·사업보고서 …' 같은 요청 문구용."""
    by_year = {}
    for fy, q in fqs:
        by_year.setdefault(fy, []).append(REPORT_NAME[q] + ("보고서" if q == 4 else ""))
    return ", ".join(f"{fy} {'·'.join(v)}" for fy, v in sorted(by_year.items()))

