"""
Traffic Database Manager (SQLite)
Manages persistent bandwidth / traffic usage statistics across server reboots.
Records hourly deltas and provides aggregated summaries:
- Today (Hari Ini)
- Last 7 Days / Week (Minggu Ini)
- Current Month (Bulan Ini)
- All-Time Total (Sepanjang Waktu)
"""

import sqlite3
import datetime
import os
import threading

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traffic.db")
_db_lock = threading.Lock()

def _get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS traffic_hourly (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        period_date TEXT NOT NULL,
                        period_hour INTEGER NOT NULL,
                        rx_bytes INTEGER DEFAULT 0,
                        tx_bytes INTEGER DEFAULT 0,
                        UNIQUE(period_date, period_hour)
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_traffic_date ON traffic_hourly(period_date);")
                
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS traffic_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS device_traffic_hourly (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_ip TEXT NOT NULL,
                        device_name TEXT,
                        period_date TEXT NOT NULL,
                        period_hour INTEGER NOT NULL,
                        rx_bytes INTEGER DEFAULT 0,
                        tx_bytes INTEGER DEFAULT 0,
                        UNIQUE(device_ip, period_date, period_hour)
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_traffic_ip_date ON device_traffic_hourly(device_ip, period_date);")
        finally:
            conn.close()

def seed_initial_if_empty(initial_rx, initial_tx):
    """
    If database is completely new, seed the currently accumulated bytes
    so existing usage is preserved across the update.
    """
    if initial_rx <= 0 and initial_tx <= 0:
        return
        
    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM traffic_hourly")
                count = cursor.fetchone()[0]
                if count == 0:
                    now = datetime.datetime.now()
                    d_str = now.strftime("%Y-%m-%d")
                    hr = now.hour
                    cursor.execute("""
                        INSERT INTO traffic_hourly (period_date, period_hour, rx_bytes, tx_bytes)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(period_date, period_hour) DO UPDATE SET
                            rx_bytes = rx_bytes + excluded.rx_bytes,
                            tx_bytes = tx_bytes + excluded.tx_bytes
                    """, (d_str, hr, int(initial_rx), int(initial_tx)))
                    cursor.execute("""
                        INSERT OR REPLACE INTO traffic_meta (key, value)
                        VALUES ('seeded_at', ?)
                    """, (now.isoformat(),))
                    print(f"[TrafficDB] Seeded baseline traffic: RX {initial_rx} B, TX {initial_tx} B")
        finally:
            conn.close()

def record_delta(rx_delta, tx_delta):
    """
    Records newly elapsed byte delta into the current hour bucket.
    """
    if rx_delta <= 0 and tx_delta <= 0:
        return

    now = datetime.datetime.now()
    d_str = now.strftime("%Y-%m-%d")
    hr = now.hour

    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO traffic_hourly (period_date, period_hour, rx_bytes, tx_bytes)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(period_date, period_hour) DO UPDATE SET
                        rx_bytes = rx_bytes + excluded.rx_bytes,
                        tx_bytes = tx_bytes + excluded.tx_bytes
                """, (d_str, hr, int(rx_delta), int(tx_delta)))
        except Exception as e:
            print(f"[TrafficDB] Error recording delta: {e}")
        finally:
            conn.close()

def record_device_delta(device_ip, device_name, rx_delta, tx_delta):
    """
    Records per-device traffic delta into device_traffic_hourly.
    """
    if rx_delta <= 0 and tx_delta <= 0:
        return

    now = datetime.datetime.now()
    d_str = now.strftime("%Y-%m-%d")
    hr = now.hour

    with _db_lock:
        conn = _get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO device_traffic_hourly (device_ip, device_name, period_date, period_hour, rx_bytes, tx_bytes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(device_ip, period_date, period_hour) DO UPDATE SET
                        device_name = excluded.device_name,
                        rx_bytes = rx_bytes + excluded.rx_bytes,
                        tx_bytes = tx_bytes + excluded.tx_bytes
                """, (device_ip, device_name, d_str, hr, int(rx_delta), int(tx_delta)))
        except Exception as e:
            print(f"[TrafficDB] Error recording device delta for {device_ip}: {e}")
        finally:
            conn.close()

def get_devices_traffic_today():
    """
    Returns today's total rx and tx per device IP.
    """
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    result = {}
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT device_ip, COALESCE(MAX(device_name), ''), COALESCE(SUM(rx_bytes), 0), COALESCE(SUM(tx_bytes), 0)
                FROM device_traffic_hourly
                WHERE period_date = ?
                GROUP BY device_ip
            """, (today_str,))
            for row in cursor.fetchall():
                ip, name, rx, tx = row
                result[ip] = {
                    "name": name,
                    "rx_bytes": int(rx),
                    "tx_bytes": int(tx),
                    "total_bytes": int(rx + tx)
                }
        except Exception as e:
            print(f"[TrafficDB] Error getting devices traffic: {e}")
        finally:
            conn.close()
    return result

def get_traffic_summary():
    """
    Returns aggregated RX and TX for today, week (last 7 days), month, and all-time.
    """
    now = datetime.datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    week_start_str = (now - datetime.timedelta(days=6)).strftime("%Y-%m-%d")
    month_prefix = now.strftime("%Y-%m") + "%"

    summary = {
        "today": {"rx": 0, "tx": 0, "total": 0},
        "week":  {"rx": 0, "tx": 0, "total": 0},
        "month": {"rx": 0, "tx": 0, "total": 0},
        "all":   {"rx": 0, "tx": 0, "total": 0},
    }

    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.cursor()

            # Today
            cursor.execute("""
                SELECT COALESCE(SUM(rx_bytes), 0), COALESCE(SUM(tx_bytes), 0)
                FROM traffic_hourly
                WHERE period_date = ?
            """, (today_str,))
            r = cursor.fetchone()
            summary["today"]["rx"] = int(r[0])
            summary["today"]["tx"] = int(r[1])
            summary["today"]["total"] = int(r[0] + r[1])

            # Week (Last 7 days including today)
            cursor.execute("""
                SELECT COALESCE(SUM(rx_bytes), 0), COALESCE(SUM(tx_bytes), 0)
                FROM traffic_hourly
                WHERE period_date >= ?
            """, (week_start_str,))
            r = cursor.fetchone()
            summary["week"]["rx"] = int(r[0])
            summary["week"]["tx"] = int(r[1])
            summary["week"]["total"] = int(r[0] + r[1])

            # Current Month
            cursor.execute("""
                SELECT COALESCE(SUM(rx_bytes), 0), COALESCE(SUM(tx_bytes), 0)
                FROM traffic_hourly
                WHERE period_date LIKE ?
            """, (month_prefix,))
            r = cursor.fetchone()
            summary["month"]["rx"] = int(r[0])
            summary["month"]["tx"] = int(r[1])
            summary["month"]["total"] = int(r[0] + r[1])

            # All time
            cursor.execute("""
                SELECT COALESCE(SUM(rx_bytes), 0), COALESCE(SUM(tx_bytes), 0)
                FROM traffic_hourly
            """)
            r = cursor.fetchone()
            summary["all"]["rx"] = int(r[0])
            summary["all"]["tx"] = int(r[1])
            summary["all"]["total"] = int(r[0] + r[1])

        except Exception as e:
            print(f"[TrafficDB] Error getting summary: {e}")
        finally:
            conn.close()

    return summary

def get_daily_history(days=30):
    """
    Returns daily breakdown for the last N days.
    """
    history = []
    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT period_date, COALESCE(SUM(rx_bytes), 0), COALESCE(SUM(tx_bytes), 0)
                FROM traffic_hourly
                GROUP BY period_date
                ORDER BY period_date DESC
                LIMIT ?
            """, (days,))
            for row in cursor.fetchall():
                rx = int(row[1])
                tx = int(row[2])
                history.append({
                    "date": row[0],
                    "rx": rx,
                    "tx": tx,
                    "total": rx + tx
                })
        except Exception as e:
            print(f"[TrafficDB] Error getting daily history: {e}")
        finally:
            conn.close()
    return history
