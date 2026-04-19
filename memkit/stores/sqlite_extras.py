"""
SQLite-backed quarantine and fleet stores.

The quarantine needs to survive restarts — if the cloud critic is offline
when episodes end, in-memory quarantine would silently lose them. SQLite
gives us durability without adding dependencies.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..protocols import (
    Command,
    Episode,
    Event,
    MemoryCandidate,
    Outcome,
    SafetyRule,
    Severity,
    Skill,
)


class SQLiteQuarantineStore:
    """Durable QuarantineStore. Same DB file as episodic/semantic is fine."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS quarantine_candidates (
            candidate_id TEXT PRIMARY KEY,
            episode_json TEXT NOT NULL,
            proposed_skill_json TEXT,
            proposed_safety_rule_json TEXT,
            created_at TEXT NOT NULL,
            enqueued_at REAL NOT NULL,
            reviewed_at REAL,
            review_decision TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_quarantine_pending
            ON quarantine_candidates(enqueued_at)
            WHERE reviewed_at IS NULL;
        """)

    def enqueue(self, candidate: MemoryCandidate) -> None:
        if not candidate.candidate_id:
            candidate.candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
        if not candidate.created_at:
            candidate.created_at = datetime.now(timezone.utc)

        episode_json = _episode_to_json(candidate.episode)
        skill_json = (
            _skill_to_json(candidate.proposed_skill)
            if candidate.proposed_skill else None
        )
        rule_json = (
            _safety_rule_to_json(candidate.proposed_safety_rule)
            if candidate.proposed_safety_rule else None
        )

        self._conn.execute(
            "INSERT OR REPLACE INTO quarantine_candidates"
            "(candidate_id, episode_json, proposed_skill_json, "
            " proposed_safety_rule_json, created_at, enqueued_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                candidate.candidate_id,
                episode_json,
                skill_json,
                rule_json,
                candidate.created_at.isoformat(),
                time.time(),
            ),
        )

    def pending(self, limit: int = 100) -> list[MemoryCandidate]:
        rows = self._conn.execute(
            "SELECT candidate_id, episode_json, proposed_skill_json, "
            "proposed_safety_rule_json, created_at "
            "FROM quarantine_candidates WHERE reviewed_at IS NULL "
            "ORDER BY enqueued_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_candidate(r) for r in rows]

    def mark_reviewed(self, candidate_id: str, decision: str) -> None:
        cur = self._conn.execute(
            "UPDATE quarantine_candidates "
            "SET reviewed_at = ?, review_decision = ? "
            "WHERE candidate_id = ? AND reviewed_at IS NULL",
            (time.time(), decision, candidate_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"no pending candidate {candidate_id}")

    def prune_expired(self, ttl_hours: float = 24) -> int:
        cutoff = time.time() - ttl_hours * 3600
        cur = self._conn.execute(
            "DELETE FROM quarantine_candidates "
            "WHERE reviewed_at IS NULL AND enqueued_at < ?",
            (cutoff,),
        )
        return cur.rowcount

    def close(self):
        self._conn.close()


class SQLiteFleetStore:
    """Durable FleetStore — cross-agent shared memory with validation gating.

    This is single-node SQLite for simplicity. In a real deployment, this
    lives on the cloud side and is accessed via HTTP or another RPC.
    Here we give the same Python interface so projects can develop against
    it locally before wiring in the real cloud store.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS fleet_skills (
            skill_id TEXT NOT NULL,
            source_agent_id TEXT NOT NULL,
            cli_sequence TEXT NOT NULL,
            cli_signature TEXT NOT NULL,
            preconditions TEXT NOT NULL,
            environment_class TEXT NOT NULL,
            success_rate REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            confidence REAL NOT NULL,
            last_used TEXT NOT NULL,
            provenance TEXT NOT NULL,
            contributed_at REAL NOT NULL,
            PRIMARY KEY (skill_id, source_agent_id)
        );
        CREATE INDEX IF NOT EXISTS ix_fleet_signature
            ON fleet_skills(cli_signature, environment_class);
        """)

    def contribute(self, skill: Skill, source_agent_id: str) -> None:
        cli_sig = "|".join(c.signature() for c in skill.cli_sequence)
        self._conn.execute(
            "INSERT OR REPLACE INTO fleet_skills"
            "(skill_id, source_agent_id, cli_sequence, cli_signature, "
            " preconditions, environment_class, success_rate, sample_count, "
            " confidence, last_used, provenance, contributed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                skill.skill_id,
                source_agent_id,
                json.dumps([{"name": c.name, "params": c.params}
                            for c in skill.cli_sequence]),
                cli_sig,
                json.dumps(skill.preconditions),
                skill.environment_class,
                skill.success_rate,
                skill.sample_count,
                skill.confidence,
                skill.last_used.isoformat(),
                json.dumps({**skill.provenance, "source_agent_id": source_agent_id}),
                time.time(),
            ),
        )

    def query(self, *, task_type: str | None = None,
              environment_fingerprint: str | None = None,
              min_validations: int = 2,
              limit: int = 10) -> list[Skill]:
        """Returns aggregated skills, filtered by validation threshold.

        A skill is "validated" when at least `min_validations` distinct agents
        have independently contributed it (same cli_signature + environment_class).
        """
        sql = """
        SELECT cli_signature, environment_class,
               COUNT(DISTINCT source_agent_id) AS validators,
               AVG(success_rate) AS avg_success,
               SUM(sample_count) AS total_samples,
               AVG(confidence) AS avg_confidence,
               MAX(last_used) AS last_used,
               MIN(cli_sequence) AS sample_cli_seq,
               MIN(preconditions) AS sample_preconds,
               MIN(skill_id) AS sample_skill_id
        FROM fleet_skills
        """
        filters = []
        args: list = []
        if environment_fingerprint:
            filters.append("environment_class = ?")
            args.append(environment_fingerprint)
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += """
        GROUP BY cli_signature, environment_class
        HAVING validators >= ?
        ORDER BY avg_confidence DESC, total_samples DESC
        LIMIT ?
        """
        args.extend([min_validations, limit])

        skills: list[Skill] = []
        for row in self._conn.execute(sql, args):
            (cli_sig, env, validators, avg_success, total_samples,
             avg_confidence, last_used, sample_cli_seq, sample_preconds,
             sample_skill_id) = row
            cli_sequence = [
                Command(name=c["name"], params=c.get("params", {}))
                for c in json.loads(sample_cli_seq)
            ]
            # task_type post-filter
            if task_type and cli_sequence:
                first_cmd = cli_sequence[0].name
                if task_type not in first_cmd:
                    continue
            skills.append(Skill(
                skill_id=f"fleet_{sample_skill_id}",
                cli_sequence=cli_sequence,
                preconditions=json.loads(sample_preconds),
                environment_class=env,
                success_rate=avg_success,
                sample_count=total_samples,
                confidence=avg_confidence,
                last_used=datetime.fromisoformat(last_used),
                provenance={
                    "source": "fleet",
                    "validator_count": validators,
                    "representative_skill_id": sample_skill_id,
                },
            ))
        return skills

    def close(self):
        self._conn.close()


class InMemoryFleetStore:
    """In-memory FleetStore for tests and local development."""

    def __init__(self):
        # key: (cli_signature, env_class) -> list of (agent_id, skill)
        self._contributions: dict[tuple[str, str], list[tuple[str, Skill]]] = {}

    def contribute(self, skill: Skill, source_agent_id: str) -> None:
        cli_sig = "|".join(c.signature() for c in skill.cli_sequence)
        key = (cli_sig, skill.environment_class)
        entries = self._contributions.setdefault(key, [])
        # Replace existing entry from same agent
        entries[:] = [(a, s) for a, s in entries if a != source_agent_id]
        entries.append((source_agent_id, skill))

    def query(self, *, task_type: str | None = None,
              environment_fingerprint: str | None = None,
              min_validations: int = 2,
              limit: int = 10) -> list[Skill]:
        results: list[Skill] = []
        for (cli_sig, env), entries in self._contributions.items():
            if environment_fingerprint and env != environment_fingerprint:
                continue
            # Count distinct agents
            distinct_agents = {agent_id for agent_id, _ in entries}
            if len(distinct_agents) < min_validations:
                continue

            skills_here = [s for _, s in entries]
            if task_type:
                if not skills_here[0].cli_sequence:
                    continue
                first_cmd = skills_here[0].cli_sequence[0].name
                if task_type not in first_cmd:
                    continue

            # Aggregate — use first skill as template, average the numbers
            template = skills_here[0]
            avg_success = sum(s.success_rate for s in skills_here) / len(skills_here)
            total_samples = sum(s.sample_count for s in skills_here)
            avg_conf = sum(s.confidence for s in skills_here) / len(skills_here)
            most_recent = max(s.last_used for s in skills_here)

            results.append(Skill(
                skill_id=f"fleet_{template.skill_id}",
                cli_sequence=template.cli_sequence,
                preconditions=template.preconditions,
                environment_class=env,
                success_rate=avg_success,
                sample_count=total_samples,
                confidence=avg_conf,
                last_used=most_recent,
                provenance={
                    "source": "fleet",
                    "validator_count": len(distinct_agents),
                },
            ))

        results.sort(key=lambda s: (s.confidence, s.sample_count), reverse=True)
        return results[:limit]


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _episode_to_json(ep: Episode) -> str:
    return json.dumps({
        "episode_id": ep.episode_id,
        "task_id": ep.task_id,
        "started_at": ep.started_at.isoformat(),
        "events": [
            {"t": e.t, "kind": e.kind, "payload": e.payload}
            for e in ep.events
        ],
        "outcome": ep.outcome.value,
        "anomaly_flags": ep.anomaly_flags,
        "env_fingerprint": ep.env_fingerprint,
        "human_feedback": ep.human_feedback,
    })


def _episode_from_json(s: str) -> Episode:
    data = json.loads(s)
    return Episode(
        episode_id=data["episode_id"],
        task_id=data["task_id"],
        started_at=datetime.fromisoformat(data["started_at"]),
        events=[Event(t=e["t"], kind=e["kind"], payload=e["payload"])
                for e in data["events"]],
        outcome=Outcome(data["outcome"]),
        anomaly_flags=data["anomaly_flags"],
        env_fingerprint=data.get("env_fingerprint"),
        human_feedback=data.get("human_feedback"),
    )


def _skill_to_json(s: Skill) -> str:
    return json.dumps({
        "skill_id": s.skill_id,
        "cli_sequence": [{"name": c.name, "params": c.params} for c in s.cli_sequence],
        "preconditions": s.preconditions,
        "environment_class": s.environment_class,
        "success_rate": s.success_rate,
        "sample_count": s.sample_count,
        "confidence": s.confidence,
        "last_used": s.last_used.isoformat(),
        "provenance": s.provenance,
        "supersedes": s.supersedes,
    })


def _skill_from_json(s: str) -> Skill:
    data = json.loads(s)
    return Skill(
        skill_id=data["skill_id"],
        cli_sequence=[Command(name=c["name"], params=c.get("params", {}))
                      for c in data["cli_sequence"]],
        preconditions=data["preconditions"],
        environment_class=data["environment_class"],
        success_rate=data["success_rate"],
        sample_count=data["sample_count"],
        confidence=data["confidence"],
        last_used=datetime.fromisoformat(data["last_used"]),
        provenance=data["provenance"],
        supersedes=data.get("supersedes", []),
    )


def _safety_rule_to_json(r: SafetyRule) -> str:
    return json.dumps({
        "rule_id": r.rule_id,
        "severity": r.severity.value,
        "context_predicate": r.context_predicate,
        "forbidden_command_pattern": r.forbidden_command_pattern,
        "unless_params": r.unless_params,
        "source": r.source,
        "created": r.created.isoformat(),
        "supersedes": r.supersedes,
    })


def _safety_rule_from_json(s: str) -> SafetyRule:
    data = json.loads(s)
    return SafetyRule(
        rule_id=data["rule_id"],
        severity=Severity(data["severity"]),
        context_predicate=data["context_predicate"],
        forbidden_command_pattern=data["forbidden_command_pattern"],
        unless_params=data.get("unless_params"),
        source=data.get("source", "human_review"),
        created=datetime.fromisoformat(data["created"]),
        supersedes=data.get("supersedes"),
    )


def _row_to_candidate(row: tuple) -> MemoryCandidate:
    candidate_id, episode_json, skill_json, rule_json, created_at = row
    return MemoryCandidate(
        candidate_id=candidate_id,
        episode=_episode_from_json(episode_json),
        proposed_skill=_skill_from_json(skill_json) if skill_json else None,
        proposed_safety_rule=_safety_rule_from_json(rule_json) if rule_json else None,
        created_at=datetime.fromisoformat(created_at),
    )
