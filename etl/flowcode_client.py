"""Flowcode REST API client — handles token exchange, caching, and refresh.

Auth flow (from Flowcode Authentication docs):
  POST https://authn.flowcode.com/identity/resources/auth/v1/api-token
       body: {"clientId": ..., "secret": ...}
       -> {accessToken, refreshToken, expiresIn, expires}
  Use Authorization: Bearer <accessToken> on all API calls.

API host: https://api.conversions.flowcode.com  (gRPC-Web / Connect routes, all POST)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

AUTH_BASE = "https://authn.flowcode.com"
API_BASE = "https://api.conversions.flowcode.com"
TOKEN_CACHE_PATH = Path(__file__).resolve().parent.parent / "output" / ".flowcode_token.json"
REFRESH_BUFFER_SECONDS = 300  # refresh 5 min before expiry
TIMEOUT = 30

# Bundle (template) IDs from the Flowcode Portal guide
BUNDLE_SCAN_TO_URL = "98209349-8051-4ca7-9415-a06bbd412065"
BUNDLE_CONTACT_FORM = "17e0f0fd-b317-4fa2-9762-59ebb462b82d"
BUNDLE_LANDING_PAGE = "c608febb-93a0-43e6-bfba-b4c344e9c652"
BUNDLE_SMARTFLOW = "e6ab5261-5902-4156-ab6c-00e96d2df824"


class FlowcodeError(Exception):
    """Raised when a Flowcode API call returns a non-2xx response."""


class FlowcodeClient:
    def __init__(
        self,
        client_id: str | None = None,
        secret: str | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
    ):
        self.client_id = client_id or os.getenv("FLOWCODE_CLIENT_ID")
        self.secret = secret or os.getenv("FLOWCODE_API_KEY")
        self.org_id = org_id or os.getenv("FLOWCODE_ORG_ID", "")
        self.workspace_id = workspace_id or os.getenv("FLOWCODE_WORKSPACE_ID", "")
        if not self.client_id or not self.secret:
            raise FlowcodeError(
                "FLOWCODE_CLIENT_ID and FLOWCODE_API_KEY must be set in .env"
            )
        self._token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0

    # ---------- auth ----------

    def _load_cached_token(self) -> bool:
        if not TOKEN_CACHE_PATH.exists():
            return False
        try:
            data = json.loads(TOKEN_CACHE_PATH.read_text())
            if data.get("expiresAt", 0) - REFRESH_BUFFER_SECONDS > time.time():
                self._token = data["accessToken"]
                self._refresh_token = data.get("refreshToken")
                self._expires_at = data["expiresAt"]
                return True
        except Exception:
            pass
        return False

    def _save_cached_token(self) -> None:
        TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE_PATH.write_text(json.dumps({
            "accessToken": self._token,
            "refreshToken": self._refresh_token,
            "expiresAt": self._expires_at,
        }))

    def _exchange_token(self) -> None:
        r = requests.post(
            f"{AUTH_BASE}/identity/resources/auth/v1/api-token",
            headers={"accept": "application/json", "content-type": "application/json"},
            json={"clientId": self.client_id, "secret": self.secret},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            raise FlowcodeError(f"Token exchange failed: {r.status_code} {r.text[:300]}")
        body = r.json()
        self._token = body["accessToken"]
        self._refresh_token = body.get("refreshToken")
        self._expires_at = time.time() + int(body.get("expiresIn", 86400))
        self._save_cached_token()

    def token(self) -> str:
        if self._token and self._expires_at - REFRESH_BUFFER_SECONDS > time.time():
            return self._token
        if self._load_cached_token():
            return self._token  # type: ignore[return-value]
        self._exchange_token()
        return self._token  # type: ignore[return-value]

    # ---------- low-level POST helper ----------

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{API_BASE}{path}"
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.token()}",
                "content-type": "application/json",
                "accept": "application/json",
            },
            json=body,
            timeout=TIMEOUT,
        )
        if r.status_code >= 400:
            raise FlowcodeError(f"POST {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else {}

    def _require_org_ws(self) -> dict[str, str]:
        if not self.org_id or not self.workspace_id:
            raise FlowcodeError(
                "FLOWCODE_ORG_ID and FLOWCODE_WORKSPACE_ID must be set in .env "
                "(find them in Flowcode Profile -> 'Finding your Workspace ID')"
            )
        return {"orgId": self.org_id, "workspaceId": self.workspace_id}

    # ---------- folders ----------

    def list_folders(self, path: str = "/") -> list[dict[str, Any]]:
        body = {**self._require_org_ws(), "filter": {"path": path}}
        res = self.post("/folder.v1.FolderService/ListFolders", body)
        return res.get("folders") or res.get("items") or []

    def create_folder(self, name: str, parent_path: str = "/") -> dict[str, Any]:
        body = {**self._require_org_ws(), "name": name, "parentPath": parent_path}
        return self.post("/folder.v1.FolderService/CreateFolder", body)

    # ---------- brand kits + domains ----------

    def get_default_brand_kit(self) -> dict[str, Any]:
        return self.post(
            "/brands.v1.BrandsService/GetDefaultBrandKit", self._require_org_ws()
        )

    def list_brand_kits(self) -> list[dict[str, Any]]:
        body = {
            **self._require_org_ws(),
            "filter": {"visibilities": ["VISIBILITY_ORG", "VISIBILITY_PRIVATE"]},
        }
        res = self.post("/brands.v1.BrandsService/ListBrandKits", body)
        return res.get("brandKits") or []

    def list_domains(self) -> list[dict[str, Any]]:
        res = self.post("/links.v1.LinksService/ListDomains", self._require_org_ws())
        return res.get("items") or []

    # ---------- suites (flows) ----------

    def list_bundles(self) -> list[dict[str, Any]]:
        body = {**self._require_org_ws(), "visibilities": ["VISIBILITY_PUBLIC"]}
        res = self.post("/bundles.v1.BundleService/ListBundles", body)
        return res.get("bundles") or []

    def list_suites(
        self,
        page_size: int = 250,
        include_drafts_and_archived: bool = True,
    ) -> list[dict[str, Any]]:
        """List Suites in the workspace. By default returns ACTIVE + DRAFT + ARCHIVED
        with full pagination (passing include_drafts_and_archived=False reverts to
        the API's default state-filtered + first-page-only behavior).

        Flowcode's default ListSuites filter EXCLUDES drafts and archived Suites,
        so the "include_drafts_and_archived=True" path is what most callers want.
        Without it the legacy "Migrated from Flowcode 1" Suites are invisible.
        """
        all_suites: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                **self._require_org_ws(),
                "pagination": {"first": page_size, **({"after": cursor} if cursor else {})},
            }
            if include_drafts_and_archived:
                body["states"] = [
                    "ASSET_STATE_ACTIVE",
                    "ASSET_STATE_DRAFT",
                    "ASSET_STATE_ARCHIVED",
                ]
            res = self.post("/bundles.v1.BundleService/ListSuites", body)
            suites = res.get("suites") or res.get("items") or []
            all_suites.extend(suites)
            page_info = res.get("pageInfo") or {}
            if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
                break
            cursor = page_info["endCursor"]
            if len(all_suites) > 50_000:  # safety circuit-breaker
                break
        return all_suites

    def create_suite(
        self,
        name: str,
        default_url: str,
        folder_path: str = "",
        brand_kit_id: str | None = None,
        bundle_id: str = BUNDLE_SCAN_TO_URL,
        dynamic_destination: bool = True,
    ) -> dict[str, Any]:
        """Create a flow ("Suite") in one call."""
        metadata_schema = json.dumps({
            "type": "object",
            "properties": {
                "url": {"title": "Destination URL", "description": "", "type": "string", "default": ""}
            },
        })
        config = {
            "code_batch-1": {
                "metadata": {"url": default_url},
                "metadataSchema": metadata_schema,
                "position": {},
            },
            "external_destination-1": {
                "appendUtmParameters": True,
                "url": "{{ .request.url }}" if dynamic_destination else default_url,
                "type": "EXTERNAL_DESTINATION_TYPE_URL",
            },
        }
        body: dict[str, Any] = {
            **self._require_org_ws(),
            "bundleId": bundle_id,
            "name": name,
            "folderPath": folder_path,
            "state": "ASSET_STATE_ACTIVE",
            "config": config,
        }
        if brand_kit_id:
            body["brandKitId"] = brand_kit_id
        return self.post("/bundles.v1.BundleService/CreateSuite", body)

    def get_suite(self, suite_id: str) -> dict[str, Any]:
        return self.post("/bundles.v1.BundleService/GetSuite", {"id": suite_id})

    def move_suite_to_folder(self, suite_id: str, folder_path: str) -> dict[str, Any]:
        body = {
            "suite": {
                "id": suite_id,
                **self._require_org_ws(),
                "folderPath": folder_path,
            },
            "mask": "folderPath",
        }
        return self.post("/bundles.v1.BundleService/UpdateSuite", body)

    def rename_suite(self, suite_id: str, new_name: str) -> dict[str, Any]:
        body = {
            "suite": {
                "id": suite_id,
                **self._require_org_ws(),
                "name": new_name,
            },
            "mask": "name",
        }
        return self.post("/bundles.v1.BundleService/UpdateSuite", body)

    # ---------- codes ----------

    def add_codes_to_batch(
        self, batch_id: str, codes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        body = {
            **self._require_org_ws(),
            "batchId": batch_id,
            "requests": codes,
        }
        res = self.post("/codes.v3.CodeService/AddCodesToBatch", body)
        return res.get("codes") or []

    def list_codes(
        self, batch_id: str, name_prefix: str | None = None, page_size: int = 100
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            **self._require_org_ws(),
            "batchId": batch_id,
            "pagination": {"first": page_size},
        }
        if name_prefix:
            body["namePrefix"] = name_prefix
        res = self.post("/codes.v3.CodeService/ListCodes", body)
        return res.get("codes") or []

    def archive_code(self, code_id: str) -> dict[str, Any]:
        return self.post(
            "/codes.v3.CodeService/UpdateCode",
            {
                "code": {"id": code_id, "state": "ASSET_STATE_ARCHIVED"},
                "mask": "state",
            },
        )
