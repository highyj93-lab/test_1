"""Find NPS (국민연금공단) major-shareholding reports where the stake
increased and the resulting ownership ratio is >= 10%.

Approach:
  1. list.json (pblntf_ty=D) over the given window -> filter flr_nm == 국민연금공단.
  2. For each unique corp_code, majorstock.json -> match by rcept_no to get
     the exact stkrt (ownership %) and stkrt_irds (change vs. prior report).
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

KEY = "378622ae116bf1ce76547f386b09a80ddd3db6d6"
BASE = "https://opendart.fss.or.kr/api"


def fetch_npf_filings(bgn_de: str, end_de: str) -> list[dict]:
    items = []
    page = 1
    while True:
        r = requests.get(
            f"{BASE}/list.json",
            params={
                "crtfc_key": KEY,
                "pblntf_ty": "D",
                "bgn_de": bgn_de,
                "end_de": end_de,
                "page_no": page,
                "page_count": 100,
            },
            timeout=15,
        )
        d = r.json()
        if d["status"] != "000":
            break
        items.extend(d.get("list", []))
        if page >= d.get("total_page", 1):
            break
        page += 1
        time.sleep(0.1)
    return [i for i in items if "국민연금" in i.get("flr_nm", "")]


def fetch_majorstock(corp_code: str) -> list[dict]:
    r = requests.get(
        f"{BASE}/majorstock.json",
        params={"crtfc_key": KEY, "corp_code": corp_code},
        timeout=15,
    )
    d = r.json()
    if d["status"] != "000":
        return []
    return d.get("list", [])


def to_float(s: str) -> float:
    s = (s or "").replace(",", "").strip()
    if s in ("", "-"):
        return 0.0
    return float(s)


def main() -> None:
    filings = fetch_npf_filings("20260705", "20261003")
    by_corp: dict[str, list[dict]] = {}
    for f in filings:
        by_corp.setdefault(f["corp_code"], []).append(f)

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_majorstock, code): code for code in by_corp}
        for fut in as_completed(futs):
            code = futs[fut]
            try:
                records = fut.result()
            except Exception as e:
                print(f"error fetching {code}: {e}")
                continue
            for filing in by_corp[code]:
                match = next(
                    (r for r in records if r["rcept_no"] == filing["rcept_no"]), None
                )
                if not match:
                    continue
                stkrt = to_float(match.get("stkrt"))
                stkrt_irds = to_float(match.get("stkrt_irds"))
                if "국민연금" not in match.get("repror", ""):
                    continue
                if stkrt_irds > 0 and stkrt >= 10:
                    results.append(
                        {
                            "corp_name": filing["corp_name"],
                            "rcept_dt": filing["rcept_dt"],
                            "rcept_no": filing["rcept_no"],
                            "stkrt": stkrt,
                            "stkrt_irds": stkrt_irds,
                            "stkqy": match.get("stkqy"),
                            "stkqy_irds": match.get("stkqy_irds"),
                            "report_resn": match.get("report_resn"),
                        }
                    )

    results.sort(key=lambda x: x["rcept_dt"], reverse=True)
    print(f"조건에 맞는 사례: {len(results)}건\n")
    for r in results:
        print(
            f"[{r['rcept_dt']}] {r['corp_name']} - 보유비중 {r['stkrt']}% "
            f"(전보고대비 +{r['stkrt_irds']}%p), 보유주식수 {r['stkqy']} ({r['stkqy_irds']})"
        )
        print(f"  사유: {r['report_resn']}")
        print(f"  접수번호: {r['rcept_no']}")

    with open("/tmp/npf_increase_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
