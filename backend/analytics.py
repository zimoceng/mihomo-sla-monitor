"""Day 2 read-only SLA analytics, isolated by probe URL.

Existing endpoint contracts remain compatible. When no probe_url is supplied,
statistics use the most recently used probe target in the selected time window.
This prevents mixing Google 204 and Gstatic 204 in latency percentiles.
No migrations, collector modifications, or outbound HTTP requests.
"""

from datetime import datetime, timedelta, timezone
from math import ceil, floor
from pathlib import Path
import os
import sqlite3

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/analytics", tags=["Day 2 analytics"])
DB = Path(os.getenv("SLA_DB", str(Path(__file__).resolve().parent / "sla.db")))


def db_open():
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def percentile(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    position = (len(xs) - 1) * q
    lo, hi = floor(position), ceil(position)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (position - lo), 1)


def cutoff_for(hours):
    if not 1 <= hours <= 720:
        raise HTTPException(400, "hours must be 1..720")
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def summarise(rows):
    samples = len(rows)
    good = [r["latency_ms"] for r in rows if r["success"] == 1 and r["latency_ms"] is not None]
    successes = sum(r["success"] == 1 for r in rows)
    return {
        "samples": samples,
        "successes": successes,
        "failures": samples - successes,
        "availability_pct": round(successes / samples * 100, 2) if samples else None,
        "avg_ms": round(sum(good) / len(good), 1) if good else None,
        "min_ms": min(good) if good else None,
        "max_ms": max(good) if good else None,
        "p50_ms": percentile(good, .5),
        "p95_ms": percentile(good, .95),
        "p99_ms": percentile(good, .99),
        "latency_samples": len(good),
        "percentile_warning": len(good) < 30,
    }


def _select_target(db, cutoff, probe_url):
    """Use explicit target, or latest target actually used by a CURRENT node."""
    if probe_url is not None:
        if not probe_url.strip():
            raise HTTPException(400, "probe_url cannot be empty")
        return probe_url
    row = db.execute(
        """SELECT p.probe_url
           FROM probes AS p
           INNER JOIN nodes AS n ON n.provider=p.provider AND n.name=p.name
           WHERE p.checked_at >= ? AND p.probe_url IS NOT NULL AND p.probe_url <> ''
           ORDER BY p.id DESC LIMIT 1""",
        (cutoff,),
    ).fetchone()
    return row["probe_url"] if row else None


def _node_stats(db, cutoff, selected_url):
    nodes = db.execute("SELECT provider,name,kind FROM nodes ORDER BY name").fetchall()
    if selected_url is None:
        records = []
    else:
        records = db.execute(
            """SELECT provider,name,success,latency_ms FROM probes
               WHERE checked_at >= ? AND probe_url = ? ORDER BY id""",
            (cutoff, selected_url),
        ).fetchall()
    grouped = {}
    for r in records:
        grouped.setdefault((r["provider"], r["name"]), []).append(r)
    return [
        {
            "provider": n["provider"],
            "name": n["name"],
            "kind": n["kind"],
            "probe_url": selected_url,
            **summarise(grouped.get((n["provider"], n["name"]), [])),
        }
        for n in nodes
    ]


@router.get("/targets")
def analytics_targets(hours: int = 24):
    """Discover probe URLs seen within a time window for currently tracked nodes."""
    cutoff = cutoff_for(hours)
    with db_open() as db:
        selected_url = _select_target(db, cutoff, None)
        rows = db.execute(
            """SELECT p.probe_url, COUNT(*) AS samples, SUM(p.success) AS successes,
                      MAX(p.checked_at) AS last_checked_at
               FROM probes AS p
               INNER JOIN nodes AS n ON n.provider=p.provider AND n.name=p.name
               WHERE p.checked_at >= ? AND p.probe_url IS NOT NULL AND p.probe_url <> ''
               GROUP BY p.probe_url
               ORDER BY MAX(p.id) DESC""",
            (cutoff,),
        ).fetchall()
    return {
        "hours": hours,
        "selected_probe_url": selected_url,
        "targets": [dict(r) for r in rows],
    }


@router.get("/nodes")
def analytics_nodes(hours: int = 24, probe_url: str | None = Query(default=None, max_length=2048)):
    cutoff = cutoff_for(hours)
    with db_open() as db:
        target = _select_target(db, cutoff, probe_url)
        return _node_stats(db, cutoff, target)


@router.get("/summary")
def analytics_summary(hours: int = 24, probe_url: str | None = Query(default=None, max_length=2048)):
    cutoff = cutoff_for(hours)
    with db_open() as db:
        target = _select_target(db, cutoff, probe_url)
        nodes = _node_stats(db, cutoff, target)
    observed = [n for n in nodes if n["samples"]]
    samples = sum(n["samples"] for n in nodes)
    successes = sum(n["successes"] for n in nodes)
    return {
        "hours": hours,
        "probe_url": target,
        "nodes": len(nodes),
        "observed_nodes": len(observed),
        "samples": samples,
        "successes": successes,
        "failures": samples - successes,
        "availability_pct": round(100 * successes / samples, 2) if samples else None,
        "note": "Probe success rate only; monitoring gaps are not counted as outages.",
    }


@router.get("/history")
def analytics_history(
    provider: str = Query(min_length=1),
    name: str = Query(min_length=1),
    hours: int = 24,
    probe_url: str | None = Query(default=None, max_length=2048),
):
    cutoff = cutoff_for(hours)
    with db_open() as db:
        target = _select_target(db, cutoff, probe_url)
        if target is None:
            rows = []
        else:
            rows = db.execute(
                """SELECT checked_at,success,latency_ms,error FROM probes
                   WHERE provider=? AND name=? AND checked_at>=? AND probe_url=? ORDER BY id""",
                (provider, name, cutoff, target),
            ).fetchall()
    rows = list(rows)
    stats = summarise(rows)  # Percentiles use all matching records, not decimated points.
    step = max(1, ceil(len(rows) / 600))
    return {
        "provider": provider,
        "name": name,
        "hours": hours,
        "probe_url": target,
        "stats": stats,
        "total_points": len(rows),
        "points": [
            {"time": r["checked_at"], "success": bool(r["success"]), "latency_ms": r["latency_ms"]}
            for r in rows[::step]
        ],
    }
