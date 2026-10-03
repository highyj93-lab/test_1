"""Client for the OpenDART (Financial Supervisory Service) API.

API docs: https://opendart.fss.or.kr/guide/main.do
"""
import io
import os
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

    def _get(self, endpoint: str, **params: Any) -> dict:
        params = {"crtfc_key": self.api_key, **{k: v for k, v in params.items() if v is not None}}
        resp = self.session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
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

    def download_corp_codes(self) -> bytes:
        """고유번호 (corpCode.xml): download the full corp-code list as a zip.

        Returns the raw XML bytes (the API serves a zip containing a single
        CORPCODE.xml file).
        """
        resp = self.session.get(
            f"{BASE_URL}/corpCode.xml",
            params={"crtfc_key": self.api_key},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            name = zf.namelist()[0]
            return zf.read(name)
