"""Day 3 fault incidents: independent from Day 1 probe data.

New events begin when this extension is installed (no retroactive classification).
Only completed probe rounds update incidents; missing rounds are UNKNOWN, not DOWN.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from probe_settings import current_settings

router = APIRouter(prefix="/api/incidents", tags=["Day 3 incidents"])
DB = Path(os.getenv("SLA_DB", str(Path(__file__).resolve().parent / "sla.db")))
FAIL_THRESHOLD = 3
RECOVER_THRESHOLD = 2


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def seconds_between(start, end):
    a, b = parse_time(start), parse_time(end)
    return max(0.0, (b - a).total_seconds()) if a and b else None


def db_open(read_only=True):
    if read_only:
        db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    else:
        db = sqlite3.connect(DB, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def init_schema(path=None):
    path = Path(path or DB)
    with sqlite3.connect(path, timeout=10) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS incident_states (
            provider TEXT NOT NULL,
            name TEXT NOT NULL,
            probe_url TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT 'unknown',
            failure_streak INTEGER NOT NULL DEFAULT 0,
            success_streak INTEGER NOT NULL DEFAULT 0,
            first_failure_at TEXT,
            last_checked_at TEXT,
            last_success INTEGER,
            open_incident_id INTEGER,
            PRIMARY KEY (provider, name, probe_url)
        );
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            name TEXT NOT NULL,
            probe_url TEXT NOT NULL,
            started_at TEXT NOT NULL,
            confirmed_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('open','resolved','interrupted')),
            duration_seconds REAL,
            failures INTEGER NOT NULL DEFAULT 0,
            last_failure_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_incidents_target_confirmed
            ON incidents(probe_url, confirmed_at);
        CREATE INDEX IF NOT EXISTS idx_incidents_node
            ON incidents(provider, name, probe_url, started_at);
        CREATE TABLE IF NOT EXISTS monitoring_rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            finished_at TEXT NOT NULL,
            probe_url TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL,
            tested INTEGER NOT NULL,
            successes INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_monitoring_rounds_time
            ON monitoring_rounds(finished_at);
        """)


def _interrupt(db, state, last_seen):
    if state['open_incident_id']:
        db.execute("""UPDATE incidents SET status='interrupted', ended_at=?, duration_seconds=NULL
                      WHERE id=? AND status='open'""", (last_seen, state['open_incident_id']))
    return ('unknown', 0, 0, None, None)


def record_round(db, results, settings):
    """Consume a finished collector batch *within its SQLite transaction*.

    results: (provider, name, kind, checked_at, success, latency, error, probe_url).
    Called exactly once per successful collect_once().
    """
    interval = int(settings['interval_seconds'])
    url = str(settings['probe_url'])
    newest = utc_now().isoformat()
    db.execute("""INSERT INTO monitoring_rounds
        (finished_at,probe_url,interval_seconds,tested,successes)
        VALUES(?,?,?,?,?)""", (newest, url, interval, len(results), sum(int(r[4]) for r in results)))

    # Switching probe targets or removing a node does not mean the old target recovered.
    current_keys = {(r[0], r[1], r[7]) for r in results}
    for state in db.execute("SELECT * FROM incident_states WHERE phase!='unknown'").fetchall():
        key = (state['provider'], state['name'], state['probe_url'])
        if key not in current_keys:
            _interrupt(db, state, state['last_checked_at'])
            db.execute("""UPDATE incident_states SET phase='unknown', failure_streak=0,
                success_streak=0, first_failure_at=NULL, open_incident_id=NULL
                WHERE provider=? AND name=? AND probe_url=?""", key)

    gap_limit = max(150, interval * 3 + 30)
    for provider, name, _kind, checked_at, success, _ms, _err, probe_url in results:
        key = (provider, name, probe_url)
        state = db.execute("""SELECT * FROM incident_states
            WHERE provider=? AND name=? AND probe_url=?""", key).fetchone()
        phase = state['phase'] if state else 'unknown'
        fail_streak = state['failure_streak'] if state else 0
        success_streak = state['success_streak'] if state else 0
        first_failure = state['first_failure_at'] if state else None
        open_id = state['open_incident_id'] if state else None

        if state and seconds_between(state['last_checked_at'], checked_at) is not None \
                and seconds_between(state['last_checked_at'], checked_at) > gap_limit:
            phase, fail_streak, success_streak, first_failure, open_id = _interrupt(
                db, state, state['last_checked_at'])

        if int(success) == 0:
            success_streak = 0
            if phase in ('down', 'recovering') and open_id:
                phase = 'down'
                db.execute("""UPDATE incidents SET failures=failures+1, last_failure_at=?
                    WHERE id=? AND status='open'""", (checked_at, open_id))
            else:
                if fail_streak == 0:
                    first_failure = checked_at
                fail_streak += 1
                phase = 'suspect'
                if fail_streak >= FAIL_THRESHOLD:
                    cursor = db.execute("""INSERT INTO incidents
                        (provider,name,probe_url,started_at,confirmed_at,status,failures,last_failure_at)
                        VALUES(?,?,?,?,?,'open',?,?)""", (
                        provider, name, probe_url, first_failure, checked_at, fail_streak, checked_at))
                    open_id = cursor.lastrowid
                    phase = 'down'
        else:
            if phase in ('down', 'recovering') and open_id:
                success_streak += 1
                phase = 'recovering'
                if success_streak >= RECOVER_THRESHOLD:
                    incident = db.execute("SELECT started_at FROM incidents WHERE id=?", (open_id,)).fetchone()
                    duration = seconds_between(incident['started_at'], checked_at)
                    db.execute("""UPDATE incidents SET status='resolved', ended_at=?, duration_seconds=?
                        WHERE id=? AND status='open'""", (checked_at, duration, open_id))
                    phase, fail_streak, success_streak, first_failure, open_id = 'healthy', 0, 0, None, None
            else:
                phase, fail_streak, success_streak, first_failure, open_id = 'healthy', 0, 0, None, None

        db.execute("""INSERT INTO incident_states
            (provider,name,probe_url,phase,failure_streak,success_streak,first_failure_at,
            last_checked_at,last_success,open_incident_id)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(provider,name,probe_url) DO UPDATE SET
            phase=excluded.phase, failure_streak=excluded.failure_streak,
            success_streak=excluded.success_streak, first_failure_at=excluded.first_failure_at,
            last_checked_at=excluded.last_checked_at, last_success=excluded.last_success,
            open_incident_id=excluded.open_incident_id""",
            (*key, phase, fail_streak, success_streak, first_failure, checked_at, int(success), open_id))


def _window(hours):
    if not 1 <= hours <= 720:
        raise HTTPException(400, "hours must be 1..720")
    return (utc_now() - timedelta(hours=hours)).isoformat()


def _target(probe_url):
    # Enforce only currently registered probe targets to keep the queries bounded.
    return probe_url or current_settings()['probe_url']


def _monitor(db, url):
    row = db.execute("SELECT * FROM monitoring_rounds ORDER BY id DESC LIMIT 1").fetchone()
    interval = current_settings()['interval_seconds']
    grace = max(150, interval * 3 + 30)
    age = seconds_between(row['finished_at'], utc_now().isoformat()) if row else None
    status = 'no_data' if row is None else ('stale' if age is None or age > grace else ('target_switch_pending' if row['probe_url'] != url else 'healthy'))
    return {
        'status': status, 'last_round_at': row['finished_at'] if row else None,
        'last_round_probe_url': row['probe_url'] if row else None,
        'last_round_tested': row['tested'] if row else None,
        'last_round_successes': row['successes'] if row else None,
        'last_round_age_seconds': round(age, 1) if age is not None else None,
        'stale_after_seconds': grace,
    }


def _node_status(row, now, grace, current_target):
    if row is None or row['last_checked_at'] is None:
        return 'unknown'
    age = seconds_between(row['last_checked_at'], now)
    if age is None or age > grace:
        return 'unknown'
    return row['phase'] if current_target else 'unknown'


def _events(db, url, cutoff, limit=500):
    rows = db.execute("""SELECT * FROM incidents
        WHERE probe_url=? AND confirmed_at<=? AND (ended_at IS NULL OR ended_at>=?)
        ORDER BY confirmed_at DESC LIMIT ?""", (url, utc_now().isoformat(), cutoff, limit)).fetchall()
    return [dict(r) for r in rows]


def _mtbf(events):
    # Uptime between one confirmed recovery and the next incident's first failure,
    # grouped by node and target. Undefined if no pair exists.
    by_node = {}
    for e in events:
        by_node.setdefault((e['provider'], e['name'], e['probe_url']), []).append(e)
    intervals = []
    for node_events in by_node.values():
        chronological = sorted(node_events, key=lambda e: e['started_at'])
        for previous, next_one in zip(chronological, chronological[1:]):
            if previous['status'] == 'resolved' and previous['ended_at']:
                elapsed = seconds_between(previous['ended_at'], next_one['started_at'])
                if elapsed is not None:
                    intervals.append(elapsed)
    return round(sum(intervals) / len(intervals), 1) if intervals else None


@router.get('/health')
def incident_monitor_health():
    url = current_settings()['probe_url']
    with db_open() as db:
        return {'probe_url': url, **_monitor(db, url),
                'note': 'Monitoring gaps or absence of fresh samples are UNKNOWN, never proof of node outage.'}


@router.get('/summary')
def incident_summary(hours: int = 24, probe_url: str | None = None):
    cutoff = _window(hours)
    url = _target(probe_url)
    now = utc_now().isoformat()
    with db_open() as db:
        mon = _monitor(db, url)
        events = _events(db, url, cutoff, limit=10000)
        states = db.execute("""SELECT * FROM incident_states WHERE probe_url=?""", (url,)).fetchall()
    grace = mon['stale_after_seconds']
    active = sum(1 for s in states if _node_status(s, now, grace, mon['status'] == 'healthy') in ('down','recovering'))
    suspect = sum(1 for s in states if _node_status(s, now, grace, mon['status'] == 'healthy') == 'suspect')
    recovered = [e['duration_seconds'] for e in events if e['status'] == 'resolved' and e['duration_seconds'] is not None]
    return {
        'hours': hours, 'probe_url': url, 'monitor': mon,
        'confirmed_incidents': len(events), 'active_nodes': active, 'suspected_nodes': suspect,
        'resolved_incidents': sum(e['status'] == 'resolved' for e in events),
        'interrupted_incidents': sum(e['status'] == 'interrupted' for e in events),
        'mttr_seconds': round(sum(recovered) / len(recovered), 1) if recovered else None,
        'mtbf_seconds': _mtbf(events),
        'note': 'MTTR uses only confirmed resolved incidents; MTBF uses observed healthy intervals between such incidents. Day 3 events start after installation. Gaps remain unknown.'
    }


@router.get('/nodes')
def incident_nodes(hours: int = 24, probe_url: str | None = None):
    cutoff = _window(hours)
    url = _target(probe_url)
    now = utc_now().isoformat()
    with db_open() as db:
        mon = _monitor(db, url)
        nodes = db.execute("""SELECT n.provider,n.name,n.kind,
                s.phase,s.failure_streak,s.success_streak,s.last_checked_at,s.last_success
                FROM nodes n LEFT JOIN incident_states s
                  ON s.provider=n.provider AND s.name=n.name AND s.probe_url=?
                ORDER BY n.name""", (url,)).fetchall()
        counts = db.execute("""SELECT provider,name,COUNT(*) incidents,
                  SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) resolved
                FROM incidents WHERE probe_url=? AND confirmed_at>=?
                GROUP BY provider,name""", (url, cutoff)).fetchall()
    mapped = {(r['provider'], r['name']): r for r in counts}
    out=[]
    for r in nodes:
        stats=mapped.get((r['provider'],r['name']))
        entry=dict(r)
        entry['status']=_node_status(r, now, mon['stale_after_seconds'], mon['status']=='healthy')
        entry['incidents']=stats['incidents'] if stats else 0
        entry['resolved']=stats['resolved'] if stats else 0
        out.append(entry)
    return {'hours': hours, 'probe_url': url, 'monitor': mon, 'nodes': out}


@router.get('/events')
def incident_events(hours: int = 24, probe_url: str | None = None, limit: int = Query(100, ge=1, le=500)):
    cutoff = _window(hours)
    url = _target(probe_url)
    with db_open() as db:
        events = _events(db, url, cutoff, limit)
        mon = _monitor(db, url)
    return {'hours': hours, 'probe_url': url, 'monitor': mon, 'events': events,
            'note': 'interrupted means monitoring/target continuity was lost; it does not assert recovery.'}
