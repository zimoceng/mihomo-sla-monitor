"""Day 2.4: persistent, runtime-editable SLA probe settings.

No database migration. No authentication (LAN/SSH use only).
Collector reads current_settings() each cycle; writes are atomic.
"""
import ipaddress
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/settings", tags=["Day 2.4 probe settings"])
SETTINGS_FILE = Path(os.getenv("SLA_PROBE_SETTINGS_FILE", str(Path(__file__).resolve().parent / "probe-settings.json")))
_lock = threading.RLock()


def _defaults():
    return {
        "probe_url": os.getenv("SLA_PROBE_URL", "https://www.gstatic.com/generate_204"),
        "interval_seconds": max(30, int(os.getenv("SLA_INTERVAL", "60"))),
        "timeout_ms": max(1000, int(os.getenv("SLA_TIMEOUT_MS", "5000"))),
    }


def _validate_url(value):
    if not isinstance(value, str) or not value or len(value) > 500 or any(ord(ch) < 32 for ch in value):
        raise ValueError("探测 URL 必须是长度不超过 500 的 HTTPS 地址")
    if value != value.strip():
        raise ValueError("URL 两端不能有空白字符")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ValueError("URL 端口格式不正确") from exc
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("仅支持不含账号、密码或 # 片段的 HTTPS URL")
    if port not in (None, 443):
        raise ValueError("仅允许 HTTPS 默认端口 443")
    host = parts.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa", ".svc", ".onion")):
        raise ValueError("不允许内网或本机域名")
    try:
        # Literal IPs are not supported, even when apparently public.
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("请使用公共 HTTPS 域名，不允许 IP 地址")
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", host):
        raise ValueError("请输入有效的公共域名")
    return value


def _checked(config):
    if not isinstance(config, dict):
        raise ValueError("设置文件不是 JSON 对象")
    url = _validate_url(config.get("probe_url"))
    interval = config.get("interval_seconds")
    timeout = config.get("timeout_ms")
    if type(interval) is not int or not 30 <= interval <= 3600:
        raise ValueError("检测间隔必须是 30–3600 秒的整数")
    if type(timeout) is not int or not 1000 <= timeout <= 30000:
        raise ValueError("超时时间必须是 1000–30000 毫秒的整数")
    return {"probe_url": url, "interval_seconds": interval, "timeout_ms": timeout}


def _read_file():
    if not SETTINGS_FILE.exists():
        return _checked(_defaults()), "default", None
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return _checked(saved), "file", saved.get("saved_at")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Invalid persisted config must not stop the collector on boot.
        print(f"[probe-settings] invalid config, using defaults: {type(exc).__name__}", flush=True)
        return _checked(_defaults()), "default (file invalid)", None


_with_metadata = None
with _lock:
    _with_metadata = _read_file()


def current_settings():
    """Return an immutable-by-copy snapshot for one entire probe round."""
    with _lock:
        return dict(_with_metadata[0])


def _view():
    with _lock:
        config, source, saved_at = _with_metadata
        return {**config, "source": source, "saved_at": saved_at, "effective": "next_round"}


class ProbeSettingsRequest(BaseModel):
    probe_url: str = Field(min_length=1, max_length=500)
    interval_seconds: int = Field(ge=30, le=3600)
    timeout_ms: int = Field(ge=1000, le=30000)


@router.get("/probe")
def get_probe_settings():
    return _view()


@router.post("/probe")
def save_probe_settings(payload: ProbeSettingsRequest):
    try:
        settings = _checked(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    saved_at = datetime.now(timezone.utc).isoformat()
    content = json.dumps({**settings, "saved_at": saved_at}, ensure_ascii=False, indent=2) + "\n"
    with _lock:
        global _with_metadata
        fd, temporary = None, None
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".probe-settings-", suffix=".json", dir=SETTINGS_FILE.parent)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                fd = None
                fp.write(content)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(temporary, SETTINGS_FILE)
            temporary = None
            _with_metadata = (settings, "file", saved_at)
        except OSError as exc:
            raise HTTPException(500, "配置保存失败，请检查后端目录写入权限") from exc
        finally:
            if fd is not None:
                os.close(fd)
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    return {**settings, "source": "file", "saved_at": saved_at, "effective": "next_round", "message": "设置已保存；下一轮探测会自动采用新配置"}
