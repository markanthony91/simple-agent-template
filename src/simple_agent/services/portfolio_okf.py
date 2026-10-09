"""Pin the active portfolio OKF release to a local immutable Runtime snapshot."""

from __future__ import annotations

import io
import json
import os
import re
import stat
import urllib.parse
import urllib.request
import zipfile

from simple_agent.services.okf_store import PersistentOKFStore


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def configured() -> bool:
    url = os.getenv("PORTFOLIO_OKF_SERVICE_URL", "").strip()
    token = os.getenv("PORTFOLIO_OKF_SERVICE_TOKEN", "").strip()
    if bool(url) != bool(token):
        raise RuntimeError("portfolio_okf_service_configuration_incomplete")
    return bool(url)


def active_snapshot(scope_id: int, tenant_id: str) -> str | None:
    base = os.environ["PORTFOLIO_OKF_SERVICE_URL"].rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid_portfolio_okf_service_url")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", tenant_id):
        raise ValueError("invalid_portfolio_okf_tenant")
    prefix = f"{base}/v1/tenants/{urllib.parse.quote(tenant_id)}/portfolios/{scope_id}"
    token = os.environ["PORTFOLIO_OKF_SERVICE_TOKEN"]
    opener = urllib.request.build_opener(_NoRedirect)

    def get(path: str, limit: int) -> bytes:
        request = urllib.request.Request(
            prefix + path,
            headers={"Authorization": f"Bearer {token}"},
        )
        with opener.open(request, timeout=15) as response:
            payload = response.read(limit + 1)
            if len(payload) > limit:
                raise ValueError("portfolio_okf_response_too_large")
            return payload

    status = json.loads(get("/status", 100_000))["data"]
    remote_id = status.get("active_bundle_id")
    if not status.get("active") or not remote_id:
        return None
    if not isinstance(remote_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", remote_id
    ):
        raise ValueError("invalid_portfolio_okf_bundle_id")
    store = PersistentOKFStore()
    snapshot = store.portfolio_snapshot_id(scope_id, tenant_id, remote_id)
    try:
        store.bundle_root(snapshot)
        return snapshot
    except FileNotFoundError:
        pass
    payload = get(f"/bundles/{remote_id}/archive", 12_000_000)
    files: dict[str, str] = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if not members or len(members) > 2_000:
            raise ValueError("portfolio_okf_archive_file_limit")
        for member in members:
            if member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("unsafe_portfolio_okf_archive")
            path = store._safe_relative(member.filename)
            total += member.file_size
            if total > 10_000_000 or path in files:
                raise ValueError("portfolio_okf_archive_limit_or_duplicate")
            files[path] = archive.read(member).decode("utf-8")
    return store.cache_portfolio_bundle(snapshot, files)
