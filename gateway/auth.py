"""직원 계정과 내부 API 키 관리 (SQLite)."""
import random
import secrets
import sqlite3
from datetime import datetime

SURNAMES = "김이박최정강조윤장임한오서신권황안송류홍"
GIVEN = ["민준", "서연", "도윤", "하은", "시우", "지우", "예준", "수아", "주원", "지호", "하준", "서윤", "지안",
         "은우", "유진", "현우", "채원", "건우", "다은", "준서", "소율", "우진", "지민", "선우", "예린"]
DEPTS = ["영업1팀", "영업2팀", "구매팀", "재무팀", "인사팀", "마케팅팀", "해외사업팀", "물류팀", "고객지원팀", "데이터팀"]


def _new_key() -> str:
    return "gk_" + secrets.token_hex(16)


class UserStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, dept TEXT NOT NULL,
            api_key TEXT UNIQUE NOT NULL, active INTEGER NOT NULL, created_at TEXT NOT NULL)""")
        db.commit()
        self._by_id: dict[str, dict] = {}
        self._by_key: dict[str, dict] = {}
        for row in db.execute("SELECT id, name, dept, api_key, active, created_at FROM users ORDER BY id"):
            self._put(dict(zip(("id", "name", "dept", "api_key", "active", "created_at"), row)))

    def _put(self, user: dict):
        user["active"] = bool(user["active"])
        self._by_id[user["id"]] = user
        self._by_key[user["api_key"]] = user

    def seed(self, count: int):
        """처음 실행할 때 시연용 직원 계정을 만든다."""
        if self._by_id:
            return
        rng = random.Random(2026)
        names: set[str] = set()
        while len(names) < count:
            names.add(rng.choice(SURNAMES) + rng.choice(GIVEN))
        for name in sorted(names, key=lambda _: rng.random()):
            self.create(name, rng.choice(DEPTS))

    def create(self, name: str, dept: str) -> dict:
        next_no = max((int(uid[1:]) for uid in self._by_id), default=0) + 1
        user = {"id": f"u{next_no:03d}", "name": name, "dept": dept, "api_key": _new_key(),
                "active": True, "created_at": datetime.now().isoformat(timespec="seconds")}
        self.db.execute("INSERT INTO users VALUES (:id, :name, :dept, :api_key, :active, :created_at)", user)
        self.db.commit()
        self._put(user)
        return user

    def set_active(self, user_id: str, active: bool) -> dict | None:
        user = self._by_id.get(user_id)
        if user is None:
            return None
        user["active"] = active
        self.db.execute("UPDATE users SET active = ? WHERE id = ?", (int(active), user_id))
        self.db.commit()
        return user

    def get(self, user_id: str) -> dict | None:
        return self._by_id.get(user_id)

    def by_key(self, api_key: str | None) -> dict | None:
        return self._by_key.get(api_key) if api_key else None

    def all(self) -> list[dict]:
        return list(self._by_id.values())
