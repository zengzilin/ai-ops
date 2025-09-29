from __future__ import annotations

import json as _json
import time
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.config import SETTINGS

logger = logging.getLogger(__name__)


# Shared HTTP client with connection pooling and keep-alive
_HTTP_CLIENT: Optional[httpx.Client] = None


def _get_http_client() -> httpx.Client:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.Client(
            timeout=httpx.Timeout(connect=30, read=60, write=30, pool=30),  # 增加超时时间
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            headers={"User-Agent": "ai-ops-http/1.0"},
            verify=False,  # 禁用SSL验证以避免证书问题
        )
    return _HTTP_CLIENT


def _make_request(
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 15,
    auth: Optional[tuple[str, str]] = None,
    max_retries: int = None,
) -> Tuple[int, Any]:
    max_retries = max_retries or SETTINGS.max_retries
    retry_delay = SETTINGS.retry_delay

    req_headers = headers.copy() if headers else {}
    # httpx will set content-type automatically for json kwarg

    client = _get_http_client()

    for attempt in range(max_retries + 1):
        try:
            resp = client.request(
                method.upper(),
                url,
                params={k: v for k, v in (params or {}).items() if v is not None} or None,
                json=json,
                headers=req_headers or None,
                timeout=timeout,
                auth=auth,
            )
            status = resp.status_code
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    return status, resp.json()
                except Exception:
                    return status, resp.text
            return status, resp.text
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else 599
            body = e.response.text if e.response is not None else str(e)
            if attempt == max_retries:
                logger.error(f"HTTP {method} failed after {max_retries + 1} attempts: {status} {body}")
                return status, body
            logger.warning(f"HTTP {method} attempt {attempt + 1} failed: {status}, retrying...")
            time.sleep(retry_delay * (2 ** attempt))
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"Request {method} {url} failed after {max_retries + 1} attempts: {e}")
                return 599, str(e)
            logger.warning(f"Request {method} {url} attempt {attempt + 1} failed: {e}, retrying...")
            time.sleep(retry_delay * (2 ** attempt))


def http_get(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 15, auth: Optional[tuple[str, str]] = None, max_retries: int = None):
    return _make_request("GET", url, params=params, headers=headers, timeout=timeout, auth=auth, max_retries=max_retries)


def http_post(url: str, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 15, auth: Optional[tuple[str, str]] = None, max_retries: int = None):
    return _make_request("POST", url, json=json, headers=headers, timeout=timeout, auth=auth, max_retries=max_retries)


def http_head(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 15, auth: Optional[tuple[str, str]] = None, max_retries: int = None):
    return _make_request("HEAD", url, headers=headers, timeout=timeout, auth=auth, max_retries=max_retries)


def http_put(url: str, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 15, auth: Optional[tuple[str, str]] = None, max_retries: int = None):
    return _make_request("PUT", url, json=json, headers=headers, timeout=timeout, auth=auth, max_retries=max_retries)


