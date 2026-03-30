"""Optional GitHub Copilot API summarization helpers for A365 package rows."""

import json
import os
import random
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from Core.spinner import _stdout_lock, get_timestamp


DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_API_URL = "https://models.inference.ai.azure.com/chat/completions"
MAX_RETRIES = 3
DEFAULT_MAX_CALLS = 120


_state_lock = threading.Lock()
_cached_token = None
_cached_source = None
_api_disabled = False
_api_failure_announced = False
_next_allowed_time = 0.0
_cooldown_announced = False
_consecutive_429 = 0
_summaries_requested = 0
_summary_cache = {}


def _get_env_token():
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_MODELS_TOKEN"):
        value = os.getenv(key, "").strip()
        if value:
            return value, key
    return "", ""


def _get_gh_cli_token():
    """Best-effort token discovery from GitHub CLI auth context."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip(), "gh auth token"
    except Exception:
        pass
    return "", ""


def _get_token_cached():
    global _cached_token, _cached_source

    with _state_lock:
        if _cached_token is not None:
            return _cached_token, _cached_source

    token, source = _get_env_token()
    if not token:
        token, source = _get_gh_cli_token()

    with _state_lock:
        _cached_token = token
        _cached_source = source

    return token, source


def get_runtime_mode():
    """Return summarization mode details for console messaging."""
    token, source = _get_token_cached()
    if token:
        return {
            "enabled": True,
            "source": source,
            "model": DEFAULT_MODEL,
            "endpoint": DEFAULT_API_URL,
        }
    return {
        "enabled": False,
        "reason": "No GitHub token found in env or GitHub CLI auth context",
    }


def _extract_text(response_json):
    try:
        return response_json["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


def _parse_retry_after(headers):
    """Return retry delay in seconds from Retry-After header when possible."""
    raw = (headers or {}).get("Retry-After")
    if not raw:
        return None

    try:
        seconds = float(str(raw).strip())
        if seconds >= 0:
            return seconds
    except Exception:
        pass

    try:
        dt = parsedate_to_datetime(str(raw).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (dt - now).total_seconds())
    except Exception:
        return None


def _cache_key(package_row):
    if not isinstance(package_row, dict):
        return None

    package_id = str(package_row.get("id") or package_row.get("packageId") or "").strip()
    package_name = str(package_row.get("displayName") or package_row.get("name") or "").strip()
    package_status = str(package_row.get("status") or "").strip()

    if not package_id and not package_name:
        return None
    return f"{package_id}|{package_name}|{package_status}"


def _normalize_package_input(package_row):
    safe_payload = package_row if isinstance(package_row, dict) else {}
    return {
        "packageName": safe_payload.get("displayName") or safe_payload.get("name") or safe_payload.get("title") or "Unknown",
        "packageId": safe_payload.get("id") or safe_payload.get("packageId") or "Unknown",
        "typeOrCategory": safe_payload.get("type") or safe_payload.get("category") or "Unspecified",
        "status": safe_payload.get("status") or "Unknown",
        "publisher": safe_payload.get("publisher") or "Unknown",
        "tags": safe_payload.get("tags") if isinstance(safe_payload.get("tags"), list) else safe_payload.get("tags") or [],
        "purpose": safe_payload.get("description") or safe_payload.get("shortDescription") or safe_payload.get("summary") or "Unknown",
        "createdOrPublished": safe_payload.get("createdDateTime") or safe_payload.get("createdAt") or safe_payload.get("publishedDateTime") or safe_payload.get("lastModifiedDateTime") or "Unknown",
        "platform": safe_payload.get("platform") or safe_payload.get("platforms") or safe_payload.get("runtime") or safe_payload.get("supportedClients") or safe_payload.get("supportedPlatforms") or safe_payload.get("hostProducts") or [],
    }


def _extract_json_block(text):
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\\s*", "", stripped)
        stripped = re.sub(r"\\s*```$", "", stripped)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start:end + 1]
    return stripped


def _request_bulk_chunk(client, headers, chunk_payload):
    request_body = {
        "model": DEFAULT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You summarize Microsoft 365 Copilot catalog package metadata for readiness reports. "
                    "Return JSON only in the format {\"summaries\":[{\"index\":<int>,\"summary\":<string>}]} with one entry per input row. "
                    "Each summary must be exactly 4 short lines:\n"
                    "1) Package: ...\n"
                    "2) Purpose/capability: ...\n"
                    "3) Lifecycle/platform: ...\n"
                    "4) Status/risk signal: ...\n"
                    "Do not include markdown or explanations outside JSON."
                ),
            },
            {
                "role": "user",
                "content": "Summarize these package rows:\n" + json.dumps({"rows": chunk_payload}, ensure_ascii=True),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 1200,
    }

    for attempt in range(MAX_RETRIES):
        response = client.post(DEFAULT_API_URL, json=request_body, headers=headers)

        if response.status_code < 400:
            text = _extract_text(response.json())
            json_text = _extract_json_block(text)
            try:
                parsed = json.loads(json_text or "{}")
                rows = parsed.get("summaries")
                if isinstance(rows, list):
                    return {"ok": True, "rows": rows}
            except Exception:
                pass
            return {"ok": True, "rows": []}

        if response.status_code == 429 or 500 <= response.status_code <= 599:
            if attempt < (MAX_RETRIES - 1):
                retry_after = _parse_retry_after(response.headers)
                if retry_after is not None:
                    wait_seconds = retry_after
                else:
                    wait_seconds = (1.5 * (attempt + 1)) + random.uniform(0.0, 0.8)
                time.sleep(max(0.5, min(wait_seconds, 8.0)))
                continue

        return {"ok": False, "status_code": response.status_code, "headers": dict(response.headers)}

    return {"ok": False, "status_code": 500, "headers": {}}


def summarize_package_rows_bulk(package_rows, chunk_size=25, progress_callback=None):
    """Bulk summarize package rows in chunks; returns {row_index: summary_text}."""
    global _api_disabled, _api_failure_announced, _next_allowed_time
    global _cooldown_announced, _consecutive_429, _summaries_requested

    if _api_disabled:
        return {}

    token, _ = _get_token_cached()
    if not token:
        return {}

    rows = package_rows if isinstance(package_rows, list) else []
    if not rows:
        return {}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        max_calls = int(os.getenv("A365_SUMMARY_MAX_CALLS", str(DEFAULT_MAX_CALLS)) or DEFAULT_MAX_CALLS)
    except Exception:
        max_calls = DEFAULT_MAX_CALLS

    size = max(5, min(100, int(chunk_size or 25)))
    results = {}
    total_chunks = (len(rows) + size - 1) // size
    completed_chunks = 0

    if callable(progress_callback):
        try:
            progress_callback(0, total_chunks)
        except Exception:
            pass

    with httpx.Client(timeout=45.0) as client:
        for start in range(0, len(rows), size):
            now = time.monotonic()
            with _state_lock:
                blocked_until = _next_allowed_time
                should_announce_cooldown = not _cooldown_announced
                exhausted = _summaries_requested >= max_calls

            if exhausted:
                break

            if now < blocked_until:
                if should_announce_cooldown:
                    remaining = max(0.0, blocked_until - now)
                    with _stdout_lock:
                        print(
                            f"\n[{get_timestamp()}] [WARN] A365 Copilot bulk summarization cooling down for {remaining:.1f}s; using fallback summaries for this window."
                        )
                    with _state_lock:
                        _cooldown_announced = True
                continue

            chunk = rows[start:start + size]
            chunk_payload = []
            for offset, package_row in enumerate(chunk):
                absolute_index = start + offset
                normalized = _normalize_package_input(package_row)
                normalized["index"] = absolute_index
                chunk_payload.append(normalized)

            with _state_lock:
                _summaries_requested += 1

            result = _request_bulk_chunk(client, headers, chunk_payload)
            if result.get("ok"):
                for item in result.get("rows", []):
                    try:
                        idx = int(item.get("index"))
                    except Exception:
                        continue
                    summary = str(item.get("summary") or "").strip()
                    if not summary:
                        continue
                    results[idx] = summary

                    if 0 <= idx < len(rows):
                        key = _cache_key(rows[idx])
                        if key:
                            with _state_lock:
                                _summary_cache[key] = summary

                with _state_lock:
                    _consecutive_429 = 0
                    _next_allowed_time = 0.0
                    _cooldown_announced = False
                    _api_failure_announced = False

                completed_chunks += 1
                if callable(progress_callback):
                    try:
                        progress_callback(completed_chunks, total_chunks)
                    except Exception:
                        pass
                continue

            status_code = int(result.get("status_code") or 0)
            headers_map = result.get("headers") or {}
            if status_code == 429:
                retry_after = _parse_retry_after(headers_map)
                with _state_lock:
                    _consecutive_429 += 1
                    _cooldown_announced = False
                    cooldown = retry_after
                    if cooldown is None:
                        cooldown = min(20.0, 2.0 * (2 ** min(_consecutive_429 - 1, 3))) + random.uniform(0.0, 1.0)
                    _next_allowed_time = time.monotonic() + max(1.0, cooldown)
                    should_announce = not _api_failure_announced
                    _api_failure_announced = True
                if should_announce:
                    with _stdout_lock:
                        print(
                            f"\n[{get_timestamp()}] [WARN] A365 Copilot bulk summarization is being rate limited (HTTP 429); using fallback summaries until cooldown ends."
                        )

                completed_chunks += 1
                if callable(progress_callback):
                    try:
                        progress_callback(completed_chunks, total_chunks)
                    except Exception:
                        pass
                continue

            with _state_lock:
                _api_disabled = True
                should_announce = not _api_failure_announced
                _api_failure_announced = True
            if should_announce:
                with _stdout_lock:
                    print(
                        f"\n[{get_timestamp()}] [WARN] A365 Copilot bulk summarization disabled after API HTTP {status_code}; using fallback summaries."
                    )

            completed_chunks += 1
            if callable(progress_callback):
                try:
                    progress_callback(completed_chunks, total_chunks)
                except Exception:
                    pass
            break

    return results


def summarize_package_row(package_row):
    """Return a 2-3 line summary for a package row using GitHub Copilot API.

    Uses implicit token discovery from environment variables or GitHub CLI auth.
    """
    global _api_disabled, _api_failure_announced, _next_allowed_time
    global _cooldown_announced, _consecutive_429, _summaries_requested

    if _api_disabled:
        return None

    token, _ = _get_token_cached()
    if not token:
        return None

    key = _cache_key(package_row)
    if key:
        with _state_lock:
            cached = _summary_cache.get(key)
        if cached:
            return cached

    now = time.monotonic()
    with _state_lock:
        blocked_until = _next_allowed_time
        should_announce_cooldown = not _cooldown_announced

    if now < blocked_until:
        if should_announce_cooldown:
            remaining = max(0.0, blocked_until - now)
            with _stdout_lock:
                print(
                    f"\n[{get_timestamp()}] [WARN] A365 Copilot summarization cooling down for {remaining:.1f}s after rate limiting; using fallback summaries meanwhile."
                )
            with _state_lock:
                _cooldown_announced = True
        return None

    try:
        max_calls = int(os.getenv("A365_SUMMARY_MAX_CALLS", str(DEFAULT_MAX_CALLS)) or DEFAULT_MAX_CALLS)
    except Exception:
        max_calls = DEFAULT_MAX_CALLS
    with _state_lock:
        if _summaries_requested >= max_calls:
            return None
        _summaries_requested += 1

    normalized_input = _normalize_package_input(package_row)
    payload_text = json.dumps(normalized_input, ensure_ascii=True)

    request_body = {
        "model": DEFAULT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You summarize Microsoft 365 Copilot catalog package metadata for readiness reports. "
                    "Return exactly 4 short lines, plain text only, no markdown, no bullets. "
                    "Line 1 must start with 'Package:' and include package name, type/category, and identifier. "
                    "Line 2 must start with 'Purpose/capability:' and explain what it does from available fields. "
                    "Line 3 must start with 'Lifecycle/platform:' and include created/published timing and runtime/platform when present. "
                    "Line 4 must start with 'Status/risk signal:' and summarize status risk from metadata only. "
                    "Never ask for more details, never say information is missing, and never use placeholders like 'not provided'."
                )
            },
            {
                "role": "user",
                "content": f"Summarize this package row for enterprise readers:\n{payload_text}"
            },
        ],
        "temperature": 0.2,
        "max_tokens": 180,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            for attempt in range(MAX_RETRIES):
                response = client.post(DEFAULT_API_URL, json=request_body, headers=headers)

                if response.status_code < 400:
                    text = _extract_text(response.json())
                    if text:
                        if key:
                            with _state_lock:
                                _summary_cache[key] = text
                        with _state_lock:
                            _consecutive_429 = 0
                            _next_allowed_time = 0.0
                            _cooldown_announced = False
                            _api_failure_announced = False
                        return text
                    return None

                # Retry rate limit and transient server errors with backoff.
                if response.status_code == 429 or 500 <= response.status_code <= 599:
                    if attempt < (MAX_RETRIES - 1):
                        retry_after = _parse_retry_after(response.headers)
                        if retry_after is not None:
                            wait_seconds = retry_after
                        else:
                            base_wait = 1.5 * (attempt + 1)
                            jitter = random.uniform(0.0, 0.8)
                            wait_seconds = base_wait + jitter
                        time.sleep(max(0.5, min(wait_seconds, 8.0)))
                        continue

                if response.status_code == 429:
                    retry_after = _parse_retry_after(response.headers)
                    with _state_lock:
                        _consecutive_429 += 1
                        _cooldown_announced = False
                        cooldown = retry_after
                        if cooldown is None:
                            # Escalating cooldown when retry-after is unavailable.
                            cooldown = min(20.0, 2.0 * (2 ** min(_consecutive_429 - 1, 3))) + random.uniform(0.0, 1.0)
                        _next_allowed_time = time.monotonic() + max(1.0, cooldown)

                    with _state_lock:
                        should_announce = not _api_failure_announced
                        _api_failure_announced = True
                    if should_announce:
                        with _stdout_lock:
                            print(
                                f"\n[{get_timestamp()}] [WARN] A365 Copilot summarization is being rate limited (HTTP 429); temporarily using fallback summaries with adaptive cooldown."
                            )
                    return None

                with _state_lock:
                    _api_disabled = True
                    should_announce = not _api_failure_announced
                    _api_failure_announced = True
                if should_announce:
                    with _stdout_lock:
                        print(
                            f"\n[{get_timestamp()}] [WARN] A365 Copilot summarization disabled after API HTTP {response.status_code}; using fallback summaries."
                        )
                return None
    except Exception:
        with _state_lock:
            _api_disabled = True
            should_announce = not _api_failure_announced
            _api_failure_announced = True
        if should_announce:
            with _stdout_lock:
                print(f"\n[{get_timestamp()}] [WARN] A365 Copilot summarization call failed; using fallback summaries.")
        return None
