"""MagManager (Mirabel) API client wrapper.

Wraps the four THM stored-proc endpoints documented in
data/api-documentation.html:
  - api_ContactsGetTHM       (10000 rows/page)
  - api_ContactActivityGetTHM (1000 rows/page)
  - api_OpportunityGetTHM    (1000 rows/page)
  - api_ProposalsGetTHM      (1000 rows/page)

Every endpoint queries multiple tenant databases in one call. Response shape:
  { StatusCode, Message, Data: [...], Warnings?: [{DatabaseName,ErrorNumber,ErrorMessage}] }

Caller pattern:
    mm = MagManagerClient()
    for page in mm.iter_contacts(from_date="2025-01-01"):
        # page is a list of dicts; warnings surfaced via mm.last_warnings

Required env vars:
- MAGMANAGER_API_KEY
"""

from __future__ import annotations

import os
import time
from typing import Iterator
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = (
    "https://mirabelconnect.mirabeltechnologies.com"
    "/api/v2/thehomemagcolorado/_proc"
)

CONTACTS_PAGE_SIZE = 10_000
DEFAULT_PAGE_SIZE = 1_000

# Endpoint -> page size (for pagination loop termination)
PAGE_SIZES = {
    "api_ContactsGetTHM": CONTACTS_PAGE_SIZE,
    "api_ContactActivityGetTHM": DEFAULT_PAGE_SIZE,
    "api_OpportunityGetTHM": DEFAULT_PAGE_SIZE,
    "api_ProposalsGetTHM": DEFAULT_PAGE_SIZE,
}


class MagManagerAuthError(Exception):
    """API key missing or rejected."""


class MagManagerAPIError(Exception):
    """API returned a non-2xx response (other than 404 no-records)."""


class MagManagerClient:
    def __init__(self, api_key: str | None = None, timeout: int = 60):
        # Env can be named the conventional way or as the literal HTTP header name.
        self.api_key = (
            api_key
            or os.getenv("MAGMANAGER_API_KEY")
            or os.getenv("x-mirabel-api-key")
        )
        if not self.api_key:
            raise MagManagerAuthError(
                "MAGMANAGER_API_KEY not set in env. Add it to .env."
            )
        self.timeout = timeout
        self.session = requests.Session()
        self.last_warnings: list[dict] = []  # populated after each call

    # ---------- low-level ----------

    def _headers(self) -> dict:
        return {"x-mirabel-api-key": self.api_key}

    def _get(self, proc: str, params: dict) -> dict:
        """Make one paginated call. Returns the full response envelope.

        404 (no records) returns {"StatusCode":404, "Data":[], "Warnings":[]}.
        Other non-2xx raises MagManagerAPIError.
        """
        # Filter out None / empty values so defaults apply server-side
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        url = f"{BASE_URL}/{proc}?{urlencode(clean)}"

        for attempt in range(3):
            try:
                r = self.session.get(url, headers=self._headers(), timeout=self.timeout)
                break
            except requests.RequestException as e:
                if attempt == 2:
                    raise MagManagerAPIError(f"Network error on {proc}: {e}") from e
                time.sleep(2 ** attempt)

        if r.status_code == 401 or r.status_code == 403:
            raise MagManagerAuthError(
                f"{r.status_code} on {proc} — API key rejected. Body: {r.text[:300]}"
            )
        if r.status_code == 404:
            # 404 = no records found in the requested filter; treat as empty Data
            try:
                body = r.json()
            except ValueError:
                body = {}
            self.last_warnings = body.get("Warnings") or []
            return {
                "StatusCode": 404,
                "Message": body.get("Message", "No records found"),
                "Data": [],
                "Warnings": self.last_warnings,
            }
        if r.status_code == 400:
            raise MagManagerAPIError(
                f"400 Bad Request on {proc}: {r.text[:500]}"
            )
        if not r.ok:
            raise MagManagerAPIError(
                f"{r.status_code} on {proc}: {r.text[:500]}"
            )

        body = r.json()
        # Doc shows {StatusCode, Message, Data: [...], Warnings?: [...]} but
        # the live API returns a bare list. Normalize both.
        if isinstance(body, list):
            body = {"StatusCode": r.status_code, "Data": body, "Warnings": []}
        else:
            if "Data" not in body:
                body["Data"] = []
            if "Warnings" not in body:
                body["Warnings"] = []
        self.last_warnings = body.get("Warnings") or []
        return body

    # ---------- public per-endpoint helpers ----------

    def get_contacts_page(
        self,
        *,
        page: int = 1,
        customer_id: str | None = None,
        create_date_from: str | None = None,
        create_date_to: str | None = None,
        database_name: str | None = None,
    ) -> dict:
        return self._get(
            "api_ContactsGetTHM",
            {
                "PageNumber": page,
                "customerID": customer_id,
                "CreateDateFrom": create_date_from,
                "CreateDateTo": create_date_to,
                "DatabaseName": database_name,
            },
        )

    def get_activities_page(
        self,
        *,
        page: int = 1,
        customer_id: str | None = None,
        rep_id: str | None = None,
        activity_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        database_name: str | None = None,
    ) -> dict:
        return self._get(
            "api_ContactActivityGetTHM",
            {
                "PageNumber": page,
                "CustomerID": customer_id,
                "RepID": rep_id,
                "ActivityID": activity_id,
                "FromDate": from_date,
                "ToDate": to_date,
                "DatabaseName": database_name,
            },
        )

    def get_opportunities_page(
        self,
        *,
        page: int = 1,
        opportunity_id: str | None = None,
        customer_id: str | None = None,
        contact_id: str | None = None,
        owner_id: str | None = None,
        assigned_to_id: str | None = None,
        stage_id: str | None = None,
        status: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        database_name: str | None = None,
    ) -> dict:
        return self._get(
            "api_OpportunityGetTHM",
            {
                "PageNumber": page,
                "OpportunityID": opportunity_id,
                "CustomerID": customer_id,
                "ContactID": contact_id,
                "OwnerID": owner_id,
                "AssignedToID": assigned_to_id,
                "StageID": stage_id,
                "Status": status,
                "FromDate": from_date,
                "ToDate": to_date,
                "DatabaseName": database_name,
            },
        )

    def get_proposals_page(
        self,
        *,
        page: int = 1,
        proposal_id: str | None = None,
        insertion_id: str | None = None,
        customer_id: str | None = None,
        product_type_id: str | None = None,
        product_id: str | None = None,
        issue_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        date_type: str | None = None,  # 'DateCreated' | 'IssueDate'
        is_active: str | None = None,  # '0' | '1'
        approval_status: str | None = None,  # 0/1/2
        approval_status_name: str | None = None,  # 'Draft'/'Sent'/'Approved'
        database_name: str | None = None,
    ) -> dict:
        return self._get(
            "api_ProposalsGetTHM",
            {
                "PageNumber": page,
                "ProposalID": proposal_id,
                "InsertionID": insertion_id,
                "CustomerID": customer_id,
                "ProductTypeID": product_type_id,
                "ProductID": product_id,
                "IssueID": issue_id,
                "FromDate": from_date,
                "ToDate": to_date,
                "DateType": date_type,
                "IsActive": is_active,
                "ApprovalStatus": approval_status,
                "ApprovalStatusName": approval_status_name,
                "DatabaseName": database_name,
            },
        )

    # ---------- generic paginator ----------

    def iter_pages(self, proc: str, **kwargs) -> Iterator[list[dict]]:
        """Yield each page's Data array until a short page is returned.

        Honors the per-endpoint page size in PAGE_SIZES. Surfaces warnings on
        self.last_warnings after each page (caller can capture them per-page).
        """
        page_size = PAGE_SIZES.get(proc, DEFAULT_PAGE_SIZE)
        page = 1
        while True:
            body = self._get(proc, {**kwargs, "PageNumber": page})
            data = body.get("Data") or []
            yield data
            if len(data) < page_size:
                break
            page += 1
