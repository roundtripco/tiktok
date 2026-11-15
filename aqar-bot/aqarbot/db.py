"""قاعدة البيانات (SQLite): المكاتب، الوسطاء، المستأجرين، الإيصالات."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .utils import add_months, month_key, today_kw

SCHEMA = """
CREATE TABLE IF NOT EXISTS offices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    color TEXT NOT NULL,
    logo_path TEXT,
    code TEXT NOT NULL UNIQUE,
    owner_id INTEGER NOT NULL,
    paid_until TEXT NOT NULL,
    receipt_seq INTEGER NOT NULL DEFAULT 0,
    card_seq INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    user_id INTEGER PRIMARY KEY,
    office_id INTEGER NOT NULL REFERENCES offices(id),
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'agent')),
    joined_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY,
    office_id INTEGER NOT NULL REFERENCES offices(id),
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    unit TEXT NOT NULL,
    amount_fils INTEGER NOT NULL,
    due_day INTEGER NOT NULL CHECK (due_day BETWEEN 1 AND 31),
    last_paid_month TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY,
    office_id INTEGER NOT NULL REFERENCES offices(id),
    number INTEGER NOT NULL,
    payer TEXT NOT NULL,
    amount_fils INTEGER NOT NULL,
    reason TEXT NOT NULL,
    method TEXT NOT NULL,
    notes TEXT,
    tenant_id INTEGER REFERENCES tenants(id),
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (office_id, number)
);
CREATE TABLE IF NOT EXISTS reminders_sent (
    tenant_id INTEGER NOT NULL,
    month TEXT NOT NULL,
    kind TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, month, kind)
);
CREATE TABLE IF NOT EXISTS activations (
    id INTEGER PRIMARY KEY,
    office_id INTEGER NOT NULL REFERENCES offices(id),
    months INTEGER NOT NULL,
    new_paid_until TEXT NOT NULL,
    admin_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    office_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    action TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (office_id, day, action)
);
"""


@dataclass
class Office:
    id: int
    name: str
    phone: str
    color: str
    logo_path: str | None
    code: str
    owner_id: int
    paid_until: date
    receipt_seq: int
    card_seq: int

    def is_active(self, today: date | None = None) -> bool:
        return (today or today_kw()) <= self.paid_until

    def days_left(self, today: date | None = None) -> int:
        return (self.paid_until - (today or today_kw())).days


@dataclass
class Member:
    user_id: int
    office_id: int
    name: str
    role: str


@dataclass
class Tenant:
    id: int
    office_id: int
    name: str
    phone: str
    unit: str
    amount_fils: int
    due_day: int
    last_paid_month: str | None
    active: bool

    def paid_for(self, d: date) -> bool:
        return self.last_paid_month is not None and self.last_paid_month >= month_key(d)


@dataclass
class Receipt:
    id: int
    office_id: int
    number: int
    payer: str
    amount_fils: int
    reason: str
    method: str
    notes: str | None
    tenant_id: int | None
    created_by: int
    created_at: datetime


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---------- المكاتب ----------

    def _new_code(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            if not self.conn.execute("SELECT 1 FROM offices WHERE code=?", (code,)).fetchone():
                return code

    def create_office(
        self, *, name: str, phone: str, color: str, logo_path: str | None,
        owner_id: int, owner_name: str, trial_days: int,
    ) -> Office:
        paid_until = date.fromordinal(today_kw().toordinal() + trial_days)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO offices (name, phone, color, logo_path, code, owner_id, paid_until, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, phone, color, logo_path, self._new_code(), owner_id,
                 paid_until.isoformat(), _now()),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO members (user_id, office_id, name, role, joined_at)"
                " VALUES (?, ?, ?, 'owner', ?)",
                (owner_id, cur.lastrowid, owner_name, _now()),
            )
        return self.get_office(cur.lastrowid)

    @staticmethod
    def _office(row: sqlite3.Row | None) -> Office | None:
        if row is None:
            return None
        data = dict(row)
        data.pop("created_at")
        data["paid_until"] = date.fromisoformat(data["paid_until"])
        return Office(**data)

    def get_office(self, office_id: int) -> Office | None:
        return self._office(self.conn.execute("SELECT * FROM offices WHERE id=?", (office_id,)).fetchone())

    def get_office_by_code(self, code: str) -> Office | None:
        return self._office(
            self.conn.execute("SELECT * FROM offices WHERE code=?", (code.strip().upper(),)).fetchone()
        )

    def list_offices(self) -> list[Office]:
        rows = self.conn.execute("SELECT * FROM offices ORDER BY id").fetchall()
        return [self._office(r) for r in rows]

    def update_office(self, office_id: int, **fields) -> None:
        allowed = {"name", "phone", "color", "logo_path"}
        if not fields or not set(fields) <= allowed:
            raise ValueError(f"حقول غير مسموحة: {set(fields) - allowed}")
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.conn:
            self.conn.execute(f"UPDATE offices SET {cols} WHERE id=?", (*fields.values(), office_id))

    def extend_subscription(self, office_id: int, months: int, admin_id: int) -> Office:
        office = self.get_office(office_id)
        start = max(office.paid_until, today_kw())
        new_until = add_months(start, months)
        with self.conn:
            self.conn.execute("UPDATE offices SET paid_until=? WHERE id=?", (new_until.isoformat(), office_id))
            self.conn.execute(
                "INSERT INTO activations (office_id, months, new_paid_until, admin_id, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (office_id, months, new_until.isoformat(), admin_id, _now()),
            )
        return self.get_office(office_id)

    def next_card_number(self, office_id: int) -> int:
        with self.conn:
            self.conn.execute("UPDATE offices SET card_seq = card_seq + 1 WHERE id=?", (office_id,))
            return self.conn.execute("SELECT card_seq FROM offices WHERE id=?", (office_id,)).fetchone()[0]

    # ---------- الأعضاء ----------

    def get_member(self, user_id: int) -> Member | None:
        row = self.conn.execute(
            "SELECT user_id, office_id, name, role FROM members WHERE user_id=?", (user_id,)
        ).fetchone()
        return Member(**dict(row)) if row else None

    def add_agent(self, user_id: int, office_id: int, name: str) -> Member:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO members (user_id, office_id, name, role, joined_at)"
                " VALUES (?, ?, ?, 'agent', ?)",
                (user_id, office_id, name, _now()),
            )
        return self.get_member(user_id)

    def list_members(self, office_id: int) -> list[Member]:
        rows = self.conn.execute(
            "SELECT user_id, office_id, name, role FROM members WHERE office_id=?"
            " ORDER BY role DESC, joined_at", (office_id,)
        ).fetchall()
        return [Member(**dict(r)) for r in rows]

    def remove_member(self, user_id: int, office_id: int) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM members WHERE user_id=? AND office_id=? AND role='agent'", (user_id, office_id)
            )
        return cur.rowcount > 0

    # ---------- المستأجرين ----------

    @staticmethod
    def _tenant(row: sqlite3.Row | None) -> Tenant | None:
        if row is None:
            return None
        data = dict(row)
        data.pop("created_at")
        data["active"] = bool(data["active"])
        return Tenant(**data)

    def add_tenant(
        self, *, office_id: int, name: str, phone: str, unit: str,
        amount_fils: int, due_day: int, last_paid_month: str | None,
    ) -> Tenant:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO tenants (office_id, name, phone, unit, amount_fils, due_day, last_paid_month, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (office_id, name, phone, unit, amount_fils, due_day, last_paid_month, _now()),
            )
        return self.get_tenant(cur.lastrowid, office_id)

    def get_tenant(self, tenant_id: int, office_id: int) -> Tenant | None:
        return self._tenant(self.conn.execute(
            "SELECT * FROM tenants WHERE id=? AND office_id=? AND active=1", (tenant_id, office_id)
        ).fetchone())

    def list_tenants(self, office_id: int) -> list[Tenant]:
        rows = self.conn.execute(
            "SELECT * FROM tenants WHERE office_id=? AND active=1 ORDER BY due_day, name", (office_id,)
        ).fetchall()
        return [self._tenant(r) for r in rows]

    def all_active_tenants(self) -> list[Tenant]:
        rows = self.conn.execute("SELECT * FROM tenants WHERE active=1").fetchall()
        return [self._tenant(r) for r in rows]

    def mark_tenant_paid(self, tenant_id: int, month: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE tenants SET last_paid_month=? WHERE id=? AND (last_paid_month IS NULL OR last_paid_month < ?)",
                (month, tenant_id, month),
            )

    def deactivate_tenant(self, tenant_id: int, office_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE tenants SET active=0 WHERE id=? AND office_id=?", (tenant_id, office_id))

    def reminder_sent(self, tenant_id: int, month: str, kind: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM reminders_sent WHERE tenant_id=? AND month=? AND kind=?", (tenant_id, month, kind)
        ).fetchone() is not None

    def log_reminder(self, tenant_id: int, month: str, kind: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO reminders_sent (tenant_id, month, kind, sent_at) VALUES (?, ?, ?, ?)",
                (tenant_id, month, kind, _now()),
            )

    # ---------- الإيصالات ----------

    def create_receipt(
        self, *, office_id: int, payer: str, amount_fils: int, reason: str, method: str,
        notes: str | None, created_by: int, tenant_id: int | None = None,
    ) -> Receipt:
        with self.conn:
            self.conn.execute("UPDATE offices SET receipt_seq = receipt_seq + 1 WHERE id=?", (office_id,))
            number = self.conn.execute("SELECT receipt_seq FROM offices WHERE id=?", (office_id,)).fetchone()[0]
            cur = self.conn.execute(
                "INSERT INTO receipts (office_id, number, payer, amount_fils, reason, method, notes, tenant_id,"
                " created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (office_id, number, payer, amount_fils, reason, method, notes, tenant_id, created_by, _now()),
            )
        row = dict(self.conn.execute("SELECT * FROM receipts WHERE id=?", (cur.lastrowid,)).fetchone())
        row["created_at"] = datetime.fromisoformat(row["created_at"])
        return Receipt(**row)

    # ---------- الاستخدام ----------

    def log_usage(self, office_id: int, action: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO usage (office_id, day, action, count) VALUES (?, ?, ?, 1)"
                " ON CONFLICT (office_id, day, action) DO UPDATE SET count = count + 1",
                (office_id, today_kw().isoformat(), action),
            )

    def usage_summary(self, since: date) -> dict[int, dict[str, int]]:
        rows = self.conn.execute(
            "SELECT office_id, action, SUM(count) AS n FROM usage WHERE day >= ? GROUP BY office_id, action",
            (since.isoformat(),),
        ).fetchall()
        summary: dict[int, dict[str, int]] = {}
        for r in rows:
            summary.setdefault(r["office_id"], {})[r["action"]] = r["n"]
        return summary
