#!/usr/bin/env python3
"""
Simple Log Management System
============================
Now with Separate Batch Tables!

Each batch (1–5) is stored in its own table:
    batch_1, batch_2, batch_3, batch_4, batch_5

Run: python simple_log_system.py
"""

import subprocess
import sqlite3
import time
import re
import json
import threading
from datetime import datetime
from collections import defaultdict
from dateutil import parser as dateparser
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.file_persistence import FilePersistence

# ============================================================================
# CONFIGURATION
# ============================================================================
DB_PATH = "system_logs.db"
BATCH_DB_PATH = "batches.db"
JOURNALCTL_CMD = ["journalctl", "-f", "-o", "short"]
DRAIN3_STATE = "drain3_state.json"
CONTEXT_WINDOW_SECONDS = 10
BATCH_SIZE = 100
NUM_BATCHES = 5
CHECK_INTERVAL = 5  # seconds

# ============================================================================
# REGEX PATTERNS
# ============================================================================
IP_V4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})(?:\.(?:25[0-5]|2[0-4]\d|1?\d{1,2})){3})\b")
IP_V6_RE = re.compile(r"\b([0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b")
TIMESTAMP_RE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?|\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\b")
NUMBER_RE = re.compile(r"\b\d+\b")
PATH_RE = re.compile(r"(/(?:[\w\-. ]+/?)+)")

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================
def init_database():
    """Initialize all database tables."""
    # System logs database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            timestamp REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON raw_logs(timestamp)")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clean (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_id INTEGER,
            group_id INTEGER,
            template_id INTEGER,
            template TEXT,
            params TEXT,
            count INTEGER,
            first_seen TEXT,
            last_seen TEXT,
            sample_message TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS context_groups (
            group_id INTEGER PRIMARY KEY,
            summary TEXT,
            first_seen TEXT,
            last_seen TEXT,
            unique_templates INTEGER,
            total_messages INTEGER
        )
    """)
    
    conn.commit()
    conn.close()
    print(f"✓ System logs database: {DB_PATH}")
    
    # Batches database
    batch_conn = sqlite3.connect(BATCH_DB_PATH)
    cur = batch_conn.cursor()

    # Create separate batch tables
    for i in range(1, NUM_BATCHES + 1):
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS batch_{i} (
                clean_id INTEGER NOT NULL,
                template TEXT,
                template_id INTEGER,
                params TEXT,
                count INTEGER,
                first_seen TEXT,
                last_seen TEXT,
                sample_message TEXT,
                created_at TEXT,
                PRIMARY KEY (clean_id)
            )
        """)

    # Metadata + events
    cur.execute("""
        CREATE TABLE IF NOT EXISTS batch_metadata (
            batch_id INTEGER PRIMARY KEY,
            log_count INTEGER,
            first_seen TEXT,
            last_seen TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS batch_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            batch_id INTEGER,
            count INTEGER,
            timestamp TEXT,
            details TEXT
        )
    """)
    
    batch_conn.commit()
    batch_conn.close()
    print(f"✓ Batches database (5 separate tables): {BATCH_DB_PATH}")

# ============================================================================
# MODULE 1: JOURNALCTL STREAMING
# ============================================================================
def store_log(conn, message: str, timestamp: float):
    """Store log entry in raw_logs table."""
    cursor = conn.cursor()
    created_at = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO raw_logs (message, timestamp, created_at)
        VALUES (?, ?, ?)
    """, (message, timestamp, created_at))
    conn.commit()

def stream_logs_thread():
    """Stream journalctl logs continuously."""
    conn = sqlite3.connect(DB_PATH)
    print("🔴 [STREAM] Starting journalctl capture...")
    
    proc = subprocess.Popen(JOURNALCTL_CMD, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    log_count = 0
    
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            timestamp = time.time()
            store_log(conn, line, timestamp)
            log_count += 1
            if log_count % 50 == 0:
                print(f"🔴 [STREAM] Captured {log_count} logs")
    except Exception as e:
        print(f"🔴 [STREAM] Error: {e}")
    finally:
        conn.close()
        proc.terminate()

# ============================================================================
# MODULE 2: DRAIN3 PROCESSING
# ============================================================================
def parse_timestamp(ts_str):
    if ts_str is None:
        return None
    try:
        if isinstance(ts_str, (int, float)):
            return datetime.fromtimestamp(ts_str)
        return dateparser.parse(ts_str)
    except Exception:
        try:
            now = datetime.now()
            dt = datetime.strptime(ts_str, "%b %d %H:%M:%S")
            return dt.replace(year=now.year)
        except Exception:
            return None

def mask_message(msg):
    msg = IP_V4_RE.sub("<IP>", msg)
    msg = IP_V6_RE.sub("<IPV6>", msg)
    msg = TIMESTAMP_RE.sub("<TIME>", msg)
    msg = PATH_RE.sub("<PATH>", msg)
    msg = NUMBER_RE.sub("<NUM>", msg)
    return msg

def extract_params(msg):
    params = []
    pats = [("IP", IP_V4_RE), ("IPV6", IP_V6_RE), ("TIME", TIMESTAMP_RE), ("PATH", PATH_RE), ("NUM", NUMBER_RE)]
    matches = []
    for name, pat in pats:
        for m in pat.finditer(msg):
            matches.append((m.start(), name, m.group(0)))
    matches.sort(key=lambda x: x[0])
    for _, name, value in matches:
        params.append({"type": name, "value": value})
    return params

def init_drain3():
    cfg = TemplateMinerConfig()
    persistence = FilePersistence(DRAIN3_STATE)
    return TemplateMiner(persistence, config=cfg)

def process_logs_thread():
    print("🟡 [PROCESS] Starting log processing...")
    while True:
        try:
            db = sqlite3.connect(DB_PATH)
            db.row_factory = sqlite3.Row
            cur = db.cursor()

            cur.execute("SELECT MAX(original_id) FROM clean")
            last_processed = cur.fetchone()[0] or 0

            cur.execute("""
                SELECT id, message, timestamp, created_at 
                FROM raw_logs 
                WHERE id > ? 
                ORDER BY timestamp ASC
                LIMIT 1000
            """, (last_processed,))
            
            rows = cur.fetchall()
            if rows:
                miner = init_drain3()
                records = []
                for r in rows:
                    ts = parse_timestamp(r["timestamp"] or r["created_at"]) or datetime.now()
                    records.append({"original_id": r["id"], "message": r["message"], "timestamp": ts})

                processed = []
                for rec in records:
                    masked = mask_message(rec["message"])
                    res = miner.add_log_message(masked)
                    template = res.get("template_mined", masked)
                    template_id = res.get("cluster_id")
                    params = extract_params(rec["message"])
                    processed.append({
                        "original_id": rec["original_id"],
                        "template": template,
                        "template_id": template_id,
                        "params": params,
                        "timestamp": rec["timestamp"],
                        "raw": rec["message"]
                    })

                processed.sort(key=lambda x: x["timestamp"])
                groups = []
                current = []
                cur.execute("SELECT MAX(group_id) FROM context_groups")
                last_gid = cur.fetchone()[0]
                gid_seq = (last_gid + 1) if last_gid else int(datetime.now().timestamp())
                start_time = None

                for p in processed:
                    if not current:
                        current = [p]; start_time = p["timestamp"]; continue
                    if (p["timestamp"] - start_time).total_seconds() <= CONTEXT_WINDOW_SECONDS:
                        current.append(p)
                    else:
                        groups.append((gid_seq, current))
                        gid_seq += 1
                        current = [p]; start_time = p["timestamp"]
                if current:
                    groups.append((gid_seq, current))

                for gid, recs in groups:
                    dedup = {}
                    for r in recs:
                        pjson = json.dumps(r["params"], ensure_ascii=False)
                        key = (r["template_id"], r["template"], pjson)
                        if key not in dedup:
                            dedup[key] = {"original_ids": [r["original_id"]], "count": 1,
                                          "first_seen": r["timestamp"], "last_seen": r["timestamp"],
                                          "sample_message": r["raw"]}
                        else:
                            d = dedup[key]
                            d["original_ids"].append(r["original_id"])
                            d["count"] += 1
                            d["first_seen"] = min(d["first_seen"], r["timestamp"])
                            d["last_seen"] = max(d["last_seen"], r["timestamp"])

                    first_seen = min(r["timestamp"] for r in recs)
                    last_seen = max(r["timestamp"] for r in recs)

                    for (tid, tmpl, pjson), d in dedup.items():
                        cur.execute("""
                            INSERT INTO clean (original_id, group_id, template_id, template, params, count, first_seen, last_seen, sample_message)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (d["original_ids"][0], gid, tid, tmpl, pjson, d["count"],
                              d["first_seen"].isoformat(), d["last_seen"].isoformat(), d["sample_message"]))

                    cur.execute("""
                        INSERT OR REPLACE INTO context_groups
                        (group_id, summary, first_seen, last_seen, unique_templates, total_messages)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (gid, f"Group of {len(recs)} logs", first_seen.isoformat(),
                          last_seen.isoformat(), len(dedup), len(recs)))

                db.commit()
                print(f"🟡 [PROCESS] Processed {len(records)} logs → {len(groups)} groups")
            db.close()
        except Exception as e:
            print(f"🟡 [PROCESS] Error: {e}")
        time.sleep(CHECK_INTERVAL)

# ============================================================================
# MODULE 3: BATCH MANAGEMENT (PER-TABLE)
# ============================================================================
def log_batch_event(batch_conn, event_type, batch_id, count, details=""):
    cur = batch_conn.cursor()
    cur.execute("""
        INSERT INTO batch_events (event_type, batch_id, count, timestamp, details)
        VALUES (?, ?, ?, ?, ?)
    """, (event_type, batch_id, count, datetime.now().isoformat(), details))
    batch_conn.commit()

def shift_batches_down(batch_conn):
    cur = batch_conn.cursor()
    # Delete batch_5
    cur.execute("SELECT log_count FROM batch_metadata WHERE batch_id = 5")
    batch5_info = cur.fetchone()
    deleted_count = batch5_info[0] if batch5_info else 0
    cur.execute("DROP TABLE IF EXISTS batch_5")
    if deleted_count > 0:
        log_batch_event(batch_conn, "DELETED", 5, deleted_count, "Batch 5 dropped")

    # Shift 4→5, 3→4, etc.
    for old in range(4, 0, -1):
        new = old + 1
        cur.execute(f"ALTER TABLE batch_{old} RENAME TO batch_{new}")
        cur.execute("""
            UPDATE batch_metadata
            SET batch_id = ?, updated_at = ?
            WHERE batch_id = ?
        """, (new, datetime.now().isoformat(), old))
        log_batch_event(batch_conn, "MOVED", new, 0, f"Renamed batch_{old} → batch_{new}")

    # Recreate fresh batch_1
    cur.execute("""
        CREATE TABLE batch_1 (
            clean_id INTEGER NOT NULL,
            template TEXT,
            template_id INTEGER,
            params TEXT,
            count INTEGER,
            first_seen TEXT,
            last_seen TEXT,
            sample_message TEXT,
            created_at TEXT,
            PRIMARY KEY (clean_id)
        )
    """)
    batch_conn.commit()

def add_logs_to_batch(batch_conn, batch_id, logs):
    if not logs: return
    cur = batch_conn.cursor()
    now = datetime.now().isoformat()
    table = f"batch_{batch_id}"
    cur.executemany(f"""
        INSERT INTO {table} (clean_id, template, template_id, params, count,
                             first_seen, last_seen, sample_message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [(log[0], log[1], log[2], log[3], log[4], log[5], log[6], log[7], now) for log in logs])

    first_seen = min(log[5] for log in logs)
    last_seen = max(log[6] for log in logs)
    cur.execute("SELECT log_count FROM batch_metadata WHERE batch_id = ?", (batch_id,))
    existing = cur.fetchone()
    if existing:
        new_count = existing[0] + len(logs)
        cur.execute("""
            UPDATE batch_metadata SET log_count=?, last_seen=?, updated_at=? WHERE batch_id=?
        """, (new_count, last_seen, now, batch_id))
    else:
        cur.execute("""
            INSERT INTO batch_metadata (batch_id, log_count, first_seen, last_seen, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (batch_id, len(logs), first_seen, last_seen, now, now))
    batch_conn.commit()
    log_batch_event(batch_conn, "LOADED", batch_id, len(logs), f"Added {len(logs)} logs to Batch {batch_id}")

def batch_management_thread():
    print("🟢 [BATCH] Starting batch manager...")
    while True:
        try:
            sys_conn = sqlite3.connect(DB_PATH)
            batch_conn = sqlite3.connect(BATCH_DB_PATH)
            cur = batch_conn.cursor()
            cur.execute("SELECT MAX(clean_id) FROM batch_1")
            last_id = cur.fetchone()[0] or 0
            sys_cur = sys_conn.cursor()
            sys_cur.execute("""
                SELECT id, template, template_id, params, count, first_seen, last_seen, sample_message
                FROM clean WHERE id > ? ORDER BY id ASC
            """, (last_id,))
            new_logs = sys_cur.fetchall()
            if new_logs:
                cur.execute("SELECT log_count FROM batch_metadata WHERE batch_id = 1")
                meta = cur.fetchone()
                batch1_count = meta[0] if meta else 0
                if batch1_count + len(new_logs) > BATCH_SIZE:
                    print("🟢 [BATCH] Overflow! Shifting batches...")
                    shift_batches_down(batch_conn)
                    batch1_count = 0
                add_logs_to_batch(batch_conn, 1, new_logs)
                print(f"🟢 [BATCH] Added {len(new_logs)} logs to Batch 1")
                for i in range(1, NUM_BATCHES + 1):
                    cur.execute("SELECT log_count FROM batch_metadata WHERE batch_id = ?", (i,))
                    info = cur.fetchone()
                    if info:
                        status = "LIVE" if i == 1 else f"B{i}"
                        print(f"   [{status}] {info[0]} logs", end="  ")
                print()
            sys_conn.close()
            batch_conn.close()
        except Exception as e:
            print(f"🟢 [BATCH] Error: {e}")
        time.sleep(CHECK_INTERVAL)

# ============================================================================
# MAIN
# ============================================================================
def main():
    print("\n" + "="*80)
    print("🚀 Simple Log Management System (Separate Batch Tables)")
    print("="*80)
    init_database()
    print("\nStarting all components...\nPress Ctrl+C to stop\n")
    t1 = threading.Thread(target=stream_logs_thread, daemon=True)
    t2 = threading.Thread(target=process_logs_thread, daemon=True)
    t3 = threading.Thread(target=batch_management_thread, daemon=True)
    t1.start(); time.sleep(2)
    t2.start(); time.sleep(2)
    t3.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n✅ Shutting down...")
        print("="*80)

if __name__ == "__main__":
    main()
