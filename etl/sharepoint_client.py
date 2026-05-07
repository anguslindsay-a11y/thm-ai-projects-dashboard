"""SharePoint / Microsoft Graph client wrapper.

App-only authentication via MSAL client-credentials flow. Phase 2 scope is
read-only: resolve site IDs, list folder contents, download files to memory.
Reused later by per-source ETL scripts (IA, Ad Placements, Ad JPGs).

Required env vars:
- AZURE_TENANT_ID
- AZURE_CLIENT_ID
- AZURE_CLIENT_SECRET

Usage:
    from etl.sharepoint_client import SharePointClient

    sp = SharePointClient()
    site_id = sp.resolve_site_id("https://thehomemagwest.sharepoint.com/sites/SystemsOps")
    data = sp.download_file_bytes(site_id, "Reports/InBox Advantage/IA Data.xlsx")
"""

import os
import time
from urllib.parse import urlparse, unquote, quote

import requests
from dotenv import load_dotenv

try:
    import msal
except ImportError as e:
    raise ImportError(
        "msal is not installed. Run: pip install -r requirements.txt"
    ) from e

load_dotenv()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPE = ["https://graph.microsoft.com/.default"]


class SharePointAuthError(Exception):
    """Token acquisition or auth-config failure."""


class SharePointAPIError(Exception):
    """Graph API returned a non-2xx response."""


class SharePointClient:
    def __init__(self):
        self.tenant_id = os.getenv("AZURE_TENANT_ID")
        self.client_id = os.getenv("AZURE_CLIENT_ID")
        self.client_secret = os.getenv("AZURE_CLIENT_SECRET")
        missing = [
            k for k, v in {
                "AZURE_TENANT_ID": self.tenant_id,
                "AZURE_CLIENT_ID": self.client_id,
                "AZURE_CLIENT_SECRET": self.client_secret,
            }.items() if not v
        ]
        if missing:
            raise SharePointAuthError(
                f"Missing env var(s): {', '.join(missing)}. "
                "Add them to .env before running."
            )

        self._app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
        )
        self._token = None
        self._token_expires_at = 0.0
        self._session = requests.Session()

    # ---------- auth ----------

    def get_token(self) -> str:
        """Return a valid access token, refreshing if within 60s of expiry."""
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        result = self._app.acquire_token_for_client(scopes=SCOPE)
        if "access_token" not in result:
            err = (
                result.get("error_description")
                or result.get("error")
                or str(result)
            )
            raise SharePointAuthError(
                f"Token acquisition failed: {err}\n"
                "Check AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET "
                "and confirm the secret has not expired."
            )
        self._token = result["access_token"]
        self._token_expires_at = time.time() + result.get("expires_in", 3600)
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.get_token()}"}

    # ---------- low-level GET ----------

    def _get(self, path: str, *, stream: bool = False) -> requests.Response:
        url = path if path.startswith("http") else f"{GRAPH_BASE}{path}"
        r = self._session.get(url, headers=self._headers(), stream=stream)
        if r.status_code == 401:
            raise SharePointAuthError(
                f"401 Unauthorized — token rejected by Graph. Body: {r.text[:300]}"
            )
        if r.status_code == 403:
            raise SharePointAPIError(
                f"403 Forbidden on {url}\n"
                "Likely cause: the Entra app does not have Sites.Selected access "
                "to this site. Have IT grant the app the 'read' role on the site "
                "via PnP PowerShell (Grant-PnPAzureADAppSitePermission).\n"
                f"Body: {r.text[:300]}"
            )
        if r.status_code == 404:
            raise SharePointAPIError(
                f"404 Not Found on {url}\n"
                "Check the site URL hostname/path and the file path within "
                "the document library (case-sensitive on some tenants)."
            )
        if not r.ok:
            raise SharePointAPIError(f"{r.status_code} on {url}: {r.text[:500]}")
        return r

    # ---------- public API ----------

    def resolve_site_id(self, site_url: str) -> str:
        """Convert a SharePoint site URL into a Graph site ID.

        Accepts either the bare site root (preferred) or any deeper URL —
        only the hostname and the leading /sites/{name} (or /teams/{name})
        segment are used.

        Returns the composite ID Graph expects, e.g.
        'thehomemagwest.sharepoint.com,<guid>,<guid>'.
        """
        parsed = urlparse(site_url)
        if not parsed.netloc:
            raise ValueError(f"Could not parse site URL: {site_url!r}")
        hostname = parsed.netloc
        path = unquote(parsed.path)
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() in ("sites", "teams"):
            site_path = f"/{parts[0]}/{parts[1]}"
        else:
            site_path = ""  # tenant root site
        endpoint = f"/sites/{hostname}:{site_path}" if site_path else f"/sites/{hostname}"
        r = self._get(endpoint)
        return r.json()["id"]

    def _drive_path_url(self, site_id: str, path: str, suffix: str) -> str:
        """Build a path-addressed DriveItem URL.

        Graph syntax: /drive/root:/{path}{suffix}
          - metadata: suffix=""
          - listing children: suffix=":/children"
          - download content: suffix=":/content"
        """
        encoded = quote(path.strip("/"), safe="/")
        return f"/sites/{site_id}/drive/root:/{encoded}{suffix}"

    def list_drive_root(self, site_id: str, top: int = 25) -> list:
        """List items at the root of the default document library."""
        r = self._get(f"/sites/{site_id}/drive/root/children?$top={top}")
        return r.json().get("value", [])

    def list_folder(self, site_id: str, folder_path: str, top: int = 100) -> list:
        """List items in a folder by server-relative path within the default library."""
        path = folder_path.strip("/")
        if not path:
            return self.list_drive_root(site_id, top=top)
        r = self._get(self._drive_path_url(site_id, path, f":/children?$top={top}"))
        return r.json().get("value", [])

    def get_file_metadata(self, site_id: str, file_path: str) -> dict:
        """Return Graph DriveItem metadata (id, size, eTag, lastModified, etc.)."""
        r = self._get(self._drive_path_url(site_id, file_path, ""))
        return r.json()

    def download_file_bytes(self, site_id: str, file_path: str) -> bytes:
        """Download a file from the default doc library into memory."""
        r = self._get(self._drive_path_url(site_id, file_path, ":/content"))
        return r.content
