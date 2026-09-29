"""사용량·비용 기록. 누가, 언제, 어떤 플랫폼을, 얼마에 썼는지 남긴다."""
import sqlite3
from collections import defaultdict, deque
from datetime import date, datetime


def _empty() -> dict:
    return {"calls": 0, "success": 0, "errors": 0, "cached": 0, "cost": 0.0}


class UsageTracker:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        db.execute("""CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user_id TEXT NOT NULL,
            platform TEXT NOT NULL, status INTEGER NOT NULL, error_code TEXT, source TEXT,
            queued_ms INTEGER, latency_ms INTEGER, retries INTEGER, cost_krw REAL)""")
        db.commit()
        self.recent: deque[dict] = deque(maxlen=60)
        self._load_today()

    def _load_today(self):
        self.day = date.today()
        self.users: dict[str, dict] = defaultdict(_empty)
        rows = self.db.execute(
            """SELECT user_id, COUNT(*), SUM(status < 300), SUM(status >= 300),
                      SUM(source IN ('cache', 'coalesced')), COALESCE(SUM(cost_krw), 0)
               FROM usage_log WHERE ts >= ? GROUP BY user_id""", (self.day.isoformat(),))
        for uid, calls, ok, err, cached, cost in rows:
            self.users[uid] = {"calls": calls, "success": ok or 0, "errors": err or 0,
                               "cached": cached or 0, "cost": cost}

    def record(self, user: dict, platform: str, status: int, meta: dict, error_code: str | None = None):
        if date.today() != self.day:
            self._load_today()
        now = datetime.now()
        entry = {
            "time": now.strftime("%H:%M:%S"),
            "user_id": user["id"], "user_name": user["name"], "dept": user["dept"],
            "platform": platform, "status": status, "error_code": error_code,
            "source": meta.get("source"), "queued_ms": meta.get("queued_ms", 0),
            "latency_ms": meta.get("latency_ms", 0), "retries": meta.get("retries", 0),
            "cost_krw": meta.get("cost_krw", 0.0),
        }
        self.recent.append(entry)

        agg = self.users[user["id"]]
        agg["calls"] += 1
        agg["success" if status < 300 else "errors"] += 1
        agg["cached"] += entry["source"] in ("cache", "coalesced")
        agg["cost"] += entry["cost_krw"]

        self.db.execute(
            "INSERT INTO usage_log (ts, user_id, platform, status, error_code, source, queued_ms, latency_ms, "
            "retries, cost_krw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now.isoformat(timespec="milliseconds"), user["id"], platform, status, error_code, entry["source"],
             entry["queued_ms"], entry["latency_ms"], entry["retries"], entry["cost_krw"]))
        self.db.commit()

    def today(self, user_id: str) -> dict:
        return dict(self.users.get(user_id) or _empty())

    def spent_today(self, user_id: str) -> float:
        return self.users[user_id]["cost"] if user_id in self.users else 0.0

    def totals(self) -> dict:
        t = _empty()
        for agg in self.users.values():
            for k in t:
                t[k] += agg[k]
        return t

    def reset(self):
        self.db.execute("DELETE FROM usage_log")
        self.db.commit()
        self.recent.clear()
        self.users.clear()
