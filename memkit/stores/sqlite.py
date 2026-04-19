"""
SQLite-backed implementations of EpisodicStore and SemanticStore.

These are the durable local-side stores. WAL mode, append-only for events,
mutable for skill confidence.

We deliberately don't use an ORM — the schemas are narrow and stable, and
direct SQL makes migration paths explicit.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..protocols import Command, Episode, Event, Outcome, Skill


class SQLiteEpisodicStore:
    """Durable EpisodicStore backed by SQLite. WAL mode."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS episodes (
            episode_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            env_fingerprint TEXT,
            outcome TEXT NOT NULL DEFAULT 'unknown',
            anomaly_flags TEXT NOT NULL DEFAULT '[]',
            ended_at REAL,
            human_feedback TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_episodes_active
            ON episodes(ended_at) WHERE ended_at IS NULL;
        CREATE INDEX IF NOT EXISTS ix_episodes_ended
            ON episodes(ended_at) WHERE ended_at IS NOT NULL;

        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id TEXT NOT NULL REFERENCES episodes(episode_id),
            t REAL NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_events_episode
            ON events(episode_id, event_id);
        """)

    def start_episode(self, task_id: str, env_fingerprint: str | None = None) -> Episode:
        episode_id = f"ep_{uuid.uuid4().hex[:12]}"
        started_at = datetime.now(timezone.utc)
        self._conn.execute(
            "INSERT INTO episodes(episode_id, task_id, started_at, env_fingerprint) "
            "VALUES (?, ?, ?, ?)",
            (episode_id, task_id, started_at.isoformat(), env_fingerprint),
        )
        return Episode(
            episode_id=episode_id,
            task_id=task_id,
            started_at=started_at,
            env_fingerprint=env_fingerprint,
        )

    def append_event(self, episode_id: str, event: Event) -> None:
        row = self._conn.execute(
            "SELECT ended_at FROM episodes WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown episode {episode_id}")
        if row[0] is not None:
            raise RuntimeError(f"episode {episode_id} already ended")
        self._conn.execute(
            "INSERT INTO events(episode_id, t, kind, payload) VALUES (?, ?, ?, ?)",
            (episode_id, event.t, event.kind, json.dumps(event.payload)),
        )

    def end_episode(self, episode_id: str, outcome: Outcome,
                    anomaly_flags: list[str] | None = None) -> Episode:
        flags = anomaly_flags or []
        self._conn.execute(
            "UPDATE episodes SET outcome = ?, anomaly_flags = ?, ended_at = ? "
            "WHERE episode_id = ?",
            (outcome.value, json.dumps(flags), time.time(), episode_id),
        )
        ep = self.get_episode(episode_id)
        if ep is None:
            raise KeyError(f"unknown episode {episode_id}")
        return ep

    def get_episode(self, episode_id: str) -> Episode | None:
        row = self._conn.execute(
            "SELECT task_id, started_at, env_fingerprint, outcome, anomaly_flags, "
            "human_feedback FROM episodes WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
        if row is None:
            return None
        task_id, started_at, env_fp, outcome, anomalies, feedback = row
        events = [
            Event(t=r[0], kind=r[1], payload=json.loads(r[2]))
            for r in self._conn.execute(
                "SELECT t, kind, payload FROM events WHERE episode_id = ? "
                "ORDER BY event_id ASC",
                (episode_id,),
            )
        ]
        return Episode(
            episode_id=episode_id,
            task_id=task_id,
            started_at=datetime.fromisoformat(started_at),
            events=events,
            outcome=Outcome(outcome),
            anomaly_flags=json.loads(anomalies),
            env_fingerprint=env_fp,
            human_feedback=json.loads(feedback) if feedback else None,
        )

    def active_episodes(self) -> list[Episode]:
        ids = [
            r[0] for r in self._conn.execute(
                "SELECT episode_id FROM episodes WHERE ended_at IS NULL",
            )
        ]
        return [ep for ep in (self.get_episode(i) for i in ids) if ep is not None]

    def evict_completed(self, older_than_seconds: float = 3600) -> int:
        cutoff = time.time() - older_than_seconds
        # Cascade delete events first (no FK cascade on SQLite by default)
        expired_ids = [
            r[0] for r in self._conn.execute(
                "SELECT episode_id FROM episodes "
                "WHERE ended_at IS NOT NULL AND ended_at < ?",
                (cutoff,),
            )
        ]
        if not expired_ids:
            return 0
        placeholders = ",".join("?" * len(expired_ids))
        self._conn.execute(
            f"DELETE FROM events WHERE episode_id IN ({placeholders})",
            expired_ids,
        )
        self._conn.execute(
            f"DELETE FROM episodes WHERE episode_id IN ({placeholders})",
            expired_ids,
        )
        return len(expired_ids)

    def close(self):
        self._conn.close()


class SQLiteSemanticStore:
    """Durable SemanticStore. Same DB file as episodic is fine."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY,
            cli_sequence TEXT NOT NULL,
            preconditions TEXT NOT NULL,
            environment_class TEXT NOT NULL,
            success_rate REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            confidence REAL NOT NULL,
            last_used TEXT NOT NULL,
            provenance TEXT NOT NULL,
            supersedes TEXT NOT NULL DEFAULT '[]',
            superseded_by TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_skills_env
            ON skills(environment_class) WHERE superseded_by IS NULL;
        """)

    def add_skill(self, skill: Skill) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO skills(skill_id, cli_sequence, preconditions, "
            "environment_class, success_rate, sample_count, confidence, last_used, "
            "provenance, supersedes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                skill.skill_id,
                json.dumps([{"name": c.name, "params": c.params} for c in skill.cli_sequence]),
                json.dumps(skill.preconditions),
                skill.environment_class,
                skill.success_rate,
                skill.sample_count,
                skill.confidence,
                skill.last_used.isoformat(),
                json.dumps(skill.provenance),
                json.dumps(skill.supersedes),
            ),
        )
        # Mark superseded ones
        for old_id in skill.supersedes:
            self._conn.execute(
                "UPDATE skills SET superseded_by = ? WHERE skill_id = ?",
                (skill.skill_id, old_id),
            )

    def get_skill(self, skill_id: str) -> Skill | None:
        row = self._conn.execute(
            "SELECT cli_sequence, preconditions, environment_class, success_rate, "
            "sample_count, confidence, last_used, provenance, supersedes "
            "FROM skills WHERE skill_id = ?",
            (skill_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_skill(skill_id, row)

    def query(self, *, task_type: str | None = None,
              environment_class: str | None = None,
              min_confidence: float = 0.0,
              limit: int = 10) -> list[Skill]:
        sql = (
            "SELECT skill_id, cli_sequence, preconditions, environment_class, "
            "success_rate, sample_count, confidence, last_used, provenance, supersedes "
            "FROM skills WHERE superseded_by IS NULL AND confidence >= ?"
        )
        args: list = [min_confidence]
        if environment_class:
            sql += " AND environment_class = ?"
            args.append(environment_class)
        sql += " ORDER BY confidence DESC, sample_count DESC LIMIT ?"
        args.append(limit)

        skills = [
            _row_to_skill(row[0], row[1:])
            for row in self._conn.execute(sql, args)
        ]
        # task_type filter applied in Python — hits the first command name
        if task_type:
            import fnmatch
            skills = [
                s for s in skills
                if s.cli_sequence and (
                    task_type in s.cli_sequence[0].name or
                    fnmatch.fnmatch(s.cli_sequence[0].name, task_type)
                )
            ]
        return skills

    def update_confidence(self, skill_id: str, new_confidence: float) -> None:
        clamped = max(0.0, min(1.0, new_confidence))
        cur = self._conn.execute(
            "UPDATE skills SET confidence = ? WHERE skill_id = ?",
            (clamped, skill_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"no skill {skill_id}")

    def supersede(self, old_id: str, new_skill: Skill) -> None:
        if old_id not in new_skill.supersedes:
            new_skill.supersedes.append(old_id)
        self.add_skill(new_skill)

    def decay(self, unused_days: float = 30, rate: float = 0.9) -> int:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=unused_days)).isoformat()
        cur = self._conn.execute(
            "UPDATE skills SET confidence = MAX(0.0, confidence * ?) "
            "WHERE last_used < ? AND superseded_by IS NULL",
            (rate, cutoff),
        )
        return cur.rowcount

    def close(self):
        self._conn.close()


def _row_to_skill(skill_id: str, row: tuple) -> Skill:
    (cli_seq_json, preconditions_json, env_class, success_rate, sample_count,
     confidence, last_used, provenance_json, supersedes_json) = row
    cli_sequence = [
        Command(name=c["name"], params=c.get("params", {}))
        for c in json.loads(cli_seq_json)
    ]
    return Skill(
        skill_id=skill_id,
        cli_sequence=cli_sequence,
        preconditions=json.loads(preconditions_json),
        environment_class=env_class,
        success_rate=success_rate,
        sample_count=sample_count,
        confidence=confidence,
        last_used=datetime.fromisoformat(last_used),
        provenance=json.loads(provenance_json),
        supersedes=json.loads(supersedes_json),
    )
