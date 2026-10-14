"""Thin cached client for Naver's mobile stock API (m.stock.naver.com)."""
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "https://m.stock.naver.com/api"
PAGE = 60  # the price endpoint rejects pageSize > 60


def num(v):
    """Parse '1,234', '+9,285', '0.42%', '-' etc. into float (None if not numeric)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[-+]?[\d,]*\.?\d+", str(v))
    return float(m.group().replace(",", "")) if m else None


def hangeul_eok(v):
    """'6조 1,567억' / '88.1억' -> value in 억원."""
    if not v:
        return None
    total = 0.0
    jo = re.search(r"([\d,.]+)\s*조", v)
    eok = re.search(r"([\d,.]+)\s*억", v)
    if jo:
        total += float(jo.group(1).replace(",", "")) * 10000
    if eok:
        total += float(eok.group(1).replace(",", ""))
    return total if (jo or eok) else None


class Naver:
    def __init__(self, cache_dir, workers=12):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.session = requests.Session()
        self.workers = workers
        self.blocked = False  # 프록시가 접속을 막으면 이후 요청은 캐시만 사용
        self.misses = 0

    def get(self, path, **params):
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        fp = os.path.join(self.cache_dir, hashlib.md5(key.encode()).hexdigest() + ".json")
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as f:
                return json.load(f)
        if self.blocked:
            self.misses += 1
            return None
        for attempt in range(4):
            try:
                r = self.session.get(f"{BASE}/{path}", params=params, timeout=20)
                if r.status_code == 200:
                    data = r.json()
                    with open(fp, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False)
                    return data
                if r.status_code in (400, 404):
                    return None
            except requests.exceptions.ProxyError:
                self.blocked = True
                self.misses += 1
                return None
            except (requests.RequestException, ValueError):
                pass
            time.sleep(2 ** attempt)
        return None

    def pmap(self, fn, items):
        with ThreadPoolExecutor(self.workers) as ex:
            return list(ex.map(fn, items))

    # --- endpoints -------------------------------------------------------
    def prices(self, code, pages, index=False):
        """Daily OHLCV, oldest first. pages*60 trading days at most."""
        path = f"index/{code}/price" if index else f"stock/{code}/price"
        rows = []
        for p in range(1, pages + 1):
            chunk = self.get(path, pageSize=PAGE, page=p) or []
            rows += chunk
            if len(chunk) < PAGE:
                break
        out = {}
        for x in rows:
            out[x["localTradedAt"][:10]] = {
                "date": x["localTradedAt"][:10],
                "close": num(x["closePrice"]),
                "high": num(x.get("highPrice")),
                "volume": num(x.get("accumulatedTradingVolume")) or 0.0,
            }
        return [out[k] for k in sorted(out)]

    def trend(self, code, days=20):
        """Investor net-buy quantities per day (newest first)."""
        return self.get(f"stock/{code}/trend", pageSize=days) or []

    def integration(self, code):
        return self.get(f"stock/{code}/integration")

    def finance_annual(self, code):
        return self.get(f"stock/{code}/finance/annual")

    def finance_quarter(self, code):
        return self.get(f"stock/{code}/finance/quarter")

    def industries(self):
        return (self.get("stocks/industry", page=1, pageSize=100) or {}).get("groups", [])

    def industry_stocks(self, no):
        out, page = [], 1
        while True:
            d = self.get(f"stocks/industry/{no}", page=page, pageSize=100) or {}
            out += d.get("stocks", [])
            if page * 100 >= d.get("totalCount", 0):
                return out
            page += 1
