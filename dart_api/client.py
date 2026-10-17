"""Client for the OpenDART (Financial Supervisory Service) API.

API docs: https://opendart.fss.or.kr/guide/main.do
"""
import io
import json
import os
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Optional

import requests

BASE_URL = "https://opendart.fss.or.kr/api"

# DART-specific status codes that are not HTTP errors but signal API-level failures.
_OK_STATUS = "000"


class DartApiError(Exception):
    """Raised when the DART API responds with a non-success status code."""

    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message
        super().__init__(f"[{status}] {message}")


class DartApiClient:
    """Thin wrapper around the OpenDART REST API.

    The API key is never hardcoded: pass it explicitly or set it via the
    DART_API_KEY environment variable (e.g. in a local, gitignored .env file).
    """

    def __init__(self, api_key: Optional[str] = None, timeout: int = 10):
        self.api_key = api_key or os.environ.get("DART_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DART API key is required. Pass api_key= or set DART_API_KEY."
            )
        self.timeout = timeout
        self.session = requests.Session()

    def _request(self, endpoint: str, params: dict) -> requests.Response:
        """GET with the key attached. Network/HTTP errors are re-raised as
        DartApiError("network", ...) with the key masked, because their messages
        include the request URL (and therefore crtfc_key)."""
        try:
            resp = self.session.get(
                f"{BASE_URL}/{endpoint}",
                params={"crtfc_key": self.api_key, **params},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            raise DartApiError("network", str(e).replace(self.api_key, "***")) from None

    def _get(self, endpoint: str, **params: Any) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            data = self._request(endpoint, params).json()
        except ValueError:
            raise DartApiError("network", f"{endpoint}: invalid JSON response") from None
        status = data.get("status")
        if status != _OK_STATUS:
            raise DartApiError(status, data.get("message", "Unknown DART API error"))
        return data

    def search_disclosures(
        self,
        corp_code: Optional[str] = None,
        bgn_de: Optional[str] = None,
        end_de: Optional[str] = None,
        page_no: int = 1,
        page_count: int = 10,
        **extra: Any,
    ) -> dict:
        """공시검색 (list.json): search recent disclosures."""
        return self._get(
            "list.json",
            corp_code=corp_code,
            bgn_de=bgn_de,
            end_de=end_de,
            page_no=page_no,
            page_count=page_count,
            **extra,
        )

    def get_company(self, corp_code: str) -> dict:
        """기업개황 (company.json): basic info for a single company."""
        return self._get("company.json", corp_code=corp_code)

    def financial_statements(
        self, corp_code: str, bsns_year: int, reprt_code: str, fs_div: str = "CFS"
    ) -> dict:
        """단일회사 전체 재무제표 (fnlttSinglAcntAll.json).

        reprt_code: 11013 1분기 / 11012 반기 / 11014 3분기 / 11011 사업보고서.
        fs_div: CFS 연결 / OFS 별도.
        """
        return self._get(
            "fnlttSinglAcntAll.json",
            corp_code=corp_code,
            bsns_year=str(bsns_year),
            reprt_code=reprt_code,
            fs_div=fs_div,
        )

    def download_corp_codes(self) -> bytes:
        """고유번호 (corpCode.xml): download the full corp-code list as a zip.

        Returns the raw XML bytes (the API serves a zip containing a single
        CORPCODE.xml file).
        """
        body = self._request("corpCode.xml", {}).content
        if not zipfile.is_zipfile(io.BytesIO(body)):
            # Errors (bad key, IP, limit, maintenance) come back as HTTP 200 with an XML/JSON status body.
            status = message = None
            try:
                root = ET.fromstring(body)
                status, message = root.findtext("status"), root.findtext("message")
            except ET.ParseError:
                try:
                    data = json.loads(body)
                    status, message = data.get("status"), data.get("message")
                except ValueError:
                    pass
            raise DartApiError(status or "network", message or "corpCode.xml: unexpected (non-zip) response")
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            return zf.read(zf.namelist()[0])
