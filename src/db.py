"""SQLite schema and access. DDL and row mapping only — no business logic.

Schema mirrors SCHEMA.md exactly. Dict/dataclass-typed fields (raw, provenance,
params, transcript) are stored as JSON text columns.
"""

import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from src.models import Check, CheckResult, Decision, Lead, Override

DB_PATH = "data/qa.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS checks (
    check_id             TEXT NOT NULL,
    version              INTEGER NOT NULL DEFAULT 1,
    retailer_id          TEXT NOT NULL,
    type                 TEXT NOT NULL CHECK (type IN ('A','B','C')),
    description          TEXT NOT NULL,
    is_critical          INTEGER NOT NULL DEFAULT 0,
    weight               REAL NOT NULL DEFAULT 1.0,
    effective_from       TEXT NOT NULL DEFAULT '1970-01-01',
    effective_to         TEXT,
    expected_script_text TEXT,
    pass_at              REAL DEFAULT 0.85,
    fail_at              REAL DEFAULT 0.60,
    min_word_confidence  REAL DEFAULT 0.55,
    crm_field            TEXT,
    plan_field           TEXT,
    comparator           TEXT,
    tolerance            REAL DEFAULT 0.0,
    params_json          TEXT DEFAULT '{}',
    raw_json             TEXT DEFAULT '{}',
    provenance_json      TEXT DEFAULT '{}',
    PRIMARY KEY (check_id, version)
);

CREATE TABLE IF NOT EXISTS leads (
    lead_id         TEXT PRIMARY KEY,
    retailer_id     TEXT NOT NULL,
    call_date       TEXT NOT NULL,
    agent_id        TEXT,
    campaign        TEXT,
    team_lead_id    TEXT,
    recording_path  TEXT,
    transcript_json TEXT,
    crm_fields_json TEXT DEFAULT '{}',
    plan_json       TEXT DEFAULT '{}',
    raw_json        TEXT DEFAULT '{}',
    provenance_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS check_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id         TEXT NOT NULL,
    check_id        TEXT NOT NULL,
    check_version   INTEGER NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('PASS','FAIL','LOW_CONFIDENCE')),
    confidence      REAL NOT NULL,
    is_critical     INTEGER NOT NULL,
    weight          REAL NOT NULL,
    transcript_line TEXT,
    start_ts        REAL,
    end_ts          REAL,
    expected        TEXT,
    actual          TEXT,
    detail          TEXT,
    asr_confidence  REAL,
    scored_at       TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(lead_id)
);
CREATE INDEX IF NOT EXISTS idx_results_lead ON check_results(lead_id);

CREATE TABLE IF NOT EXISTS decisions (
    lead_id              TEXT PRIMARY KEY,
    gate_status          TEXT NOT NULL
                         CHECK (gate_status IN ('AUTO_SUBMIT','HELD','QA_REVIEW')),
    reason               TEXT,
    sampled              INTEGER NOT NULL DEFAULT 0,
    score_with_fatals    REAL,
    score_without_fatals REAL,
    decided_at           TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(lead_id)
);

CREATE TABLE IF NOT EXISTS overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id     TEXT NOT NULL,
    check_id    TEXT NOT NULL,
    actor       TEXT NOT NULL,
    old_status  TEXT NOT NULL,
    new_status  TEXT NOT NULL,
    reason      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditor_labels (
    lead_id    TEXT NOT NULL,
    check_id   TEXT NOT NULL,
    status     TEXT NOT NULL,
    auditor_id TEXT,
    PRIMARY KEY (lead_id, check_id, auditor_id)
);

CREATE TABLE IF NOT EXISTS llm_cache (
    input_hash    TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
"""


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def insert_check(conn: sqlite3.Connection, check: Check) -> None:
    conn.execute(
        """
        INSERT INTO checks (
            check_id, version, retailer_id, type, description, is_critical,
            weight, effective_from, effective_to, expected_script_text,
            pass_at, fail_at, min_word_confidence, crm_field, plan_field,
            comparator, tolerance, params_json, raw_json, provenance_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (check_id, version) DO UPDATE SET
            retailer_id=excluded.retailer_id, type=excluded.type,
            description=excluded.description, is_critical=excluded.is_critical,
            weight=excluded.weight, effective_from=excluded.effective_from,
            effective_to=excluded.effective_to,
            expected_script_text=excluded.expected_script_text,
            pass_at=excluded.pass_at, fail_at=excluded.fail_at,
            min_word_confidence=excluded.min_word_confidence,
            crm_field=excluded.crm_field, plan_field=excluded.plan_field,
            comparator=excluded.comparator, tolerance=excluded.tolerance,
            params_json=excluded.params_json, raw_json=excluded.raw_json,
            provenance_json=excluded.provenance_json
        """,
        (
            check.check_id, check.version, check.retailer_id, check.type,
            check.description, int(check.is_critical), check.weight,
            _iso(check.effective_from), _iso(check.effective_to),
            check.expected_script_text, check.pass_at, check.fail_at,
            check.min_word_confidence, check.crm_field, check.plan_field,
            check.comparator, check.tolerance, json.dumps(check.params),
            json.dumps(check.raw), json.dumps(check.provenance),
        ),
    )
    conn.commit()


def insert_lead(conn: sqlite3.Connection, lead: Lead) -> None:
    transcript_json = (
        json.dumps(asdict(lead.transcript)) if lead.transcript is not None else None
    )
    conn.execute(
        """
        INSERT INTO leads (
            lead_id, retailer_id, call_date, agent_id, campaign, team_lead_id,
            recording_path, transcript_json, crm_fields_json, plan_json,
            raw_json, provenance_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (lead_id) DO UPDATE SET
            retailer_id=excluded.retailer_id, call_date=excluded.call_date,
            agent_id=excluded.agent_id, campaign=excluded.campaign,
            team_lead_id=excluded.team_lead_id,
            recording_path=excluded.recording_path,
            transcript_json=excluded.transcript_json,
            crm_fields_json=excluded.crm_fields_json, plan_json=excluded.plan_json,
            raw_json=excluded.raw_json, provenance_json=excluded.provenance_json
        """,
        (
            lead.lead_id, lead.retailer_id, _iso(lead.call_date), lead.agent_id,
            lead.campaign, lead.team_lead_id, lead.recording_path,
            transcript_json, json.dumps(lead.crm_fields), json.dumps(lead.plan),
            json.dumps(lead.raw), json.dumps(lead.provenance),
        ),
    )
    conn.commit()


def insert_check_result(conn: sqlite3.Connection, result: CheckResult) -> None:
    conn.execute(
        """
        INSERT INTO check_results (
            lead_id, check_id, check_version, status, confidence, is_critical,
            weight, transcript_line, start_ts, end_ts, expected, actual,
            detail, asr_confidence, scored_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            result.lead_id, result.check_id, result.check_version, result.status,
            result.confidence, int(result.is_critical), result.weight,
            result.transcript_line, result.start_ts, result.end_ts,
            result.expected, result.actual, result.detail, result.asr_confidence,
            _iso(result.scored_at),
        ),
    )
    conn.commit()


def insert_decision(conn: sqlite3.Connection, decision: Decision) -> None:
    conn.execute(
        """
        INSERT INTO decisions (
            lead_id, gate_status, reason, sampled, score_with_fatals,
            score_without_fatals, decided_at
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT (lead_id) DO UPDATE SET
            gate_status=excluded.gate_status, reason=excluded.reason,
            sampled=excluded.sampled, score_with_fatals=excluded.score_with_fatals,
            score_without_fatals=excluded.score_without_fatals,
            decided_at=excluded.decided_at
        """,
        (
            decision.lead_id, decision.gate_status, decision.reason,
            int(decision.sampled), decision.score_with_fatals,
            decision.score_without_fatals, _iso(decision.decided_at),
        ),
    )
    conn.commit()


def insert_override(conn: sqlite3.Connection, override: Override) -> None:
    conn.execute(
        """
        INSERT INTO overrides (
            lead_id, check_id, actor, old_status, new_status, reason, created_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (
            override.lead_id, override.check_id, override.actor,
            override.old_status, override.new_status, override.reason,
            _iso(override.created_at),
        ),
    )
    conn.commit()


def get_checks_for_retailer(conn: sqlite3.Connection, retailer_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM checks WHERE retailer_id = ? ORDER BY check_id, version",
        (retailer_id,),
    ).fetchall()


def get_lead(conn: sqlite3.Connection, lead_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM leads WHERE lead_id = ?", (lead_id,)
    ).fetchone()


def get_check_results_for_lead(conn: sqlite3.Connection, lead_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM check_results WHERE lead_id = ? ORDER BY id", (lead_id,)
    ).fetchall()


def get_decision(conn: sqlite3.Connection, lead_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM decisions WHERE lead_id = ?", (lead_id,)
    ).fetchone()


def get_llm_cache(conn: sqlite3.Connection, input_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM llm_cache WHERE input_hash = ?", (input_hash,)
    ).fetchone()


def set_llm_cache(conn: sqlite3.Connection, input_hash: str, response_json: str) -> None:
    conn.execute(
        """
        INSERT INTO llm_cache (input_hash, response_json, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT (input_hash) DO UPDATE SET
            response_json=excluded.response_json, created_at=excluded.created_at
        """,
        (input_hash, response_json, datetime.utcnow().isoformat()),
    )
    conn.commit()
