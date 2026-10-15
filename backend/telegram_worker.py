#!/usr/bin/env python3
"""Independent Telegram notifier. Reads SLA incidents; never changes SLA probe data.

First run sets a baseline at the current max incident id: historical incidents do
not generate notifications. For newer incidents, delivery is recorded only after
Telegram confirms success; unsent events are retried after network recovery.
"""
import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

DB = Path(os.getenv('SLA_DB', '/opt/mihomo-sla/backend/sla.db'))
STATE = Path(os.getenv('SLA_TG_STATE_DB', '/var/lib/mihomo-sla-alerts/state.db'))
TOKEN = os.getenv('SLA_TG_BOT_TOKEN', '').strip()
CHAT = os.getenv('SLA_TG_CHAT_ID', '').strip()
PROXY = os.getenv('SLA_TG_PROXY', 'http://127.0.0.1:7890').strip()
POLL = max(10, min(300, int(os.getenv('SLA_TG_POLL_SECONDS', '20'))))


def connect(path, read_only=False):
    if read_only:
        db = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)
    else:
        db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def state_init(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS delivered(
        incident_id INTEGER NOT NULL, kind TEXT NOT NULL,
        delivered_at TEXT NOT NULL, PRIMARY KEY(incident_id,kind));
    ''')


def current_max_incident(source):
    with connect(source, True) as db:
        return int(db.execute('SELECT COALESCE(MAX(id),0) FROM incidents').fetchone()[0])


def ensure_baseline(state, source):
    row = state.execute('SELECT value FROM settings WHERE key=?', ('baseline_id',)).fetchone()
    if row:
        return int(row['value'])
    baseline = current_max_incident(source)
    state.execute('INSERT INTO settings(key,value) VALUES (?,?)', ('baseline_id',str(baseline)))
    state.commit()
    print(f'[telegram] initialized after existing incident #{baseline}; no backfill notifications', flush=True)
    return baseline


def when(value):
    if not value:
        return '—'
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H:%M:%S (UTC+8)')
    except ValueError:
        return str(value)[:40]


def fmt(incident, kind):
    # Telegram plain text: no HTML/Markdown rendering or escaping complexity.
    name = ''.join(c for c in incident['name'] if c.isprintable())[:100]
    target = incident['probe_url'][:200]
    common = f'节点：{name}\n检测目标：{target}\n事件编号：{incident["id"]}'
    if kind == 'down':
        return f'🔴 SLA 节点故障已确认\n{common}\n首次失败：{when(incident["started_at"])}\n确认时间：{when(incident["confirmed_at"])}\n判定规则：连续 3 次探测失败'
    if kind == 'resolved':
        d = incident['duration_seconds']
        duration = f'{d / 60:.1f} 分钟' if d is not None else '未知'
        return f'🟢 SLA 节点恢复已确认\n{common}\n恢复时间：{when(incident["ended_at"])}\n故障持续：{duration}\n判定规则：连续 2 次探测成功'
    return f'⚪ SLA 故障监测中断\n{common}\n最后观测：{when(incident["ended_at"])}\n说明：监控证据中断，节点是否恢复未知'


def http_client():
    return httpx.Client(proxy=None if PROXY.lower() in ('','none','direct') else PROXY,
                        trust_env=False, follow_redirects=False, timeout=20)


def send(client, message):
    # Never log request URLs: Telegram API token is embedded in the endpoint.
    try:
        response = client.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',
                               json={'chat_id':CHAT, 'text':message, 'disable_web_page_preview':True})
        if response.status_code != 200:
            raise RuntimeError(f'Telegram HTTP {response.status_code}')
        payload = response.json()
        if not payload.get('ok'):
            raise RuntimeError('Telegram rejected request')
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f'Telegram network/response error ({type(exc).__name__})') from None


def pending_for_event(item):
    # Confirmation and recovery may happen between two scans. In that case,
    # deliver both in chronological order to avoid a missing initial alert.
    status = item['status']
    if status == 'open':
        return ('down',)
    if status == 'resolved':
        return ('down','resolved')
    if status == 'interrupted':
        return ('down','interrupted')
    return ()


def poll_once(source, state, client):
    baseline = ensure_baseline(state, source)
    with connect(source, True) as db:
        incidents = db.execute('''SELECT id,provider,name,probe_url,started_at,confirmed_at,
            ended_at,status,duration_seconds FROM incidents WHERE id>? ORDER BY id''',
            (baseline,)).fetchall()
    delivered = 0
    for incident in incidents:
        for kind in pending_for_event(incident):
            if state.execute('SELECT 1 FROM delivered WHERE incident_id=? AND kind=?',
                             (incident['id'],kind)).fetchone():
                continue
            send(client, fmt(incident,kind))
            state.execute('INSERT INTO delivered(incident_id,kind,delivered_at) VALUES(?,?,?)',
                          (incident['id'],kind,datetime.now(timezone.utc).isoformat()))
            state.commit()
            delivered += 1
            print(f'[telegram] delivered event {incident["id"]} {kind}', flush=True)
    return delivered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test',action='store_true', help='Send one explicit test message')
    parser.add_argument('--chats',action='store_true', help='List recent chat IDs from getUpdates without displaying bot token')
    parser.add_argument('--once',action='store_true', help='One polling iteration')
    args=parser.parse_args()
    if not TOKEN or TOKEN.find(':') == -1 or (not args.chats and not CHAT):
        raise SystemExit('Set SLA_TG_BOT_TOKEN and SLA_TG_CHAT_ID in the systemd EnvironmentFile')
    if args.chats:
        with http_client() as client:
            try:
                response = client.get(f'https://api.telegram.org/bot{TOKEN}/getUpdates')
                response.raise_for_status()
                result = response.json()
                if not result.get('ok'):
                    raise RuntimeError('Telegram API rejected request')
                chats = set()
                for update in result.get('result', []):
                    message = update.get('message') or update.get('channel_post') or {}
                    chat_id = (message.get('chat') or {}).get('id')
                    if chat_id is not None: chats.add(chat_id)
                print('Recent chat IDs:', ', '.join(str(x) for x in sorted(chats)) if chats else 'none; send /start to the bot first')
            except (httpx.HTTPError, ValueError):
                print('Telegram getUpdates failed; check network, proxy and bot settings')
        return
    STATE.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with connect(STATE) as state:
        state_init(state)
        with http_client() as client:
            if args.test:
                send(client, '✅ Mihomo SLA Telegram 通知测试成功。\n仅用于验证消息通道，不创建或修改 SLA 故障记录。')
                print('[telegram] test message delivered',flush=True)
                return
            ensure_baseline(state, DB)
            print('[telegram] watching confirmed incidents without modifying production data',flush=True)
            while True:
                try:
                    poll_once(DB, state, client)
                except (sqlite3.Error,RuntimeError) as exc:
                    print(f'[telegram] delivery will retry: {type(exc).__name__}',flush=True)
                if args.once:
                    break
                time.sleep(POLL)


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print(f'[telegram] fatal: {type(exc).__name__}: {exc if isinstance(exc, SystemExit) else "check service logs"}', file=sys.stderr)
        sys.exit(1)
