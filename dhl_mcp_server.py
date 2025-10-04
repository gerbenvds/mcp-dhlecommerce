"""FastMCP server that exposes DHL parcel data via the Model Context Protocol."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests
from requests import Response
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from fastmcp import FastMCP

LOGGER = logging.getLogger(__name__)
SERVER_VERSION = os.getenv("MCP_SERVER_VERSION", "0.0.0-dev")


@dataclass
class DHLConfig:
    """Configuration for connecting to the DHL API."""

    username: str
    password: str
    base_url: str = "https://my.dhlecommerce.nl/"

    @classmethod
    def from_env(cls) -> "DHLConfig":
        username = os.getenv("DHL_USERNAME")
        password = os.getenv("DHL_PASSWORD")
        if not username or not password:
            raise RuntimeError(
                "Missing DHL credentials. Set DHL_USERNAME and DHL_PASSWORD in the environment."
            )
        return cls(username=username, password=password)


class DHLClient:
    """Thin wrapper around the DHL parcel API.

    The client logs in lazily and reuses a single `requests.Session` with retries.
    """

    def __init__(self, config: Optional[DHLConfig] = None) -> None:
        self._config = config or DHLConfig.from_env()
        self._session = requests.Session()
        self._session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=5,
                    backoff_factor=2,
                    status_forcelist=(500, 502, 503, 504),
                )
            ),
        )
        self._authenticated = False

    @property
    def base_url(self) -> str:
        return self._config.base_url.rstrip("/") + "/"

    def _post(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        response = self._session.post(self.base_url + path.lstrip("/"), **kwargs)
        return self._process_response(response)

    def _get(self, path: str, **kwargs: Any) -> Dict[str, Any]:
        response = self._session.get(self.base_url + path.lstrip("/"), **kwargs)
        return self._process_response(response)

    @staticmethod
    def _process_response(response: Response) -> Dict[str, Any]:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:  # pragma: no cover - network specific
            LOGGER.error("DHL API error: %s", exc)
            raise
        try:
            return response.json()
        except ValueError as exc:
            LOGGER.error("Unexpected non-JSON response from DHL API: %s", exc)
            raise RuntimeError("DHL API returned non-JSON response") from exc

    def ensure_authenticated(self) -> None:
        if self._authenticated:
            return
        LOGGER.debug("Logging into DHL API as %s", self._config.username)
        payload = {
            "email": self._config.username,
            "password": self._config.password,
        }
        data = self._post("api/user/login", json=payload)
        if not data:
            raise RuntimeError("DHL login did not return data; authentication failed")
        self._authenticated = True

    def get_user(self) -> Dict[str, Any]:
        self.ensure_authenticated()
        return self._get("api/user")

    def list_parcels(self) -> Dict[str, Any]:
        self.ensure_authenticated()
        return self._get("receiver-parcel-api/parcels")


_client: Optional[DHLClient] = None


def get_client() -> DHLClient:
    global _client
    if _client is None:
        _client = DHLClient()
    return _client


def _parcel_received_at(parcel: Dict[str, Any]) -> Optional[datetime]:
    indication = parcel.get("receivingTimeIndication")
    moment = indication.get("moment") if isinstance(indication, dict) else None
    if not moment:
        return None
    try:
        return datetime.fromisoformat(moment.replace("Z", "+00:00"))
    except ValueError:
        return None


def _filter_parcels(
    parcels: Iterable[Dict[str, Any]],
    status: Optional[str] = None,
    category: Optional[str] = None,
    delivered_within_days: Optional[int] = None,
    returnable: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    cutoff = None
    if delivered_within_days is not None:
        cutoff = now - timedelta(days=delivered_within_days)

    def predicate(parcel: Dict[str, Any]) -> bool:
        if status and parcel.get("status") != status:
            return False
        if category and parcel.get("category") != category:
            return False
        if returnable is not None and parcel.get("returnable") is not returnable:
            return False
        if cutoff is not None:
            received_at = _parcel_received_at(parcel)
            if not received_at or received_at < cutoff:
                return False
        return True

    return [parcel for parcel in parcels if predicate(parcel)]


def _parcel_identifier_matches(parcel: Dict[str, Any], identifier: str) -> bool:
    return identifier in {
        parcel.get("parcelId"),
        parcel.get("barcode"),
    }


def _format_parcel_summary(parcel: Dict[str, Any]) -> Dict[str, Any]:
    received_at = _parcel_received_at(parcel)
    destination = parcel.get("destination", {}).get("address", {})
    return {
        "parcelId": parcel.get("parcelId"),
        "barcode": parcel.get("barcode"),
        "status": parcel.get("status"),
        "category": parcel.get("category"),
        "deliveredAt": received_at.isoformat() if received_at else None,
        "returnable": parcel.get("returnable"),
        "destination": {
            "postalCode": destination.get("postalCode"),
            "city": destination.get("city"),
            "street": destination.get("street"),
            "houseNumber": destination.get("houseNumber"),
        },
    }


mcp = FastMCP(
    name="DHL Parcels",
    version=SERVER_VERSION,
    instructions=(
        "Access live DHL parcel data. Resources expose parcel listings, individual parcels, "
        "and the authenticated user profile via MCP URIs. Tools let you filter parcels by "
        "status, category, recency, or returnability, and fetch concise parcel summaries. "
        "Ensure DHL_USERNAME and DHL_PASSWORD are set so the server can authenticate before "
        "invoking resources or tools."
    ),
)


@mcp.resource(
    "dhl://parcels", name="Parcels", description="Latest parcels from DHL API", mime_type="application/json"
)
def parcels_resource() -> Dict[str, Any]:
    """Return the full parcel payload from DHL."""
    parcels = get_client().list_parcels()
    return {
        "source": "live",
        "parcels": parcels.get("parcels", []),
        "meta": {"count": len(parcels.get("parcels", []))},
    }


@mcp.resource(
    "dhl://user/profile", name="DHL User", description="Authenticated DHL user profile", mime_type="application/json"
)
def user_profile_resource() -> Dict[str, Any]:
    profile = get_client().get_user()
    return profile


@mcp.resource(
    "dhl://parcels/{identifier}",
    name="Parcel",
    description="Fetch a specific DHL parcel by parcel ID or barcode.",
    mime_type="application/json",
)
def parcel_by_identifier(identifier: str) -> Dict[str, Any]:
    parcels = get_client().list_parcels().get("parcels", [])
    for parcel in parcels:
        if _parcel_identifier_matches(parcel, identifier):
            return _format_parcel_summary(parcel)
    raise ValueError(f"Parcel '{identifier}' not found in DHL response")


@mcp.tool(name="filter_parcels")
def filter_parcels(
    status: Optional[str] = None,
    category: Optional[str] = None,
    delivered_within_days: Optional[int] = None,
    returnable: Optional[bool] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Return parcels filtered by status/category/time window."""

    parcels = get_client().list_parcels().get("parcels", [])
    filtered = _filter_parcels(
        parcels=parcels,
        status=status,
        category=category,
        delivered_within_days=delivered_within_days,
        returnable=returnable,
    )

    return [_format_parcel_summary(parcel) for parcel in filtered[: max(limit, 0)]]


@mcp.tool(name="parcel_summary")
def parcel_summary(identifier: str) -> Dict[str, Any]:
    """Provide a compact summary for a parcel by parcel ID or barcode."""

    parcels = get_client().list_parcels().get("parcels", [])
    for parcel in parcels:
        if _parcel_identifier_matches(parcel, identifier):
            return _format_parcel_summary(parcel)
    raise ValueError(f"Parcel '{identifier}' not found in live DHL data")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run()
