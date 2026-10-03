import json
import logging
from datetime import datetime, timezone
from urllib import error, request

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from aid.config import DATABASE_URL, EVIDENCE_LOG_LIMIT, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

log = logging.getLogger("aid.store")


def make_store():
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseStore(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return PostgresStore(DATABASE_URL)


class PostgresStore:
    name = "postgres"

    def __init__(self, url: str):
        self.url = url

    def ping(self) -> None:
        self.stats()

    def stats(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                select
                  (select count(*) from incidents) as incidents,
                  (select count(*) from incident_evidence where kind = 'log') as log_samples
                """
            ).fetchone()
        return {"store": self.name, "incidents": row["incidents"], "log_samples": row["log_samples"]}

    def list_incidents(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select
                  i.id::text,
                  i.title,
                  i.summary,
                  i.summary_source,
                  i.severity,
                  i.status,
                  i.source,
                  i.service,
                  i.signal,
                  i.value,
                  i.started_at,
                  i.resolved_at,
                  i.created_at,
                  coalesce(
                    (
                      select json_agg(
                        json_build_object(
                          'kind', e.kind,
                          'observed_at', e.observed_at,
                          'payload', e.payload
                        )
                        order by e.observed_at
                      )
                      from incident_evidence e
                      where e.incident_id = i.id
                    ),
                    '[]'::json
                  ) as evidence
                from incidents i
                order by i.created_at desc
                limit 50
                """
            ).fetchall()
        return [_jsonable(row) for row in rows]

    def recent_matches(self, service: str, signal: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select title, summary, summary_source, status, value, created_at
                from incidents
                where service = %s and signal = %s
                order by created_at desc
                limit 3
                """,
                (service, signal),
            ).fetchall()
        return [_plain(row) for row in rows]

    def open_or_append(self, anomaly: dict, summary: str, summary_source: str) -> dict:
        try:
            return self._write(anomaly, summary, summary_source)
        except UniqueViolation:
            return self._write(anomaly, summary, summary_source, append_only=True)

    def set_status(self, incident_id: str, status: str) -> dict | None:
        if status not in {"acknowledged", "resolved", "open"}:
            raise ValueError("status must be open, acknowledged, or resolved")
        with self._connect() as conn:
            row = conn.execute(
                """
                update incidents
                set status = %s,
                    updated_at = now(),
                    resolved_at = case when %s = 'resolved' then now() else null end
                where id = %s
                returning id::text, status
                """,
                (status, status, incident_id),
            ).fetchone()
            if row is None:
                return None
            _event(conn, incident_id, "status_changed", {"status": status}, actor="dashboard")
        return dict(row)

    def _write(self, anomaly: dict, summary: str, summary_source: str, append_only: bool = False) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                select id::text
                from incidents
                where service = %s and signal = %s and status = 'open'
                for update
                """,
                (anomaly["service"], anomaly["signal"]),
            ).fetchone()
            if row is None and append_only:
                raise RuntimeError("open incident disappeared before retry")
            if row is not None:
                added = _insert_evidence(conn, row["id"], anomaly["samples"])
                conn.execute(
                    "update incidents set updated_at = now(), value = %s where id = %s",
                    (anomaly["value"], row["id"]),
                )
                if added:
                    _event(conn, row["id"], "evidence_appended", {"count": added}, actor="incident-engine")
                return {"id": row["id"], "created": False}

            inserted = conn.execute(
                """
                insert into incidents (
                  title, summary, summary_source, severity, status, source,
                  service, signal, value, started_at
                ) values (%s, %s, %s, %s, 'open', %s, %s, %s, %s, %s)
                returning id::text
                """,
                (
                    anomaly["title"],
                    summary,
                    summary_source,
                    anomaly["severity"],
                    anomaly["source"],
                    anomaly["service"],
                    anomaly["signal"],
                    anomaly["value"],
                    anomaly["window_start"],
                ),
            ).fetchone()
            _insert_evidence(conn, inserted["id"], anomaly["samples"])
            _event(conn, inserted["id"], "created", {"summary_source": summary_source}, actor="incident-engine")
            return {"id": inserted["id"], "created": True}

    def _connect(self):
        return psycopg.connect(self.url, row_factory=dict_row)


class SupabaseStore:
    name = "supabase"

    def __init__(self, url: str, key: str):
        self.base = f"{url}/rest/v1"
        self.key = key

    def ping(self) -> None:
        self.stats()

    def stats(self) -> dict:
        return {
            "store": self.name,
            "incidents": self._count("incidents"),
            "log_samples": self._count("incident_evidence", "kind=eq.log"),
        }

    def list_incidents(self) -> list[dict]:
        rows = self._json(
            "GET",
            "/incidents?select=id,title,summary,summary_source,severity,status,source,service,signal,value,started_at,resolved_at,created_at,incident_evidence(kind,observed_at,payload)&order=created_at.desc&limit=50",
        )
        incidents = []
        for row in rows:
            evidence = row.pop("incident_evidence", []) or []
            evidence.sort(key=lambda item: item.get("observed_at") or "")
            row["evidence"] = evidence
            incidents.append(row)
        return incidents

    def recent_matches(self, service: str, signal: str) -> list[dict]:
        return self._json(
            "GET",
            "/incidents?select=title,summary,summary_source,status,value,created_at"
            f"&service=eq.{_query(service)}&signal=eq.{_query(signal)}"
            "&order=created_at.desc&limit=3",
        )

    def open_or_append(self, anomaly: dict, summary: str, summary_source: str, _retry: bool = True) -> dict:
        existing = self._json(
            "GET",
            f"/incidents?select=id&service=eq.{_query(anomaly['service'])}&signal=eq.{_query(anomaly['signal'])}&status=eq.open&limit=1",
        )
        if existing:
            incident_id = existing[0]["id"]
            added = self._add_evidence(incident_id, anomaly["samples"])
            self._json(
                "PATCH",
                f"/incidents?id=eq.{incident_id}",
                {"value": anomaly["value"], "updated_at": _now()},
            )
            if added:
                self._add_event(incident_id, "evidence_appended", {"count": added})
            return {"id": incident_id, "created": False}

        try:
            inserted = self._json(
                "POST",
                "/incidents",
                {
                    "title": anomaly["title"],
                    "summary": summary,
                    "summary_source": summary_source,
                    "severity": anomaly["severity"],
                    "status": "open",
                    "source": anomaly["source"],
                    "service": anomaly["service"],
                    "signal": anomaly["signal"],
                    "value": anomaly["value"],
                    "started_at": anomaly["window_start"],
                },
            )
        except RestError as exc:
            if not _retry or exc.status not in {409, 400}:
                raise
            return self.open_or_append(anomaly, summary, summary_source, _retry=False)
        incident_id = inserted[0]["id"]
        self._add_evidence(incident_id, anomaly["samples"])
        self._add_event(incident_id, "created", {"summary_source": summary_source})
        return {"id": incident_id, "created": True}

    def set_status(self, incident_id: str, status: str) -> dict | None:
        if status not in {"acknowledged", "resolved", "open"}:
            raise ValueError("status must be open, acknowledged, or resolved")
        rows = self._json(
            "PATCH",
            f"/incidents?id=eq.{incident_id}",
            {
                "status": status,
                "updated_at": _now(),
                "resolved_at": _now() if status == "resolved" else None,
            },
        )
        if not rows:
            return None
        self._add_event(incident_id, "status_changed", {"status": status}, actor="dashboard")
        return {"id": incident_id, "status": status}

    def _add_evidence(self, incident_id: str, samples: list[dict]) -> int:
        existing = self._json(
            "GET",
            f"/incident_evidence?select=kind,observed_at,payload&incident_id=eq.{incident_id}",
        )
        seen = {_sample_key(row) for row in existing}
        log_count = sum(1 for row in existing if row["kind"] == "log")
        other_count = len(existing) - log_count
        fresh = []
        for sample in samples:
            row = {
                "incident_id": incident_id,
                "kind": sample["kind"],
                "observed_at": sample["observed_at"],
                "payload": sample["payload"],
            }
            if _sample_key(row) in seen:
                continue
            if sample["kind"] == "log":
                if log_count >= EVIDENCE_LOG_LIMIT:
                    continue
                log_count += 1
            elif other_count >= 2:
                continue
            else:
                other_count += 1
            fresh.append(row)
            seen.add(_sample_key(row))
        if fresh:
            self._json("POST", "/incident_evidence", fresh)
        return len(fresh)

    def _add_event(self, incident_id: str, kind: str, detail: dict, actor: str = "incident-engine") -> None:
        self._json(
            "POST",
            "/incident_events",
            {"incident_id": incident_id, "kind": kind, "actor": actor, "detail": detail},
        )

    def _count(self, table: str, query: str = "") -> int:
        path = f"/{table}?select=id"
        if query:
            path = f"{path}&{query}"
        response = self._send("GET", path, headers={"Range": "0-0", "Prefer": "count=exact"})
        content_range = response.headers.get("content-range", "")
        if "/" not in content_range:
            return 0
        total = content_range.rsplit("/", 1)[-1]
        return 0 if total == "*" else int(total)

    def _json(self, method: str, path: str, body=None):
        response = self._send(method, path, body=body, headers={"Prefer": "return=representation"})
        if not response.data:
            return []
        parsed = json.loads(response.data.decode())
        if isinstance(parsed, list):
            return parsed
        return [parsed]

    def _send(self, method: str, path: str, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        head = {
            "apikey": self.key,
            "authorization": f"Bearer {self.key}",
            "content-type": "application/json",
        }
        if headers:
            head.update(headers)
        req = request.Request(self.base + path, data=data, headers=head, method=method)
        try:
            with request.urlopen(req, timeout=15) as response:
                return _Response(response.status, response.headers, response.read())
        except error.HTTPError as exc:
            detail = exc.read().decode()
            raise RestError(exc.code, detail) from exc

    def _connect(self):
        raise NotImplementedError


class RestError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"supabase {status}: {body}")
        self.status = status
        self.body = body


class _Response:
    def __init__(self, status, headers, data):
        self.status = status
        self.headers = headers
        self.data = data


def _insert_evidence(conn, incident_id: str, samples: list[dict]) -> int:
    counts = conn.execute(
        """
        select
          count(*) filter (where kind = 'log') as logs,
          count(*) filter (where kind <> 'log') as others
        from incident_evidence
        where incident_id = %s
        """,
        (incident_id,),
    ).fetchone()
    log_count = counts["logs"]
    other_count = counts["others"]
    added = 0
    for sample in samples:
        if sample["kind"] == "log":
            if log_count >= EVIDENCE_LOG_LIMIT:
                continue
            log_count += 1
        elif other_count >= 2:
            continue
        else:
            other_count += 1
        payload = json.dumps(sample["payload"], sort_keys=True)
        exists = conn.execute(
            """
            select 1
            from incident_evidence
            where incident_id = %s
              and kind = %s
              and observed_at = %s
              and payload = %s::jsonb
            """,
            (incident_id, sample["kind"], sample["observed_at"], payload),
        ).fetchone()
        if exists:
            if sample["kind"] == "log":
                log_count -= 1
            else:
                other_count -= 1
            continue
        conn.execute(
            """
            insert into incident_evidence (incident_id, kind, observed_at, payload)
            values (%s, %s, %s, %s::jsonb)
            """,
            (incident_id, sample["kind"], sample["observed_at"], payload),
        )
        added += 1
    return added


def _event(conn, incident_id: str, kind: str, detail: dict, actor: str) -> None:
    conn.execute(
        """
        insert into incident_events (incident_id, kind, actor, detail)
        values (%s, %s, %s, %s::jsonb)
        """,
        (incident_id, kind, actor, json.dumps(detail)),
    )


def _sample_key(row: dict) -> str:
    return json.dumps(
        {
            "kind": row["kind"],
            "observed_at": row["observed_at"],
            "payload": row["payload"],
        },
        sort_keys=True,
        default=str,
    )


def _query(value: str) -> str:
    return request.quote(value, safe="")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plain(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def _jsonable(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, str) and key == "evidence":
            out[key] = json.loads(value)
        else:
            out[key] = value
    evidence = out.get("evidence") or []
    normalized = []
    for item in evidence:
        if isinstance(item.get("observed_at"), datetime):
            item = {**item, "observed_at": item["observed_at"].isoformat()}
        normalized.append(item)
    out["evidence"] = normalized
    return out
