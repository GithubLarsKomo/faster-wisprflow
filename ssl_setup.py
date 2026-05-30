"""
Enterprise TLS/SSL bootstrap for PyInstaller Windows executables.

Handles Cisco Secure Client / Umbrella / corporate TLS inspection by routing
SSL verification through the Windows Trust Store instead of the bundled certifi
CA bundle.

Usage
-----
Call ``ssl_setup.init()`` as the very first statement in ``__main__``,
*before* any import that may trigger HTTP traffic::

    import ssl_setup
    ssl_setup.init()

Strategy cascade (first that succeeds wins):
  1. ``truststore`` — patches ``ssl.SSLContext`` via OS-native APIs.  No temp
     files, no certifi dependency, fully transparent to ``requests``.
  2. ``pip-system-certs`` — patches ``certifi.where()`` to return a PEM built
     from the Windows cert store (legacy fallback, requires the package).
  3. Manual export — calls ``ssl.enum_certificates()`` (stdlib), writes a temp
     PEM, and sets ``REQUESTS_CA_BUNDLE`` + ``SSL_CERT_FILE``.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import socket
import ssl
import sys
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("ssl_setup")

# ── module-level state ────────────────────────────────────────────────────────
_ACTIVE_METHODS: list[str] = []
_EXTRA_CA_BUNDLE: Path | None = None   # set when strategy 3 runs


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def init(verbose: bool = False) -> list[str]:
    """Patch the SSL stack to use the Windows Trust Store.

    Safe to call multiple times — subsequent calls are no-ops.
    Returns the list of strategies that were successfully applied.
    """
    global _ACTIVE_METHODS, _EXTRA_CA_BUNDLE

    if _ACTIVE_METHODS:
        return _ACTIVE_METHODS      # already initialised

    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)-8s %(name)s: %(message)s",
        )

    # ── Strategy 1: truststore ─────────────────────────────────────────────
    if _try_truststore():
        _ACTIVE_METHODS.append("truststore")

    # ── Strategy 2: pip-system-certs ──────────────────────────────────────
    if not _ACTIVE_METHODS and _try_pip_system_certs():
        _ACTIVE_METHODS.append("pip-system-certs")

    # ── Strategy 3: stdlib ssl.enum_certificates() export ─────────────────
    if not _ACTIVE_METHODS:
        bundle = _export_windows_certs_to_pem()
        if bundle:
            os.environ["REQUESTS_CA_BUNDLE"] = str(bundle)
            os.environ["SSL_CERT_FILE"] = str(bundle)
            _EXTRA_CA_BUNDLE = bundle
            _ACTIVE_METHODS.append("windows-cert-export")
            log.info("SSL: using manually exported Windows cert bundle: %s", bundle)

    # ── diagnostic summary ─────────────────────────────────────────────────
    if _ACTIVE_METHODS:
        log.info("SSL init OK — strategies applied: %s", _ACTIVE_METHODS)
    else:
        log.warning(
            "SSL: no Windows Trust Store integration succeeded. "
            "Corporate TLS inspection may cause SSLCertVerificationError."
        )

    _log_cert_paths()
    _log_proxy_env()

    return list(_ACTIVE_METHODS)


def diagnose(
    target_url: str = "https://openrouter.ai/api/v1/models",
) -> dict[str, Any]:
    """Runtime SSL / proxy / connectivity diagnostic.

    Returns a structured dict; also pretty-prints findings to the log.
    Call this from a --ssl-diagnose CLI flag or a settings-dialog button.
    """
    result: dict[str, Any] = {
        "active_methods": list(_ACTIVE_METHODS),
        "python_version": sys.version,
        "frozen": getattr(sys, "frozen", False),
        "certifi_where": None,
        "requests_ca_bundle": os.environ.get("REQUESTS_CA_BUNDLE"),
        "ssl_cert_file": os.environ.get("SSL_CERT_FILE"),
        "ssl_cert_dir": os.environ.get("SSL_CERT_DIR"),
        "proxy_env": _collect_proxy_env(),
        "tls_inspection_detected": False,
        "cert_issuer": None,
        "connection_test": {},
    }

    try:
        import certifi
        result["certifi_where"] = certifi.where()
    except ImportError:
        pass

    # ── connectivity test ──────────────────────────────────────────────────
    try:
        import requests
        resp = requests.get(target_url, timeout=10)
        result["connection_test"] = {
            "url": target_url,
            "status": resp.status_code,
            "ok": resp.ok,
        }
    except Exception as exc:
        result["connection_test"] = {"url": target_url, "error": str(exc)}

    # ── TLS inspection detection ───────────────────────────────────────────
    try:
        host = target_url.split("/")[2]
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert()
                issuer = {k: v for tup in cert.get("issuer", []) for k, v in tup}
                org = issuer.get("organizationName", "")
                result["cert_issuer"] = issuer
                _INSPECTION_KEYWORDS = (
                    "cisco", "umbrella", "zscaler", "symantec", "netskope",
                    "bluecoat", "forcepoint", "inspect", "intercept", "proxy",
                    "websense", "mcafee", "sophos", "palo alto",
                )
                if any(kw in org.lower() for kw in _INSPECTION_KEYWORDS):
                    result["tls_inspection_detected"] = True
                    log.warning(
                        "SSL diagnose: TLS inspection DETECTED — issuer org: %r", org
                    )
    except Exception as exc:
        result["cert_check_error"] = str(exc)

    log.info("SSL diagnose:\n%s", json.dumps(result, indent=2, default=str))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Strategy implementations
# ─────────────────────────────────────────────────────────────────────────────

def _try_truststore() -> bool:
    """Inject Windows Trust Store into ssl.SSLContext via truststore package."""
    try:
        import truststore  # type: ignore[import-untyped]
        truststore.inject_into_ssl()
        log.info("SSL: truststore.inject_into_ssl() OK")
        return True
    except ImportError:
        log.debug("SSL: truststore not installed")
    except Exception as exc:
        log.warning("SSL: truststore injection failed: %s", exc)
    return False


def _try_pip_system_certs() -> bool:
    """Patch certifi.where() via pip-system-certs."""
    try:
        import pip_system_certs.wrapt_ssl  # type: ignore[import-untyped]  # noqa: F401
        log.info("SSL: pip-system-certs active (certifi.where() patched)")
        return True
    except ImportError:
        log.debug("SSL: pip-system-certs not installed")
    except Exception as exc:
        log.warning("SSL: pip-system-certs activation failed: %s", exc)
    return False


def _export_windows_certs_to_pem() -> Path | None:
    """
    Export DER certificates from Windows Trust Stores ROOT, CA and MY to a
    single PEM temp file using only the Python stdlib.

    Requires Windows (ssl.enum_certificates is win32-only).
    """
    if not hasattr(ssl, "enum_certificates"):
        log.debug("SSL: ssl.enum_certificates not available (non-Windows?)")
        return None

    pem_certs: list[str] = []
    for store_name in ("ROOT", "CA", "MY"):
        try:
            for cert_der, _enc_type, _trust in ssl.enum_certificates(store_name):
                b64 = base64.encodebytes(cert_der).decode("ascii")
                pem_certs.append(
                    "-----BEGIN CERTIFICATE-----\n"
                    + b64
                    + "-----END CERTIFICATE-----"
                )
        except OSError as exc:
            log.debug("SSL: enum_certificates(%r) error: %s", store_name, exc)

    if not pem_certs:
        log.warning("SSL: no certificates retrieved from Windows Trust Store")
        return None

    try:
        fd, tmp_path = tempfile.mkstemp(prefix="flusterfee_ca_", suffix=".pem")
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write("\n\n".join(pem_certs) + "\n")
        log.info(
            "SSL: exported %d certs from Windows Trust Store → %s",
            len(pem_certs),
            tmp_path,
        )
        return Path(tmp_path)
    except Exception as exc:
        log.error("SSL: failed to write Windows cert PEM: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Logging helpers
# ─────────────────────────────────────────────────────────────────────────────

def _log_cert_paths() -> None:
    try:
        import certifi
        log.info("SSL: certifi.where()       = %s", certifi.where())
    except ImportError:
        log.info("SSL: certifi               = not installed")
    log.info(
        "SSL: REQUESTS_CA_BUNDLE    = %s",
        os.environ.get("REQUESTS_CA_BUNDLE", "(unset)"),
    )
    log.info(
        "SSL: SSL_CERT_FILE         = %s",
        os.environ.get("SSL_CERT_FILE", "(unset)"),
    )


def _log_proxy_env() -> None:
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY"):
        val = os.environ.get(var)
        if val:
            log.info("SSL: proxy env  %-20s = %s", var, val)


def _collect_proxy_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY"):
        val = os.environ.get(var)
        if val:
            out[var] = val
    return out
