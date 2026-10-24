"""섹터별 4·5팩터 F 스코어 단위 테스트 (가짜 DART 응답, 네트워크 없음).

    python -m unittest discover -s tests
"""
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from dart_api import DartApiClient, DartApiError  # noqa: E402
from kospi_comp import fscore, fscore_output  # noqa: E402
from kospi_comp.fscore import REPORT_CODE, Company, DartData, judge, resolve, score  # noqa: E402

CODE_Q = {v: k for k, v in REPORT_CODE.items()}
Q = [(2024, 1), (2024, 2), (2024, 3), (2024, 4), (2025, 1), (2025, 2),
     (2025, 3), (2025, 4), (2026, 1), (2026, 2)]
# 분기 단독 값 (총자산은 기간 말 잔액)
BASE = {
    "revenue": [100, 110, 120, 130, 125, 135, 150, 160, 155, 170],
    "gross_profit": [30, 33, 36, 39, 37, 40, 48, 51, 50, 54],
    "sga": [20] * 10,
    "net_income": [10] * 10,
    "ocf": [15] * 10,
    "assets": [950, 1000, 1020, 1050, 1080, 1100, 1200, 1300, 1500, 1600],
}
IDS = {
    "revenue": ("ifrs-full_Revenue", "매출액", "IS"),
    "gross_profit": ("ifrs-full_GrossProfit", "매출총이익", "IS"),
    "sga": ("dart_TotalSellingGeneralAdministrativeExpenses", "판매비와관리비", "IS"),
    "net_income": ("ifrs-full_ProfitLoss", "당기순이익", "IS"),
    "ocf": ("ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", "CF"),
    "assets": ("ifrs-full_Assets", "자산총계", "BS"),
}


def row(sj, aid, nm, **amounts):
    return {"sj_div": sj, "account_id": aid, "account_nm": nm, "currency": "KRW",
            **{k: f"{v:,}" for k, v in amounts.items()}}


def report_rows(data, fy, q, ids=IDS, kisu=None):
    """DART 형식: 분기보고서 손익 thstrm=3개월·add=누적, 현금흐름 thstrm=누적, 사업보고서 thstrm=연간."""
    rows = _rows(data, fy, q, ids)
    if kisu:
        for r in rows:
            r["thstrm_nm"] = f"제 {kisu(fy)} 기" + ("" if q == 4 else f" {('1분기', '반기', '3분기')[q - 1]}")
    return rows


def _rows(data, fy, q, ids):
    rows = []
    for key, vals in data.items():
        aid, nm, sj = ids[key]
        cum = sum(vals[(fy, k)] for k in range(1, q + 1)) if key != "assets" else None
        if key == "assets":
            rows.append(row(sj, aid, nm, thstrm_amount=vals[(fy, q)]))
        elif key == "ocf" or q == 4:
            rows.append(row(sj, aid, nm, thstrm_amount=cum))
        else:
            rows.append(row(sj, aid, nm, thstrm_amount=vals[(fy, q)], thstrm_add_amount=cum))
    return rows


def dataset(**changes):
    data = {k: dict(zip(Q, v)) for k, v in BASE.items()}
    for k, v in changes.items():
        if v is None:
            data.pop(k)
        else:
            data[k] = dict(zip(Q, v))
    return data


def fetcher(reports):
    """reports: {(fy, q, fs_div): rows}"""
    def fetch(corp, fy, reprt, fs_div):
        return reports.get((fy, CODE_Q[reprt], fs_div))
    return fetch


def all_reports(data=None, fs_div="CFS", ids=IDS, skip=(), annual_bsns_offset=0, kisu=None):
    """annual_bsns_offset=1: 결산월이 12월이 아닌 회사처럼 사업보고서만 bsns_year가 회계연도+1."""
    data = data or dataset()
    return {(fy + (annual_bsns_offset if q == 4 else 0), q, fs_div): report_rows(data, fy, q, ids, kisu)
            for fy, q in Q if (fy, q) not in skip}


def run(sector="IT", reports=None, latest=(2026, 2), fs_div="CFS", acc_mt="12"):
    co = Company(fetcher(reports or all_reports()), "00000001", fs_div, latest, acc_mt)
    return score(co, sector)


def KISU(fy):
    return fy - 1968


class TTMAndFactors(unittest.TestCase):
    def test_full_non_materials(self):
        r = run("IT")
        m = r["metrics"]
        self.assertEqual((m["rev_cur"], m["rev_prior"]), (635, 510))  # 25.3Q~26.2Q / 24.3Q~25.2Q, 4Q = 연간 − 3Q 누적
        self.assertAlmostEqual(m["revenue_growth"], (635 / 510 - 1) * 100)
        self.assertAlmostEqual(m["gpm_change"], 203 / 635 * 100 - 152 / 510 * 100)
        self.assertAlmostEqual(m["sga_ratio_change"], 80 / 635 * 100 - 80 / 510 * 100)
        self.assertAlmostEqual(m["ato_cur"], 635 / ((1600 + 1100) / 2))
        self.assertAlmostEqual(m["ato_prior"], 510 / ((1100 + 1000) / 2))
        self.assertEqual([r["points"][f] for f in fscore.COMMON], [1, 1, 1, 0])
        self.assertEqual((r["raw"], r["valid"], r["base"], r["status"], r["verdict"]), (3, 4, 4, "완결", "완결·통과"))
        self.assertEqual((r["period_cur"], r["period_prior"]), ("2025.3Q~2026.2Q", "2024.3Q~2025.2Q"))

    def test_materials_adds_accruals_from_cumulative_cash_flow(self):
        r = run("소재")
        self.assertEqual(r["metrics"]["ocf"], 60)  # 현금흐름 분기 값 = 누적 차감
        self.assertEqual(r["metrics"]["accruals"], 40 - 60)
        self.assertEqual(r["points"]["accruals"], 1)
        self.assertEqual((r["raw"], r["valid"], r["base"], r["verdict"]), (4, 5, 5, "완결·통과"))

    def test_accruals_not_applied_outside_materials(self):
        r = run("IT")
        self.assertNotIn("accruals", r["factors"])
        self.assertEqual(fscore_output.cells({**r, "code": "000001", "name": "A"})[10], "—")

    def test_missing_gross_profit_is_not_reconstructed(self):
        reports = all_reports(dataset(gross_profit=None))
        for rows in reports.values():  # 매출원가가 있어도 매출총이익을 만들지 않음
            rows.append(row("IS", "ifrs-full_CostOfSales", "매출원가", thstrm_amount=50, thstrm_add_amount=50))
        r = run("IT", reports)
        self.assertIsNone(r["points"]["gpm"])
        self.assertIn("매출총이익 계정 없음", r["missing"]["gpm"])
        self.assertEqual((r["raw"], r["valid"], r["status"]), (2, 3, "제한적"))
        self.assertAlmostEqual(r["norm"], 2 / 3 * 4)
        self.assertEqual(r["verdict"], "제한적·미통과")

    def test_missing_quarter_nulls_only_dependent_factors(self):
        r = run("소재", all_reports(skip={(2024, 3)}))  # 전년 동기 TTM의 한 분기 보고서 없음
        for f in fscore.COMMON:
            self.assertIsNone(r["points"][f], f)
        self.assertEqual(r["points"]["accruals"], 1)  # 현재 TTM만 쓰는 발생액은 계속 계산
        self.assertEqual((r["raw"], r["valid"]), (1, 1))
        self.assertAlmostEqual(r["norm"], 5.0)
        self.assertEqual(r["verdict"], "제한적 참고 통과")
        self.assertIn("2024 3분기보고서 없음", r["missing"]["revenue_growth"])

    def test_q4_requires_q3_cumulative(self):
        reports = all_reports()
        for r_ in reports[(2025, 3, "CFS")]:
            if r_["account_id"] == "ifrs-full_Revenue":
                r_.pop("thstrm_add_amount")
        r = run("IT", reports)
        self.assertIsNone(r["points"]["revenue_growth"])
        self.assertIn("3개월·누적 구분 불가", r["missing"]["revenue_growth"])

    def test_three_month_value_derived_from_cumulative_when_missing(self):
        reports = all_reports()
        for r_ in reports[(2026, 2, "CFS")]:
            if r_["account_id"] == "ifrs-full_Revenue":
                r_["thstrm_amount"] = ""
        r = run("IT", reports)
        self.assertEqual(r["metrics"]["rev_cur"], 635)  # 반기 누적 325 − 1분기 155 = 170

    def test_q1_falls_back_to_cumulative(self):
        reports = all_reports()
        for r_ in reports[(2026, 1, "CFS")]:
            if r_["account_id"] == "ifrs-full_Revenue":
                r_["thstrm_amount"] = ""
        self.assertEqual(run("IT", reports)["metrics"]["rev_cur"], 635)

    def test_negative_sga_uses_absolute_value(self):
        r = run("IT", all_reports(dataset(sga=[-20] * 10)))
        self.assertAlmostEqual(r["metrics"]["sga_ratio_cur"], 80 / 635 * 100)
        self.assertEqual(r["points"]["sga"], 1)

    def test_company_specific_account_is_used_and_noted(self):
        ids = {**IDS, "revenue": ("-표준계정코드 미사용-", "Ⅰ. 매출액", "IS")}
        r = run("IT", all_reports(ids=ids))
        self.assertEqual(r["metrics"]["rev_cur"], 635)
        self.assertTrue(any("회사 고유 계정" in n and "매출액" in n for n in r["company_accounts"]))

    def test_restated_comparative_is_flagged_not_rescored(self):
        reports = all_reports()
        for r_ in reports[(2026, 2, "CFS")]:
            if r_["account_id"] == "ifrs-full_Revenue":
                r_["frmtrm_q_amount"] = "145"  # 2025.2Q 처음 공시 135 → 재작성 145
        r = run("IT", reports)
        self.assertEqual(r["metrics"]["rev_cur"], 635)  # 점수는 각 보고서 당기 값 그대로
        self.assertEqual(len(r["metrics"]["restated"]), 1)
        self.assertIn("2025.2Q 값이 2026.2Q 보고서에서 재작성됨", r["metrics"]["restated"][0])
        note = fscore_output.stock_note({**r, "code": "000001", "name": "A"})
        self.assertIn("비교성 확인 필요: 매출", note)
        unchanged = all_reports()
        for r_ in unchanged[(2026, 2, "CFS")]:
            if r_["account_id"] == "ifrs-full_Revenue":
                r_["frmtrm_q_amount"] = "135"
        self.assertEqual(run("IT", unchanged)["metrics"]["restated"], [])

    def test_ifrs_sga_element_is_equivalent_and_noted(self):
        # 실제 공시(세방전지 2025, 한국가스공사 2025 반기)처럼 보고서마다 판관비 ID가 바뀌는 경우
        reports = all_reports()
        for (fy, q, _), rows in reports.items():
            if fy == 2025:
                for r_ in rows:
                    if r_["account_id"] == "dart_TotalSellingGeneralAdministrativeExpenses":
                        r_["account_id"], r_["account_nm"] = "ifrs-full_SellingGeneralAndAdministrativeExpense", "판매 및 일반관리비"
        r = run("IT", reports)
        self.assertEqual(r["points"]["sga"], 1)
        self.assertAlmostEqual(r["metrics"]["sga_ratio_change"], run("IT")["metrics"]["sga_ratio_change"])
        self.assertTrue(any("ifrs-full_SellingGeneralAndAdministrativeExpense" in n for n in r["company_accounts"]))

    def test_consolidated_net_income_company_account(self):
        # 실제 공시(삼영 2025 분기·반기): ifrs-full_ProfitLoss 대신 회사 고유 계정 '연결당기순이익'
        reports = all_reports()
        for (fy, q, _), rows in reports.items():
            if fy == 2025 and q < 4:
                for r_ in rows:
                    if r_["account_id"] == "ifrs-full_ProfitLoss":
                        r_["account_id"], r_["account_nm"] = "-표준계정코드 미사용-", "연결당기순이익"
                        rows.append({**r_, "account_nm": "연결계속 당기순이익"})  # 같은 값의 계속영업 행
                        break
        r = run("소재", reports)
        self.assertEqual(r["metrics"]["accruals"], 40 - 60)
        self.assertTrue(any("연결당기순이익" in n for n in r["company_accounts"]))
        only_continuing = all_reports()
        for (fy, q, _), rows in only_continuing.items():
            if fy == 2025 and q < 4:
                for r_ in rows:
                    if r_["account_id"] == "ifrs-full_ProfitLoss":
                        r_["account_id"], r_["account_nm"] = "-표준계정코드 미사용-", "연결계속 당기순이익"
        self.assertIsNone(run("소재", only_continuing)["points"]["accruals"])

    def test_other_standard_id_with_same_name_is_null(self):
        ids = {**IDS, "revenue": ("ifrs-full_RevenueFromSaleOfGoods", "매출액", "IS")}
        r = run("IT", all_reports(ids=ids))
        self.assertIsNone(r["points"]["revenue_growth"])
        self.assertIn("의미 확정 불가", r["missing"]["revenue_growth"])

    def test_currency_mismatch_is_null(self):
        reports = all_reports()
        for r_ in reports[(2026, 1, "CFS")]:
            r_["currency"] = "USD"
        r = run("IT", reports)
        self.assertIsNone(r["points"]["revenue_growth"])
        self.assertIn("통화 단위 불일치", r["missing"]["revenue_growth"])

    def test_zero_revenue_is_null_not_zero(self):
        r = run("IT", all_reports(dataset(revenue=[0] * 10)))
        self.assertIsNone(r["points"]["revenue_growth"])
        self.assertEqual(r["verdict"], "산정 불가")

    def test_unknown_sector_is_never_complete(self):
        r = run(None)
        self.assertEqual((r["sector"], r["status"]), ("검증 필요", "검증 필요"))
        self.assertEqual(r["alt"]["소재 외"]["verdict"], "완결·통과")
        self.assertEqual(r["alt"]["소재"]["verdict"], "완결·통과")
        self.assertNotIn("완결", r["verdict"])


class ReviewRegressions(unittest.TestCase):
    """적대적 리뷰에서 확인된 결함의 회귀 테스트."""

    def test_currency_switch_between_windows_nulls_cross_window_factors(self):
        reports = all_reports()
        for (fy, q, _), rows in reports.items():
            if fy == 2025:  # 2025 회계연도부터 USD 공시
                for r_ in rows:
                    r_["currency"] = "USD"
        r = run("소재", reports, latest=(2025, 4))
        self.assertIsNone(r["points"]["revenue_growth"])
        self.assertIn("통화 단위 불일치", r["missing"]["revenue_growth"])
        self.assertIsNone(r["points"]["asset_turnover"])
        self.assertIsNotNone(r["points"]["gpm"])  # 한 창 안의 비율은 계산
        self.assertEqual(r["metrics"]["accruals_currency"], "USD")

    def test_sga_sign_differs_between_reports(self):
        reports = all_reports()
        for (fy, q, _), rows in reports.items():
            for r_ in rows:
                if r_["account_id"].endswith("SellingGeneralAdministrativeExpenses") and q < 4:
                    for f in ("thstrm_amount", "thstrm_add_amount"):
                        r_[f] = "-" + r_[f]
        self.assertAlmostEqual(run("IT", reports)["metrics"]["sga_ratio_change"],
                               run("IT")["metrics"]["sga_ratio_change"])

    def test_fiscal_year_gap_is_never_spliced(self):
        kisu = {2024: 56, 2025: 58, 2026: 59}.get  # 결산기 변경으로 제57기(단기)가 끼어 있음
        r = run("IT", all_reports(kisu=kisu), acc_mt="12")
        self.assertTrue(all(p is None for p in r["points"].values()))
        self.assertIn("이어지지 않아", r["missing"]["revenue_growth"])
        self.assertEqual(r["verdict"], "산정 불가")

    def test_as_of_excludes_reports_filed_later(self):
        reports = all_reports()
        filed = {1: "0512", 2: "0812", 3: "1112", 4: "0315"}
        for (fy, q, _), rows in reports.items():
            for r_ in rows:
                r_["rcept_no"] = f"{fy + (q == 4)}{filed[q]}000001"
        d = DartData.__new__(DartData)
        d.statements = fetcher(reports)
        self.assertEqual(d.locate("x", date(2026, 8, 1)), ("CFS", (2026, 1)))
        self.assertEqual(d.locate("x", date.today()), ("CFS", (2026, 2)))

    def test_cfs_missing_but_ofs_present_is_explained(self):
        reports = all_reports(skip={(2024, 3)})
        reports[(2024, 3, "OFS")] = report_rows(dataset(), 2024, 3)
        r = run("IT", reports)
        self.assertIn("연결재무제표 없음(별도만 공시", r["missing"]["revenue_growth"])

    def test_corpcode_error_body_becomes_dart_error(self):
        client = DartApiClient("K")
        resp = mock.Mock(content="<result><status>010</status><message>등록되지 않은 키</message></result>".encode())
        resp.raise_for_status = lambda: None
        with mock.patch.object(client.session, "get", return_value=resp):
            with self.assertRaises(DartApiError) as ctx:
                client.download_corp_codes()
        self.assertEqual(ctx.exception.status, "010")

    def test_no_data_is_not_persisted_and_broken_cache_is_refetched(self):
        import tempfile
        calls = []

        class Client:
            def financial_statements(self, corp, fy, reprt, fs_div):
                calls.append(fy)
                if fy == 2026:
                    raise DartApiError("013", "조회된 데이타가 없습니다")
                return {"list": [{"x": 1}]}

        tmp = tempfile.mkdtemp()
        d = DartData(Client(), tmp)
        self.assertIsNone(d.statements("c", 2026, "11014", "CFS"))
        self.assertEqual(d.statements("c", 2025, "11014", "CFS"), [{"x": 1}])
        self.assertEqual(sorted(os.listdir(os.path.join(tmp, "dart"))), ["c_2025_11014_CFS.json"])
        with open(os.path.join(tmp, "dart", "c_2025_11014_CFS.json"), "w") as f:
            f.write('[{"x": 1')  # 쓰다 만 캐시
        self.assertEqual(DartData(Client(), tmp).statements("c", 2025, "11014", "CFS"), [{"x": 1}])
        self.assertEqual(calls, [2026, 2025, 2025])

    def test_one_stock_failure_does_not_drop_others(self):
        good = all_reports()

        class Data:
            def company(self, corp):
                return {"acc_mt": "12"}

            def statements(self, corp, fy, reprt, fs_div):
                if corp == "BAD":
                    raise DartApiError("100", "필드의 부적절한 값")
                return fetcher(good)(corp, fy, reprt, fs_div)

            locate = DartData.locate

        stocks = [{"code": "000010", "name": "A", "corp_code": "OK"},
                  {"code": "000020", "name": "B", "corp_code": "BAD"}]
        res = fscore.evaluate(Data(), stocks, {"000010": "IT"}, date(2026, 10, 17))
        self.assertEqual(res[0]["verdict"], "완결·통과")
        self.assertIn("DART 조회 실패(100", res[1]["error"])

        class Fatal(Data):
            def statements(self, corp, fy, reprt, fs_div):
                raise DartApiError("020", "요청 제한 초과")

        with self.assertRaises(DartApiError):
            fscore.evaluate(Fatal(), stocks, {}, date(2026, 10, 17))


class Wics(unittest.TestCase):
    def test_probe_back_padding_ambiguity_and_broken_cache(self):
        import tempfile
        from kospi_comp import wics

        class Resp:
            def __init__(self, data):
                self.data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self.data

        class Session:
            def get(self, url, params, headers, timeout):
                if params["dt"] > "20261016":  # 토요일·미공표
                    return Resp({"info": {"CNT": 0}, "list": []})
                rows = {"G15": [{"CMP_CD": "5490", "SEC_CD": "G15"}], "G45": [{"CMP_CD": "005930", "SEC_CD": "G45"}],
                        "G20": [{"CMP_CD": "111110", "SEC_CD": "G20"}],
                        "G25": [{"CMP_CD": "111110", "SEC_CD": "G25"}]}.get(
                    params["sec_cd"], [{"CMP_CD": "999990", "SEC_CD": params["sec_cd"]}])
                return Resp({"info": {"CNT": len(rows)}, "list": rows})

        tmp = tempfile.mkdtemp()
        m, src = wics.fetch(date(2026, 10, 17), tmp, session=Session(), pause=0)
        self.assertEqual((m["005490"], m["005930"]), ("소재", "IT"))
        self.assertNotIn("111110", m)  # 두 대분류에 나오면 불명확 → 검증 필요
        self.assertIn("2026-10-16", src)
        with open(os.path.join(tmp, "wics_20261017.json"), "w") as f:
            f.write('{"005930": "I')  # 쓰다 만 캐시
        m2, _ = wics.fetch(date(2026, 10, 17), tmp, session=Session(), pause=0)
        self.assertEqual(m2, m)
        self.assertEqual(wics.parse_overrides(["005490=소재"]), {"005490": "소재"})
        with self.assertRaises(ValueError):
            wics.parse_overrides(["005930=반도체"])


class WicsResilience(unittest.TestCase):
    def test_retry_then_saved_snapshot_fallback(self):
        import tempfile
        import json as _json
        from kospi_comp import wics
        root = tempfile.mkdtemp()
        old = os.path.join(root, "2026-10-17", "wics")
        os.makedirs(old)
        with open(os.path.join(old, "wics_20261016.json"), "w", encoding="utf-8") as f:
            _json.dump({"005490": "소재"}, f, ensure_ascii=False)

        class Down:
            calls = 0

            def get(self, *a, **k):
                Down.calls += 1
                raise requests.ConnectionError("reset")

        with mock.patch.object(wics.time, "sleep", lambda s: None):
            m, src = wics.fetch(date(2026, 10, 23), os.path.join(root, "2026-10-24", "wics"), session=Down(), pause=0)
        self.assertEqual(m, {"005490": "소재"})
        self.assertIn("2026-10-16", src)
        self.assertIn("직전 스냅샷", src)
        self.assertEqual(Down.calls, 4)  # 재시도 후 포기
        with mock.patch.object(wics.time, "sleep", lambda s: None):  # 기간 밖 스냅샷은 쓰지 않음
            m2, src2 = wics.fetch(date(2026, 11, 30), os.path.join(root, "2026-12-01", "wics"), session=Down(), pause=0)
        self.assertEqual(m2, {})
        self.assertIn("조회 실패", src2)


class Cli(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "fscore_cli", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "fscore.py"))
        self.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.cli)
        self.cli.load_dotenv = lambda: None

    def call(self, argv, env=None):
        import contextlib
        import io
        buf = io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=False), contextlib.redirect_stdout(buf):
            if not env:
                os.environ.pop("DART_API_KEY", None)
            code = self.cli.run(argv)
        return code, buf.getvalue()

    def test_empty_input_prints_only_the_prompt(self):
        self.assertEqual(self.call([]), (0, self.cli.PROMPT + "\n"))

    def test_no_key_lists_required_data_without_numbers_from_data(self):
        code, text = self.call(["005930", "--as-of", "2026-10-17"])
        self.assertEqual(code, 4)
        self.assertIn("추정치나 다른 출처의 값으로 대체하지 않습니다", text)
        self.assertIn("2025 반기 누적, 2025 3분기 누적, 2025 사업(연간), 2026 1분기 누적, 2026 반기 누적", text)

    def test_bad_wics_override(self):
        self.assertEqual(self.call(["005930", "--wics", "005930=반도체"])[0], 5)

    def test_dart_error_and_unexpected_error_paths(self):
        class Boom:
            def __init__(self, *a, **k):
                pass

            def corp_list(self):
                raise DartApiError("012", "접근할 수 없는 IP")

        with mock.patch.object(self.cli.fscore, "DartData", Boom):
            code, text = self.call(["005930"], {"DART_API_KEY": "SECRETKEY123"})
        self.assertEqual(code, 4)
        self.assertIn("012", text)

        class Crash(Boom):
            def corp_list(self):
                raise RuntimeError("boom SECRETKEY123")

        with mock.patch.object(self.cli.fscore, "DartData", Crash):
            code, text = self.call(["005930"], {"DART_API_KEY": "SECRETKEY123"})
        self.assertEqual(code, 1)
        self.assertNotIn("SECRETKEY123", text)

    def test_ambiguous_name_asks(self):
        corps = Resolve.CORPS

        class Data:
            def __init__(self, *a, **k):
                pass

            def corp_list(self):
                return corps

        with mock.patch.object(self.cli.fscore, "DartData", Data), \
                mock.patch.object(self.cli.wics, "fetch", lambda *a: ({}, "x")):
            code, text = self.call(["동명"], {"DART_API_KEY": "K"})
        self.assertEqual(code, 3)
        self.assertIn("종목 확인 필요", text)
        self.assertIn("동명 (111110)", text)


class Pipeline(unittest.TestCase):
    def test_final_pass_only_for_complete_pass(self):
        import pandas as pd
        from kospi_comp import report
        a = {**run("IT"), "code": "000010", "name": "A", "acc_mt": "12", "error": None}
        b = {**run("소재", all_reports(skip={(2024, 3)})), "code": "000020", "name": "B", "acc_mt": "12",
             "error": None}
        c = {**run(None), "code": "000030", "name": "C", "acc_mt": "12", "error": None}
        e = {"code": "000040", "name": "D", "sector": "IT", "error": "보고서 없음"}
        df = pd.DataFrame({"name": list("ABCDE"), "comp": [85.0, 90.0, 82.0, 81.0, 75.0]},
                          index=pd.Index(["000010", "000020", "000030", "000040", "000050"], name="code"))
        fs = fscore_output.frame([a, b, c, e])
        t = report.final_table(df, fs)
        self.assertEqual(t.loc["000010", "verdict"], "완결·통과")
        self.assertTrue(t.loc["000010", "final_pass"])
        self.assertTrue(t.loc["000020", "reference_pass"])
        self.assertFalse(t.loc["000020", "final_pass"])
        self.assertEqual(t.loc["000030", "verdict"], "검증 필요(WICS 미확인)")
        self.assertEqual(t.loc["000040", "verdict"], "산정 불가")
        self.assertTrue(t.loc["000050", "verdict"].startswith("관찰"))
        self.assertEqual(list(t["comp"]), sorted(t["comp"]))  # COMP 오름차순
        self.assertEqual(report.f_cells(t.loc["000010"])[:4], ["IT", "3점/4개", "3.00", "1·1·1·0"])


class NonDecemberFiscalYear(unittest.TestCase):
    """3월 결산: 사업보고서 bsns_year 표기가 회사마다 달라 기수로 같은 회계연도를 확인한다."""

    def test_annual_report_matched_by_kisu_when_bsns_year_is_next_year(self):
        r = run("IT", all_reports(annual_bsns_offset=1, kisu=KISU), acc_mt="03")
        self.assertEqual((r["metrics"]["rev_cur"], r["metrics"]["rev_prior"]), (635, 510))
        self.assertEqual(r["period_cur"], "제57기 3Q~제58기 2Q")
        self.assertEqual(r["verdict"], "완결·통과")

    def test_annual_report_with_same_bsns_year(self):
        r = run("IT", all_reports(kisu=KISU), acc_mt="03")
        self.assertEqual(r["metrics"]["rev_cur"], 635)

    def test_previous_years_annual_report_is_never_paired(self):
        # 사업보고서가 fy+1에 있는데 fy에도 '전년도' 사업보고서가 있으면 기수가 달라 버려야 함
        reports = all_reports(annual_bsns_offset=1, kisu=KISU)
        self.assertIn((2025, 4, "CFS"), reports)  # 회계연도 2024의 사업보고서(기수 56)
        r = run("IT", reports, acc_mt="03")
        self.assertEqual(r["reports"]["제57기 4Q"], None)  # 테스트 행에는 rcept_no가 없음
        self.assertEqual(r["metrics"]["rev_cur"], 635)

    def test_without_kisu_non_december_annual_is_rejected(self):
        r = run("IT", all_reports(annual_bsns_offset=1), acc_mt="03")
        self.assertTrue(all(p is None for p in r["points"].values()))
        self.assertIn("기수를 확인할 수 없어", r["missing"]["revenue_growth"])

    def test_locate_skips_annual_report_of_previous_fiscal_year(self):
        reports = all_reports(annual_bsns_offset=1, kisu=KISU)
        d = DartData.__new__(DartData)
        d.statements = fetcher(reports)
        self.assertEqual(d.locate("x", date(2026, 10, 17), "03"), ("CFS", (2026, 2)))


class Scoring(unittest.TestCase):
    def test_verdicts(self):
        f4 = fscore.COMMON
        self.assertEqual(judge(dict(zip(f4, [1, 1, 1, 0])), f4)["verdict"], "완결·통과")
        self.assertEqual(judge(dict(zip(f4, [1, 1, 0, 0])), f4)["verdict"], "완결·미통과")
        self.assertEqual(judge(dict(zip(f4, [1, 1, 1, None])), f4)["verdict"], "제한적 참고 통과")  # 3/3×4 = 4.0
        lim = judge(dict(zip(f4, [1, 1, 0, None])), f4)  # 2/3×4 = 2.67
        self.assertEqual((lim["verdict"], round(lim["norm"], 2)), ("제한적·미통과", 2.67))
        self.assertEqual(judge(dict(zip(f4, [None] * 4)), f4)["verdict"], "산정 불가")
        f5 = fscore.FACTORS
        self.assertEqual(judge(dict(zip(f5, [1, 1, 1, 0, 0])), f5)["verdict"], "완결·통과")
        self.assertEqual(judge(dict(zip(f5, [1, 1, 0, 0, 0])), f5)["verdict"], "완결·미통과")
        r = judge(dict(zip(f5, [1, 1, None, 0, None])), f5)  # 2/3×5 = 3.33
        self.assertEqual((r["verdict"], round(r["norm"], 2)), ("제한적 참고 통과", 3.33))

    def test_required_reports(self):
        self.assertEqual(fscore.required_reports((2026, 2)),
                         [(2024, 2), (2024, 3), (2024, 4), (2025, 1), (2025, 2), (2025, 3), (2025, 4),
                          (2026, 1), (2026, 2)])


class Locate(unittest.TestCase):
    def data(self, available):
        d = DartData.__new__(DartData)
        d.statements = lambda corp, fy, reprt, fs_div: ([{}] if (fy, CODE_Q[reprt], fs_div) in available else None)
        return d

    def test_prefers_consolidated(self):
        d = self.data({(2026, 2, "CFS"), (2026, 2, "OFS")})
        self.assertEqual(d.locate("x", date(2026, 10, 17)), ("CFS", (2026, 2)))

    def test_separate_only_when_no_consolidated(self):
        d = self.data({(2026, 2, "OFS"), (2026, 1, "OFS")})
        self.assertEqual(d.locate("x", date(2026, 10, 17)), ("OFS", (2026, 2)))

    def test_does_not_mix_when_consolidated_existed(self):
        d = self.data({(2026, 2, "OFS"), (2026, 1, "CFS")})
        self.assertEqual(d.locate("x", date(2026, 10, 17)), ("MIXED", (2026, 2)))

    def test_nothing(self):
        self.assertIsNone(self.data(set()).locate("x", date(2026, 10, 17)))


class Output(unittest.TestCase):
    def results(self):
        a = {**run("IT"), "code": "005930", "name": "가나전자", "acc_mt": "12", "error": None}
        b = {**run("소재", all_reports(skip={(2024, 3)})), "code": "010130", "name": "다라소재", "acc_mt": "12",
             "error": None}
        c = {"code": "000020", "name": "마바", "sector": "검증 필요", "error": "보고서 없음"}
        return [a, b, c]

    def test_markdown_and_tsv_match(self):
        res = self.results()
        md = fscore_output.markdown(res, "테스트")
        tsv = fscore_output.tsv(res).splitlines()
        self.assertEqual(tsv[0].split("\t"), fscore_output.COLUMNS)
        table = [line for line in md.splitlines() if line.startswith("| ")]
        self.assertEqual(table[0], "| " + " | ".join(fscore_output.COLUMNS) + " |")
        for md_row, tsv_row in zip(table[1:], tsv[1:]):
            self.assertEqual(md_row[2:-2].split(" | "), tsv_row.split("\t"))

    def test_cells(self):
        a, b, c = (fscore_output.cells(r) for r in self.results())
        self.assertEqual(a[:6], ["가나전자 (005930)", "IT", "3점/4개", "3.00", "1·1·1·0", "완결·통과"])
        self.assertEqual(a[6], f"{(635 / 510 - 1) * 100:+.1f}%")
        self.assertEqual(b[:6], ["다라소재 (010130)", "소재", "1점/1개", "5.00", "—·—·—·—·1", "제한적 참고 통과"])
        self.assertEqual(b[6:10], ["—"] * 4)
        self.assertEqual(c[2:6], ["0점/0개", "—", "—·—·—·—", "산정 불가"])

    def test_render_has_both_outputs_in_order(self):
        text = fscore_output.render(self.results(), "테스트")
        self.assertLess(text.index("[1] 대화창용 표"), text.index("[2] 엑셀용 탭 구분 텍스트"))
        block = text.split("```")[1]
        self.assertIn("\t", block)
        self.assertTrue(text.splitlines()[2].startswith("비교 기준: 현재 TTM 2025.3Q~2026.2Q"))

    def test_foreign_currency_amounts(self):
        reports = all_reports()
        for rows in reports.values():
            for r_ in rows:
                r_["currency"] = "USD"
        r = {**run("소재", reports), "code": "000001", "name": "A", "acc_mt": "12", "error": None}
        self.assertEqual(fscore_output.cells(r)[10], "-0.0백만 USD")
        self.assertEqual(fscore_output._money(-2.5e9, "KRW"), "-25억")
        self.assertEqual(fscore_output._money(-20, "KRW"), "-20원")
        self.assertEqual(fscore_output._money(-20, None), "-20(통화 미확인)")

    def test_separate_basis_is_labelled(self):
        r = {**run("IT", all_reports(fs_div="OFS"), fs_div="OFS"), "code": "000001", "name": "A", "acc_mt": "12",
             "error": None}
        self.assertIn("별도 기준", fscore_output.basis_line([r]))
        self.assertIn("별도 기준", fscore_output.stock_note(r))


class Resolve(unittest.TestCase):
    CORPS = [{"corp_code": "1", "corp_name": "삼성전자", "stock_code": "005930"},
             {"corp_code": "2", "corp_name": "동명", "stock_code": "111110"},
             {"corp_code": "3", "corp_name": "동명", "stock_code": "222220"},
             {"corp_code": "4", "corp_name": "삼성전기", "stock_code": "009150"}]

    def test_code_first_and_exact_name(self):
        found, ask = resolve(["삼성전기 005930", "삼성전기"], self.CORPS)
        self.assertEqual([f["code"] for f in found], ["005930", "009150"])
        self.assertEqual(ask, [])

    def test_ambiguous_or_unknown_names_are_asked(self):
        found, ask = resolve(["동명", "삼성"], self.CORPS)
        self.assertEqual(found, [])
        self.assertEqual(ask[0]["candidates"], [("동명", "111110"), ("동명", "222220")])
        self.assertEqual({c for _, c in ask[1]["candidates"]}, {"005930", "009150"})


class KeyIsNeverPrinted(unittest.TestCase):
    def test_network_error_masks_key(self):
        client = DartApiClient("SECRETKEY123")
        err = requests.ConnectionError("HTTPSConnectionPool: /api/x.json?crtfc_key=SECRETKEY123 failed")
        with mock.patch.object(client.session, "get", side_effect=err):
            with self.assertRaises(DartApiError) as ctx:
                client.financial_statements("00000001", 2026, "11012")
        self.assertEqual(ctx.exception.status, "network")
        self.assertNotIn("SECRETKEY123", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
