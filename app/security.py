"""Security primitives: path containment and loopback request validation."""

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from app import config
from app.config import DASHBOARD_DIR, HOME_DIR

HOME = HOME_DIR
DASHBOARD_ROOT = DASHBOARD_DIR

SYSTEM_DENY_ROOTS = [
    Path("/etc").resolve(),
    Path("/root").resolve(),
    Path("/usr").resolve(),
    Path("/var").resolve(),
    Path("/bin").resolve(),
    Path("/sbin").resolve(),
    Path("/lib").resolve(),
    Path("/lib64").resolve(),
    Path("/boot").resolve(),
    Path("/dev").resolve(),
    Path("/proc").resolve(),
    Path("/sys").resolve(),
    Path("/run").resolve(),
]


def allowed_roots() -> list:
    roots = [DASHBOARD_ROOT]
    if config.WORKSPACE_ROOT is not None:
        roots.append(config.WORKSPACE_ROOT)
    return roots


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_system_denied_path(path: Path) -> bool:
    return any(path == root or is_relative_to(path, root) for root in SYSTEM_DENY_ROOTS)


def ensure_allowed_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if is_system_denied_path(resolved):
        raise ValueError("path is outside the allowed scope")
    if any(is_relative_to(resolved, root) for root in allowed_roots()):
        return resolved
    raise ValueError("path is outside the allowed scope")


def ensure_path_under_root(path: Path, root: Path, error_message: str = "path is outside the allowed scope") -> Path:
    raw_root = root.expanduser()
    # A caller may otherwise validate a path relative to a symlinked root:
    # both root.resolve() and path.resolve() would follow the same link and
    # make an escape outside the intended workspace appear contained.
    if raw_root.is_symlink():
        raise ValueError(error_message)
    resolved_root = raw_root.resolve()
    resolved = path.expanduser().resolve()
    if is_system_denied_path(resolved):
        raise ValueError(error_message)
    if is_relative_to(resolved, resolved_root):
        return resolved
    raise ValueError(error_message)


def is_loopback_hostname(hostname: str) -> bool:
    """True for localhost and any loopback address (127.0.0.0/8, ::1)."""
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def check_loopback_host(host_header: str) -> bool:
    """Validate an HTTP Host header for the loopback-only trust model."""
    value = (host_header or "").strip()
    if not value:
        return False
    try:
        parts = urlsplit(f"//{value}")
        if parts.username is not None or parts.password is not None:
            return False
        # Accessing .port validates malformed/non-numeric port values.
        _ = parts.port
    except ValueError:
        return False
    return parts.hostname is not None and is_loopback_hostname(parts.hostname)


def check_same_origin(origin: str, host_header: str, sec_fetch_site: str | None = None) -> bool:
    """Accept a browser Origin only when it matches a loopback Host.

    The dashboard has no authentication and binds to loopback, so the
    only legitimate browser origin is the dashboard itself (via SSH
    port forwarding the browser still talks to 127.0.0.1:some-port).
    Requiring a loopback hostname also defeats DNS-rebinding, where an
    attacker page reloads ``http://evil.example:7860`` onto 127.0.0.1
    and would otherwise match the Host header.

    Chrome 151+ serializes the Origin of loopback pages as the literal
    string "null" even for same-origin form POSTs. Accept that only
    when the browser's Fetch Metadata (``Sec-Fetch-Site: same-origin``,
    which scripts cannot forge) attests a true same-origin request and
    the Host is still loopback. Every other null-Origin request
    (cross-site, same-site, or missing metadata) stays rejected.
    """
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if parts.netloc.lower() == host_header.strip().lower():
        return check_loopback_host(host_header)
    if origin == "null" and sec_fetch_site == "same-origin":
        return check_loopback_host(host_header)
    return False
