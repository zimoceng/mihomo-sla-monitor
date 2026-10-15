"""Day 3.2: read-only, evidence-bounded time coverage and availability analysis.

No probes/incidents mutations. Each completed Day 3 probe represents at most one
recorded monitoring interval of evidence. Missing intervals and unconfirmed
failures are UNKNOWN, not proof of node downtime or healthy uptime.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timezone, timedelta
from pathlib import Path
import math
import os
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from probe_settings import current_settings

router = APIRouter(prefix='/api/coverage', tags=['Day 3.2 coverage'])
DB = Path(os.getenv('SLA_DB', str(Path(__file__).resolve().parent / 'sla.db')))


def timestamp(value):
    if value is None:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def open_db():
    db = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def window(hours):
    if not 1 <= hours <= 720:
        raise HTTPException(400, 'hours must be 1..720')
    end = datetime.now(timezone.utc).timestamp()
    return end - hours * 3600, end


def pick_target(probe_url):
    value = probe_url or current_settings()['probe_url']
    if not value.startswith('https://') or len(value) > 500:
        raise HTTPException(400, 'invalid probe_url')
    return value


def round_reference(db, start, end):
    # Include the preceding hour to match a probe starting before the window.
    rows = db.execute('''SELECT finished_at,probe_url,interval_seconds
        FROM monitoring_rounds WHERE finished_at>=? AND finished_at<=?
        ORDER BY finished_at''', (iso(start - 3700), iso(end))).fetchall()
    rounds = []
    for r in rows:
        t = timestamp(r['finished_at'])
        if t is not None:
            rounds.append((t, r['probe_url'], max(30, min(3600, int(r['interval_seconds'])))))
    return rounds, [r[0] for r in rounds]


def interval_for_probe(at, url, rounds, finish_times):
    # A Day 3 probe is issued *before* its round has been persisted. Locate the
    # soonest finished matching round, with a finite maximum completion lag.
    idx = bisect_left(finish_times, at - .001)
    for j in range(idx, min(idx + 4, len(rounds))):
        finished, target, interval = rounds[j]
        if finished - at > 180:
            break
        if target == url:
            return interval
    return None  # Old pre-Day-3 probes have no matching round; never backfill.


def incident_map(db, start, end, url):
    rows = db.execute('''SELECT provider,name,started_at,confirmed_at,ended_at,
        last_failure_at,status,id FROM incidents
        WHERE probe_url=? AND confirmed_at<=? AND (ended_at IS NULL OR ended_at>=?)
        ORDER BY started_at''', (url, iso(end), iso(start))).fetchall()
    grouped = {}
    for r in rows:
        s = timestamp(r['started_at'])
        f = timestamp(r['last_failure_at'])
        stop = timestamp(r['ended_at']) if r['ended_at'] else end
        if s is None:
            continue
        grouped.setdefault((r['provider'], r['name']), []).append({
            'start': s, 'last_failure': f if f is not None else s,
            'end': stop if stop is not None else end, 'id':r['id'], 'status':r['status'],
        })
    return grouped


def evidence_status(at, success, events):
    # Only a failure inside an independently CONFIRMED incident is 'down'.
    # An unconfirmed failure, or a recovery observation before final confirmation,
    # remains 'unknown'. Healthy requires a success outside an incident interval.
    for event in events:
        if event['start'] - .001 <= at < event['end'] + .001:
            if not success and at <= event['last_failure'] + .001:
                return 'down'
            if at < event['end'] - .001:
                return 'unknown'
    return 'healthy' if success else 'unknown'


def node_evidence(db, provider, name, url, start, end, rounds, finish_times, events):
    rows = db.execute('''SELECT checked_at,success FROM probes
        WHERE provider=? AND name=? AND probe_url=?
          AND checked_at>=? AND checked_at<=?
        ORDER BY checked_at,id''',
        (provider, name, url, iso(start - 3700), iso(end))).fetchall()
    samples = []
    for r in rows:
        at = timestamp(r['checked_at'])
        if at is None:
            continue
        interval = interval_for_probe(at, url, rounds, finish_times)
        if interval is None:
            continue
        samples.append((at, interval, int(r['success'])))
    slots = []
    for i,(at,interval,success) in enumerate(samples):
        next_at = samples[i+1][0] if i+1 < len(samples) else end
        left = max(at, start)
        right = min(at + interval, next_at, end)
        if right <= left:
            continue
        kind = evidence_status(at, success, events)
        slots.append((left, right, kind))
    total = end - start
    durations = {'healthy':0.0,'down':0.0}
    sampled = 0.0
    for left,right,kind in slots:
        sampled += right-left  # Even a failed/unconfirmed probe counts as monitored.
        if kind in durations:
            durations[kind] += right-left
    healthy = durations['healthy']
    down = durations['down']
    classified = healthy + down
    uncertain = max(0.0, sampled - classified)  # Probe exists, state is uncertain.
    unobserved = max(0.0, total - sampled)  # Actual monitoring gap.
    unknown = uncertain + unobserved
    evidence_count = len(samples)
    return {
        'provider':provider, 'name':name, 'probe_url':url,
        'samples_with_day3_round':evidence_count,
        'window_seconds':round(total,1),
        'healthy_seconds':round(healthy,1), 'down_seconds':round(down,1),
        'unknown_seconds':round(unknown,1),
        'sampled_seconds':round(sampled,1), 'unobserved_seconds':round(unobserved,1),
        'uncertain_seconds':round(uncertain,1),
        'classified_seconds':round(classified,1),
        'coverage_pct':round(100*sampled/total,2) if total else None,
        'observed_availability_pct':round(100*healthy/classified,2) if classified else None,
        'availability_lower_bound_pct':round(100*healthy/total,2) if total else None,
        'availability_upper_bound_pct':round(100*(healthy+unknown)/total,2) if total else None,
    }, slots


def collect_nodes(db, start, end, url, requested=None):
    rounds, times = round_reference(db, start, end)
    events = incident_map(db, start, end, url)
    if requested is None:
        nodes = db.execute('SELECT provider,name FROM nodes ORDER BY name').fetchall()
        pairs = [(r['provider'],r['name']) for r in nodes]
    else:
        pairs = [requested]
    output = []
    for provider,name in pairs:
        metrics, slots = node_evidence(db, provider,name,url,start,end,rounds,times,events.get((provider,name),[]))
        output.append((metrics, slots))
    return output


def meta(start, end, url, hours):
    return {'hours':hours,'probe_url':url,'window_start':iso(start),'window_end':iso(end),
        'methodology':'Day 3 rounds only. Each probe supports at most its recorded interval. Coverage includes completed failures; unconfirmed failures remain uncertain, not confirmed downtime.',
        'disclaimer':'Observed time availability excludes unknown time. It is not contractual SLA or proof of real server downtime.'}


@router.get('/nodes')
def coverage_nodes(hours: int = Query(24,ge=1,le=720), probe_url: str | None = None):
    start,end = window(hours)
    url = pick_target(probe_url)
    with open_db() as db:
        rows = [data for data,_ in collect_nodes(db,start,end,url)]
    return {**meta(start,end,url,hours),'nodes':rows}


@router.get('/summary')
def coverage_summary(hours: int = Query(24,ge=1,le=720), probe_url: str | None = None):
    start,end = window(hours)
    url = pick_target(probe_url)
    with open_db() as db:
        rows = [data for data,_ in collect_nodes(db,start,end,url)]
    healthy = sum(r['healthy_seconds'] for r in rows)
    down = sum(r['down_seconds'] for r in rows)
    unknown = sum(r['unknown_seconds'] for r in rows)
    total = len(rows)*(end-start)
    classified = healthy+down
    sampled = sum(r['sampled_seconds'] for r in rows)
    unobserved = sum(r['unobserved_seconds'] for r in rows)
    uncertain = sum(r['uncertain_seconds'] for r in rows)
    return {**meta(start,end,url,hours),'nodes':len(rows),
        'healthy_seconds':round(healthy,1),'down_seconds':round(down,1),
        'unknown_seconds':round(unknown,1),'sampled_seconds':round(sampled,1),
        'unobserved_seconds':round(unobserved,1), 'uncertain_seconds':round(uncertain,1),
        'coverage_pct':round(100*sampled/total,2) if total else None,
        'observed_availability_pct':round(100*healthy/classified,2) if classified else None,
        'availability_lower_bound_pct':round(100*healthy/total,2) if total else None,
        'availability_upper_bound_pct':round(100*(healthy+unknown)/total,2) if total else None,
        'note':'Coverage counts time represented by completed samples (including failures); uncertainty and missing samples count as unknown node status. Not contractual SLA.'}


def timeline_buckets(slots,start,end,bins):
    span = (end-start)/bins
    out = []
    for i in range(bins):
        a,b=start+i*span,start+(i+1)*span
        out.append({'start':iso(a),'end':iso(b), 'healthy_seconds':0.0,'down_seconds':0.0,'unknown_seconds':round(b-a,1)})
    for a,b,state in slots:
        if state not in ('healthy','down'):
            continue
        first=max(0,min(bins-1,int((a-start)/span)))
        last=max(0,min(bins-1,int((b-start-1e-8)/span)))
        for idx in range(first,last+1):
            left=max(a,start+idx*span)
            right=min(b,start+(idx+1)*span)
            if right>left:
                out[idx][f'{state}_seconds'] += right-left
    for row in out:
        row['healthy_seconds']=round(row['healthy_seconds'],1)
        row['down_seconds']=round(row['down_seconds'],1)
        row['unknown_seconds']=round(max(0,span-row['healthy_seconds']-row['down_seconds']),1)
    return out


@router.get('/timeline')
def coverage_timeline(provider: str=Query(min_length=1,max_length=150),
                      name: str=Query(min_length=1,max_length=200),
                      hours: int=Query(24,ge=1,le=720),
                      probe_url: str | None = None,
                      bins: int=Query(48,ge=12,le=120)):
    start,end = window(hours)
    url=pick_target(probe_url)
    with open_db() as db:
        row=db.execute('SELECT 1 FROM nodes WHERE provider=? AND name=?',(provider,name)).fetchone()
        if row is None:
            raise HTTPException(404,'node not found')
        metrics, slots=collect_nodes(db,start,end,url,(provider,name))[0]
        events=db.execute('''SELECT id,started_at,confirmed_at,ended_at,status,duration_seconds
            FROM incidents WHERE provider=? AND name=? AND probe_url=?
              AND confirmed_at<=? AND (ended_at IS NULL OR ended_at>=?)
            ORDER BY confirmed_at DESC LIMIT 100''',
            (provider,name,url,iso(end),iso(start))).fetchall()
    return {**meta(start,end,url,hours),'provider':provider,'name':name,
        'metrics':metrics,'buckets':timeline_buckets(slots,start,end,bins),
        'events':[dict(x) for x in events]}
