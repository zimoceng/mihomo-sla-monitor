"""Mihomo SLA Day 1: isolated collector + SQLite + FastAPI."""
import asyncio
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit
import ipaddress
import socket
import tempfile
import yaml
from pydantic import BaseModel, Field

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from probe_settings import router as probe_settings_router, current_settings
import incident_engine
import coverage_engine
from analytics import router as analytics_router

API = os.getenv("MIHOMO_API", "http://127.0.0.1:19091").rstrip("/")
API_SECRET = os.getenv("MIHOMO_SECRET", "")
DB = Path(os.getenv("SLA_DB", str(Path(__file__).resolve().parent / "sla.db")))
INTERVAL = max(30, int(os.getenv("SLA_INTERVAL", "60")))
TIMEOUT_MS = max(1000, int(os.getenv("SLA_TIMEOUT_MS", "5000")))
CONCURRENCY = max(1, int(os.getenv("SLA_CONCURRENCY", "5")))
PROBE_URL = os.getenv("SLA_PROBE_URL", "https://www.google.com/generate_204")
PROVIDER_NAME = "all-nodes"
PROVIDER_FILE = Path(os.getenv("SLA_PROVIDER_FILE", str(Path(__file__).resolve().parent.parent / "monitor/nodes.yaml")))
DOWNLOAD_PROXY = os.getenv("SLA_DOWNLOAD_PROXY", "http://127.0.0.1:7890")
_import_lock = asyncio.Lock()


class SubscriptionRequest(BaseModel):
    url: str = Field(min_length=12, max_length=4096)


def safe_url(url):
    u = urlsplit(url.strip())
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment:
        raise HTTPException(400, "只接受标准 HTTPS 订阅地址（不允许 URL 用户信息和片段）")
    if u.port not in (None, 443):
        raise HTTPException(400, "目前只允许 HTTPS 默认端口 443")
    host = u.hostname.strip('.').lower()
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise HTTPException(400, "不允许本地或内网地址")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise HTTPException(400, "不允许私有或保留 IP")
    except ValueError:
        pass
    return url.strip()


def extract_nodes(data):
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        raise HTTPException(422, "订阅内容不是 Mihomo YAML 节点配置（缺少 proxies 列表）；若返回 Base64 URI 订阅，请先转换为 Mihomo YAML")
    nodes = data["proxies"]
    if not nodes or len(nodes) > 2000:
        raise HTTPException(422, "没有节点或节点过多")
    names = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get('name'), str) or not isinstance(node.get('type'), str):
            raise HTTPException(422, "节点定义存在缺失字段")
        if node['name'] in names:
            raise HTTPException(422, "订阅存在重名节点，请先去重")
        names.add(node['name'])
    return nodes



def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                provider TEXT NOT NULL, name TEXT NOT NULL,
                kind TEXT, last_seen TEXT NOT NULL,
                PRIMARY KEY(provider, name)
            );
            CREATE TABLE IF NOT EXISTS probes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL, name TEXT NOT NULL,
                checked_at TEXT NOT NULL, success INTEGER NOT NULL,
                latency_ms INTEGER, error TEXT, probe_url TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_probes_node_time
              ON probes(provider, name, checked_at);
        """)


def headers():
    return {"Authorization": f"Bearer {API_SECRET}"} if API_SECRET else {}


async def probe_one(client, semaphore, provider, node, probe_url, timeout_ms):
    name = node["name"]
    kind = node.get("type", "unknown")
    async with semaphore:
        now = datetime.now(timezone.utc).isoformat()
        ok, latency, error = False, None, None
        try:
            endpoint = (f"{API}/providers/proxies/{quote(provider, safe='')}/"
                        f"{quote(name, safe='')}/healthcheck")
            response = await client.get(endpoint, params={"url": probe_url, "timeout": timeout_ms})
            response.raise_for_status()
            delay = response.json().get("delay")
            if not isinstance(delay, (int, float)) or delay <= 0:
                raise ValueError(f"Unexpected delay: {delay!r}")
            ok, latency = True, int(delay)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            error = str(exc)[:350]
        return (provider, name, kind, now, int(ok), latency, error, probe_url)


async def collect_once():
    settings = current_settings()  # Consistent snapshot for every node in this round.
    async with httpx.AsyncClient(timeout=httpx.Timeout((settings["timeout_ms"] / 1000) + 5), headers=headers()) as client:
        response = await client.get(f"{API}/providers/proxies")
        response.raise_for_status()
        providers = response.json().get("providers", {})
        candidates = []
        for provider, data in providers.items():
            if provider == "default" or data.get("vehicleType", "").lower() == "compatible":
                continue
            for node in data.get("proxies", []):
                if node.get("name") and node.get("type", "").lower() not in ("direct", "reject", "selector", "urltest", "fallback", "loadbalance"):
                    candidates.append((provider, node))
        if not candidates:
            raise RuntimeError("No nodes loaded in any non-default provider; verify monitor/nodes.yaml")
        sem = asyncio.Semaphore(CONCURRENCY)
        results = await asyncio.gather(*(probe_one(client, sem, p, n, settings["probe_url"], settings["timeout_ms"]) for p, n in candidates))
    with connect() as db:
        db.executemany("""INSERT INTO nodes(provider,name,kind,last_seen) VALUES(?,?,?,?)
          ON CONFLICT(provider,name) DO UPDATE SET kind=excluded.kind,last_seen=excluded.last_seen""",
          [(p,n,k,t) for p,n,k,t,*_ in results])
        db.executemany("""INSERT INTO probes(provider,name,checked_at,success,latency_ms,error,probe_url)
          VALUES(?,?,?,?,?,?,?)""", [(p,n,t,s,ms,e,url) for p,n,k,t,s,ms,e,url in results])
        # Save Day 3 incident state within this round's transaction.
        # A Day 3 calculation error is isolated so existing probe writes still commit.
        db.execute("SAVEPOINT day3_faults")
        try:
            incident_engine.record_round(db, results, settings)
        except Exception as fault_exc:
            db.execute("ROLLBACK TO SAVEPOINT day3_faults")
            print("[day3] incident processing error:", repr(fault_exc), flush=True)
        finally:
            db.execute("RELEASE SAVEPOINT day3_faults")
    return {"tested": len(results), "success": sum(x[4] for x in results)}


async def background_loop():
    while True:
        started = time.monotonic()
        try:
            print("collector:", await collect_once(), flush=True)
        except Exception as exc:
            print("collector error:", repr(exc), flush=True)
        # Re-evaluate once per second so Web changes take effect without a restart.
        while True:
            remaining = current_settings()["interval_seconds"] - (time.monotonic() - started)
            if remaining <= 0:
                break
            await asyncio.sleep(min(1.0, remaining))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    incident_engine.init_schema(DB)
    task = asyncio.create_task(background_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Mihomo SLA API", version="0.1.0", lifespan=lifespan)
app.include_router(probe_settings_router)
app.include_router(incident_engine.router)
app.include_router(coverage_engine.router)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
allow_methods=["GET", "POST"], allow_headers=["*"])
app.include_router(analytics_router)

@app.get("/api/health")
def health():
    return {"ok": True, "mihomo_api": API, "probe_interval_seconds": current_settings()["interval_seconds"]}


@app.get("/api/nodes")
def nodes(hours: int = 24):
    if not 1 <= hours <= 720:
        raise HTTPException(400, "hours must be 1..720")
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with connect() as db:
        rows = db.execute("""SELECT n.provider,n.name,n.kind,n.last_seen,
        COUNT(p.id) samples, COALESCE(SUM(p.success),0) successes,
        ROUND(AVG(CASE WHEN p.success=1 THEN p.latency_ms END),1) avg_ms,
        (SELECT success FROM probes x WHERE x.provider=n.provider AND x.name=n.name ORDER BY x.id DESC LIMIT 1) last_success,
        (SELECT latency_ms FROM probes x WHERE x.provider=n.provider AND x.name=n.name ORDER BY x.id DESC LIMIT 1) last_ms
        FROM nodes n LEFT JOIN probes p ON p.provider=n.provider AND p.name=n.name AND p.checked_at >= ?
        GROUP BY n.provider,n.name ORDER BY n.name""", (cutoff,)).fetchall()
    return [{**dict(r), "availability_pct": round(r["successes"] / r["samples"] * 100, 2) if r["samples"] else None} for r in rows]


@app.get("/api/history")
def history(provider: str, name: str, limit: int = 100):
    if not 1 <= limit <= 1000:
        raise HTTPException(400, "limit must be 1..1000")
    with connect() as db:
        rows = db.execute("""SELECT checked_at,success,latency_ms,error,probe_url FROM probes
            WHERE provider=? AND name=? ORDER BY id DESC LIMIT ?""", (provider, name, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


@app.get("/api/meta")
def meta():
    with connect() as db:
        p = db.execute("SELECT count(*) FROM probes").fetchone()[0]
        n = db.execute("SELECT count(*) FROM nodes").fetchone()[0]
    return {"nodes": n, "probes": p, "disclaimer": "Probe availability is not contractual SLA; gaps and monitor failures must be tracked separately."}


@app.post("/api/subscription/import")
async def import_subscription(payload: SubscriptionRequest):
    """Download through the already working local Mihomo proxy; never return credentials to the UI."""
    url = safe_url(payload.url)
    async with _import_lock:
        try:
            async with httpx.AsyncClient(proxy=DOWNLOAD_PROXY or None, trust_env=False,
                                         follow_redirects=False, timeout=35.0) as client:
                response = await client.get(
    url,
    headers={
        "User-Agent": "clash.meta",
        "Accept": "application/yaml,text/yaml,*/*"
    }
)
                if response.is_redirect:
                    raise HTTPException(400, "订阅重定向已被禁用；请填写最终 HTTPS 订阅地址")
                response.raise_for_status()
                if len(response.content) > 4 * 1024 * 1024:
                    raise HTTPException(413, "订阅大于 4 MiB")
        except httpx.HTTPError as exc:
            raise HTTPException(502, "下载订阅失败，请检查主 Mihomo 7890 端口及订阅服务连通性") from exc
        try:
            data = yaml.safe_load(response.text)
        except yaml.YAMLError as exc:
            raise HTTPException(422, "订阅 YAML 格式错误") from exc
        nodes = extract_nodes(data)
        PROVIDER_FILE.parent.mkdir(parents=True, exist_ok=True)
        output = yaml.safe_dump({"proxies": nodes}, allow_unicode=True, sort_keys=False)
        fd, tmp = tempfile.mkstemp(prefix=".nodes-", suffix=".yaml", dir=PROVIDER_FILE.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(output)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, PROVIDER_FILE)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        try:
            async with httpx.AsyncClient(timeout=8, headers=headers(), trust_env=False) as client:
                r = await client.put(f"{API}/providers/proxies/{PROVIDER_NAME}")
                r.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(503, f"订阅已保存 {len(nodes)} 个节点，但监控 Mihomo 刷新失败；请确认 19091 实例已启动") from exc
        return {"saved": True, "count": len(nodes), "message": "订阅已保存，并已请求监控 Mihomo 重新加载；请点击查询节点列表确认"}


@app.get("/api/subscription/nodes")
async def subscription_nodes():
    try:
        async with httpx.AsyncClient(timeout=10, headers=headers(), trust_env=False) as client:
            r = await client.get(f"{API}/providers/proxies")
            r.raise_for_status()
            providers = r.json().get("providers", {})
            selected = providers.get(PROVIDER_NAME)
            if not selected:
                raise HTTPException(503, "监控 Mihomo 未发现 all-nodes Provider")
            return {"provider": PROVIDER_NAME, "count": len(selected.get('proxies', [])), "nodes": [
                {"name": n.get('name'), "type": n.get('type')} for n in selected.get('proxies', [])]}
    except httpx.HTTPError as exc:
        raise HTTPException(503, "监控 Mihomo API 不可访问：确认独立实例监听 127.0.0.1:19091") from exc
