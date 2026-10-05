"""Fetch valuation metrics (PER, forward PER, PBR, consensus target) from Naver mobile stock API."""
import json
import re
import sys
import time

import requests

TICKERS = {
    "GS건설": "006360", "DL이앤씨": "375500", "현대건설": "000720", "HDC현대산업개발": "294870",
    "코오롱인더": "120110", "DL": "000210", "대한유화": "006650", "효성티앤씨": "298020",
    "씨에스윈드": "112610", "효성중공업": "298040", "한화엔진": "082740",
    "아모레퍼시픽": "090430", "GS리테일": "007070", "한섬": "020000", "삼양식품": "003230",
    "한미약품": "128940", "대웅제약": "069620",
    "LIG디펜스앤에어로스페이스": "079550", "이수페타시스": "007660", "현대해상": "001450",
    "NHN": "181710", "롯데관광개발": "032350",
}


def num(s):
    if s is None:
        return None
    m = re.search(r"-?[\d,]+\.?\d*", str(s))
    return float(m.group().replace(",", "")) if m else None


def fetch(code: str) -> dict:
    d = requests.get(f"https://m.stock.naver.com/api/stock/{code}/integration", timeout=20).json()
    info = {x["code"]: x.get("value") for x in d.get("totalInfos", [])}
    cns = d.get("consensusInfo") or {}
    return {
        "price": num(info.get("lastClosePrice")),
        "per": num(info.get("per")),
        "fwd_per": num(info.get("cnsPer")),
        "eps": num(info.get("eps")),
        "fwd_eps": num(info.get("cnsEps")),
        "pbr": num(info.get("pbr")),
        "div_yield": num(info.get("dividendYieldRatio")),
        "target": num(cns.get("priceTargetMean")),
        "recomm": num(cns.get("recommMean")),
    }


def main(out_path: str) -> None:
    rows = {}
    for name, code in TICKERS.items():
        rows[name] = {"code": code, **fetch(code)}
        time.sleep(0.2)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"saved {len(rows)} rows -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "valuation.json")
