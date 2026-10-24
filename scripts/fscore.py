"""/fscore: 한국시장용 섹터별 4·5팩터 F 스코어 (Piotroski F 스코어와 별개 체계).

Usage:
    python scripts/fscore.py 005930 SK하이닉스 "POSCO홀딩스(005490)"
    python scripts/fscore.py 005490 --wics 005490=소재     # WICS 대분류 직접 지정

출력은 [1] 대화창용 Markdown 표와 [2] 엑셀용 탭 구분 텍스트. 재무 수치는 DART fnlttSinglAcntAll만 쓰고,
DART에 접근할 수 없으면 추정하지 않고 필요한 보고서·계정 목록을 출력한다.
종료 코드: 0 정상 · 3 일부 입력의 종목 확인 필요 · 4 DART 키·접속 문제로 산출 안 함(필요 자료 목록 출력)
· 5 입력 형식 오류 · 1 그 밖의 오류 (2는 argparse 사용법 오류)
"""
import argparse
import json
import os
import sys
from datetime import date

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dart_api import DartApiClient, DartApiError  # noqa: E402
from kospi_comp import fscore, wics  # noqa: E402
from kospi_comp import fscore_output as out  # noqa: E402

PROMPT = "COMP 80점 이상 후보의 종목코드 또는 종목명을 입력해주세요. 여러 종목을 한 번에 입력해도 됩니다."
OK, ASK, UNAVAILABLE, BAD_INPUT, ERROR = 0, 3, 4, 5, 1


def _reports_text(fqs, cumulative=False):
    suffix = " 누적" if cumulative else ""
    return ", ".join(f"{fy} {fscore.REPORT_NAME[q]}" + ("(연간)" if q == 4 else suffix) for fy, q in fqs)


def unavailable(reason, stocks, as_of):
    latest = fscore.expected_latest(as_of)
    cur_q, prior_q = fscore.window(latest), fscore.window(fscore.shift(latest, -4))
    cur, prior = fscore.span(latest), fscore.span(fscore.shift(latest, -4))
    cf_points = sorted({(fy, k) for fy, q in cur_q for k in (q - 1, q) if k >= 1})
    bs = ", ".join(f"{fscore.qlabel(fscore.shift(latest, -k))} 말" for k in (8, 4, 0))
    return "\n".join([
        f"{reason} F 스코어를 산출하지 않았습니다. 추정치나 다른 출처의 값으로 대체하지 않습니다.",
        f"대상: {', '.join(stocks)}",
        "필요한 자료 (DART 단일회사 전체 재무제표, 연결 기준 · 연결재무제표가 없는 회사만 별도, 정정공시는 최신 정정본):",
        f"- 정기보고서: {out.quarter_list(fscore.required_reports(latest))}",
        f"- 손익 분기 3개월 값·누적 값: 매출액, 매출총이익, 판매비와관리비 — 현재 TTM {cur}({_reports_text(cur_q)}), "
        f"전년 동기 TTM {prior}({_reports_text(prior_q)}); 4분기는 사업보고서 연간 값과 같은 해 3분기 누적 값",
        f"- 재무상태표 기간 말 자산총계: {bs}",
        f"- WICS 소재 종목만: 당기순이익(지배·비지배 합계) 현재 TTM {cur}, 영업활동현금흐름 누적 값 "
        f"{_reports_text(cf_points, cumulative=True)}",
        "- WICS 대분류(소재 여부)",
        f"(12월 결산·{as_of} 기준 최신 공시 분기 {fscore.qlabel(latest)}를 가정한 목록입니다. "
        "실제 최신 보고서나 결산월이 다르면 기간이 달라집니다.)",
    ])


def main(argv=None):
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stocks", nargs="*", help="종목코드 또는 종목명")
    ap.add_argument("--wics", action="append", default=[], metavar="CODE=대분류",
                    help="WICS 대분류를 직접 지정 (예: 005490=소재). 여러 번 쓸 수 있음")
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                    help="기준일 (기본: 오늘). 과거 날짜면 그 뒤에 접수된 보고서는 쓰지 않음")
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "cache", date.today().isoformat()))
    ap.add_argument("--refresh", action="store_true", help="오늘 받은 DART 캐시를 무시하고 다시 조회")
    ap.add_argument("--save", help="결과 JSON 저장 경로")
    args = ap.parse_args(argv)

    if not args.stocks:
        print(PROMPT)
        return OK
    try:
        overrides = wics.parse_overrides(args.wics)
    except ValueError as e:
        print(e)
        return BAD_INPUT
    key = os.environ.get("DART_API_KEY")
    if not key:
        print(unavailable("DART_API_KEY가 설정되지 않아", args.stocks, args.as_of))
        return UNAVAILABLE
    data = fscore.DartData(DartApiClient(key), args.cache, refresh=args.refresh)
    try:
        stocks, unresolved = fscore.resolve(args.stocks, data.corp_list())
        sectors, source = dict(overrides), "WICS 대분류 사용자 지정"
        need = [s["code"] for s in stocks if s["code"] not in overrides]
        if need:
            fetched, src = wics.fetch(args.as_of, os.path.join(args.cache, "wics"))
            sectors.update({c: fetched[c] for c in need if c in fetched})
            source = src + (" + 사용자 지정" if overrides else "")
        results = fscore.evaluate(data, stocks, sectors, args.as_of)
    except DartApiError as e:
        print(unavailable(f"DART 조회에 실패해({e.status}: {e.message})", args.stocks, args.as_of))
        return UNAVAILABLE

    print(out.render(results, source, unresolved))
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    return ASK if unresolved else OK


def run(argv=None):
    """예상하지 못한 오류도 한 줄로 알리고(키는 가림) 종료 코드 1."""
    try:
        return main(argv)
    except Exception as e:  # noqa: BLE001
        key = os.environ.get("DART_API_KEY")
        msg = f"{type(e).__name__}: {e}"
        print("오류로 F 스코어를 산출하지 않았습니다 — " + (msg.replace(key, "***") if key else msg))
        return ERROR


if __name__ == "__main__":
    sys.exit(run())
