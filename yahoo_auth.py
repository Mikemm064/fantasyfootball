"""Server-side Yahoo OAuth helpers for the Streamlit application."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping
from urllib.parse import urlencode

import requests

AUTHORIZATION_ENDPOINT = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_ENDPOINT = "https://api.login.yahoo.com/oauth2/get_token"
FANTASY_TEST_ENDPOINT = (
    "https://fantasysports.yahooapis.com/fantasy/v2/"
    "users;use_login=1/games;game_codes=nfl"
)
REQUEST_TIMEOUT = 15
EXPIRY_SKEW_SECONDS = 60
STATE_SIGNING_CONTEXT = b"fantasy-draft-assistant-yahoo-state-v1"


class YahooAuthError(Exception):
    """An OAuth failure safe to report without exposing Yahoo response data."""


@dataclass(frozen=True)
class YahooCredentials:
    client_id: str
    client_secret: str
    redirect_uri: str


def credentials_from_secrets(streamlit_secrets: Mapping[str, Any]) -> YahooCredentials:
    """Read Yahoo credentials exclusively from Streamlit's secrets mapping."""
    try:
        yahoo = streamlit_secrets["yahoo"]
        values = YahooCredentials(
            client_id=str(yahoo["client_id"]).strip(),
            client_secret=str(yahoo["client_secret"]).strip(),
            redirect_uri=str(yahoo["redirect_uri"]).strip(),
        )
    except (KeyError, TypeError, AttributeError, FileNotFoundError) as exc:
        raise YahooAuthError("Yahoo authentication is not configured.") from exc
    if not all((values.client_id, values.client_secret, values.redirect_uri)):
        raise YahooAuthError("Yahoo authentication is not configured.")
    return values


def _state_signing_key(credentials: YahooCredentials) -> bytes:
    """Derive a purpose-specific state key without exposing the client secret."""
    return hmac.new(
        credentials.client_secret.encode(), STATE_SIGNING_CONTEXT, hashlib.sha256
    ).digest()


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    if not value or "=" in value:
        raise ValueError("invalid base64")
    return base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )


def new_signed_state(credentials: YahooCredentials) -> str:
    """Create a self-contained, authenticated OAuth state value."""
    payload = json.dumps(
        {"nonce": secrets.token_urlsafe(32), "iat": int(time.time())},
        separators=(",", ":"), sort_keys=True,
    ).encode()
    signature = hmac.new(_state_signing_key(credentials), payload, hashlib.sha256).digest()
    return f"{_urlsafe_encode(payload)}.{_urlsafe_encode(signature)}"


def validate_signed_state(
    credentials: YahooCredentials, state: str | None, max_age_seconds: int = 600
) -> bool:
    """Validate state authenticity and age without relying on browser session data."""
    if not isinstance(state, str) or max_age_seconds < 0:
        return False
    try:
        payload_part, signature_part = state.split(".")
        payload = _urlsafe_decode(payload_part)
        signature = _urlsafe_decode(signature_part)
        expected = hmac.new(_state_signing_key(credentials), payload, hashlib.sha256).digest()
        if len(signature) != hashlib.sha256().digest_size or not hmac.compare_digest(
            signature, expected
        ):
            return False
        decoded = json.loads(payload.decode())
        if set(decoded) != {"nonce", "iat"}:
            return False
        nonce, issued_at = decoded["nonce"], decoded["iat"]
        if not isinstance(nonce, str) or len(nonce) < 32:
            return False
        if not isinstance(issued_at, int) or isinstance(issued_at, bool):
            return False
        age = int(time.time()) - issued_at
        return 0 <= age <= max_age_seconds
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return False


def authorization_url(credentials: YahooCredentials, state: str) -> str:
    params = urlencode({
        "client_id": credentials.client_id,
        "redirect_uri": credentials.redirect_uri,
        "response_type": "code",
        "state": state,
    })
    return f"{AUTHORIZATION_ENDPOINT}?{params}"


def _basic_authorization(credentials: YahooCredentials) -> str:
    raw = f"{credentials.client_id}:{credentials.client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _token_request(credentials: YahooCredentials, data: dict[str, str]) -> dict[str, Any]:
    try:
        response = requests.post(
            TOKEN_ENDPOINT,
            data=data,
            headers={
                "Authorization": _basic_authorization(credentials),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else None
        category = f"HTTP {status}" if status in (401, 403) else "request_rejected"
        if response is not None:
            try:
                error = response.json().get("error")
            except (ValueError, AttributeError):
                error = None
            if error in {"invalid_grant", "invalid_client"}:
                category = error
        raise YahooAuthError(f"Yahoo token request failed: {category}.") from exc
    except (requests.RequestException, ValueError) as exc:
        raise YahooAuthError("Yahoo authentication could not be completed. Please try again.") from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise YahooAuthError("Yahoo authentication returned an invalid response. Please try again.")
    return payload


def _active_token(payload: Mapping[str, Any], previous_refresh_token: str | None = None) -> dict[str, Any]:
    """Reduce a token response to the server-side fields needed by this session."""
    try:
        expires_in = max(0, int(payload.get("expires_in", 3600)))
    except (TypeError, ValueError):
        expires_in = 3600
    refresh_token = payload.get("refresh_token") or previous_refresh_token
    return {
        "access_token": str(payload["access_token"]),
        "refresh_token": str(refresh_token) if refresh_token else None,
        "token_type": str(payload.get("token_type", "bearer")),
        "expires_at": time.time() + expires_in,
    }


def exchange_code(credentials: YahooCredentials, code: str) -> dict[str, Any]:
    payload = _token_request(credentials, {
        "grant_type": "authorization_code",
        "redirect_uri": credentials.redirect_uri,
        "code": code,
    })
    return _active_token(payload)


def refresh_access_token(credentials: YahooCredentials, token: Mapping[str, Any]) -> dict[str, Any]:
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise YahooAuthError("The Yahoo session expired. Please connect again.")
    payload = _token_request(credentials, {
        "grant_type": "refresh_token",
        "redirect_uri": credentials.redirect_uri,
        "refresh_token": str(refresh_token),
    })
    # Yahoo may rotate the refresh token. Preserve the old value only when it does not.
    return _active_token(payload, str(refresh_token))


def ensure_fresh_token(
    credentials: YahooCredentials,
    session: MutableMapping[str, Any],
    now: float | None = None,
) -> dict[str, Any]:
    token = session.get("yahoo_token")
    if not isinstance(token, dict) or not token.get("access_token"):
        raise YahooAuthError("Yahoo is not connected.")
    current_time = time.time() if now is None else now
    if current_time >= float(token.get("expires_at", 0)) - EXPIRY_SKEW_SECONDS:
        token = refresh_access_token(credentials, token)
        session["yahoo_token"] = token
    return token


def verify_fantasy_access(credentials: YahooCredentials, session: MutableMapping[str, Any]) -> bool:
    """Make one read-only request proving the user can access Yahoo fantasy football."""
    token = ensure_fresh_token(credentials, session)
    try:
        response = requests.get(
            FANTASY_TEST_ENDPOINT,
            params={"format": "json"},
            headers={"Authorization": f"Bearer {token['access_token']}"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise YahooAuthError("Yahoo connected, but Fantasy Football access could not be verified.") from exc
    return True
