"""WICS(FnGuide/WISEindex) 대분류 조회.

WISEindex 섹터 지수 구성종목(GetIndexComponets)을 대분류 10개에 대해 받아 종목코드 → 대분류명을
만든다. KRX 업종이나 업종명으로 소재 여부를 추정하지 않으며, 조회에 실패하면 빈 결과를 돌려
해당 종목을 "검증 필요"로 남긴다.
"""
import glob
import json
import os
import time
from datetime import timedelta

import requests

from .fscore import write_atomic

URL = "https://www.wiseindex.com/Index/GetIndexComponets"  # 'Componets' 철자가 실제 경로
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36",
           "Referer": "https://www.wiseindex.com/", "X-Requested-With": "XMLHttpRequest",
           "Accept": "application/json"}
SECTORS = {"G10": "에너지", "G15": "소재", "G20": "산업재", "G25": "경기관련소비재", "G30": "필수소비재",
           "G35": "건강관리", "G40": "금융", "G45": "IT", "G50": "커뮤니케이션서비스", "G55": "유틸리티"}


def _components(session, day, code, retries=4):
    """대분류 지수 구성종목. 휴장일·미공표일은 빈 목록(info.CNT 0). 연결이 끊기면 간격을 늘려 재시도."""
    for attempt in range(retries):
        try:
            r = session.get(URL, params={"ceil_yn": 0, "dt": day.strftime("%Y%m%d"), "sec_cd": code},
                            headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            break
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    if not (data.get("info") or {}).get("CNT"):
        return []
    return data.get("list") or []


def fetch(as_of, cache_dir, max_back=14, session=None, pause=0.5):
    """-> ({종목코드: 대분류명}, 'WISEindex YYYY-MM-DD 구성종목') 또는 ({}, 실패 사유).

    구성종목은 며칠 늦게 공표되기도 하므로 as_of부터 하루씩 거슬러 올라가며 10개 대분류가
    모두 조회되는 가장 최근 날짜를 쓴다. 지수에 없는 종목(리츠·스팩 등)은 결과에 없다.
    """
    session = session or requests.Session()
    os.makedirs(cache_dir, exist_ok=True)
    for back in range(max_back):
        day = as_of - timedelta(days=back)
        fp = os.path.join(cache_dir, f"wics_{day:%Y%m%d}.json")
        if os.path.exists(fp):
            try:
                with open(fp, encoding="utf-8") as f:
                    return json.load(f), f"WISEindex {day:%Y-%m-%d} WICS 대분류 구성종목"
            except (ValueError, OSError):
                os.remove(fp)  # 쓰다 만 캐시는 지우고 다시 조회
        lists = {}
        try:
            for code in SECTORS:
                lists[code] = _components(session, day, code)
                if not lists[code]:  # 휴장일·미공표일
                    break
                time.sleep(pause)
        except (requests.RequestException, ValueError) as e:
            return _saved_snapshot(as_of, cache_dir, max_back, f"WISEindex 조회 실패({type(e).__name__})")
        if len(lists) < len(SECTORS) or not all(lists.values()):
            continue
        mapping = {}
        for code, rows in lists.items():
            for row in rows:
                stock = str(row.get("CMP_CD") or "").strip().zfill(6)
                sector = SECTORS.get(row.get("SEC_CD") or code)
                if stock.strip("0") and sector:
                    mapping.setdefault(stock, set()).add(sector)
        # 한 종목이 둘 이상의 대분류에 나오면 불명확 → 결과에서 뺀다(검증 필요)
        result = {k: next(iter(v)) for k, v in mapping.items() if len(v) == 1}
        write_atomic(fp, json.dumps(result, ensure_ascii=False).encode("utf-8"))
        return result, f"WISEindex {day:%Y-%m-%d} WICS 대분류 구성종목"
    return _saved_snapshot(as_of, cache_dir, max_back, f"WISEindex에서 최근 {max_back}일 안의 구성종목을 찾지 못함")


def _saved_snapshot(as_of, cache_dir, max_back, reason):
    """조회에 실패하면 다른 날짜 캐시(data/cache/*/wics)에 저장된 가장 최근 WICS 스냅샷(as_of 이전 max_back일 이내)을 쓴다.

    추정이 아니라 그 날짜의 WISEindex 공식 분류이며, 날짜를 출처 문구에 밝힌다. 없으면 ({}, reason).
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(cache_dir)))
    lo, hi = (as_of - timedelta(days=max_back)).strftime("%Y%m%d"), as_of.strftime("%Y%m%d")
    snaps = sorted(glob.glob(os.path.join(root, "*", "wics", "wics_????????.json")),
                   key=lambda f: os.path.basename(f)[5:13], reverse=True)
    for fp in snaps:
        day = os.path.basename(fp)[5:13]
        if lo <= day <= hi:
            try:
                with open(fp, encoding="utf-8") as f:
                    data = json.load(f)
            except (ValueError, OSError):
                continue
            if data:
                return data, f"WISEindex {day[:4]}-{day[4:6]}-{day[6:]} WICS 대분류 구성종목({reason} → 저장된 직전 스냅샷)"
    return {}, reason


def parse_overrides(items):
    """['005930=IT', '010130=소재'] → {'005930': 'IT', '010130': '소재'}. 대분류명만 허용."""
    out = {}
    for item in items or []:
        code, _, name = item.partition("=")
        code, name = code.strip(), name.strip()
        if len(code) != 6 or not code.isdigit() or name not in SECTORS.values():
            raise ValueError(f"--wics 형식 오류: {item!r} (예: 005930=IT, 대분류: {', '.join(SECTORS.values())})")
        out[code] = name
    return out
