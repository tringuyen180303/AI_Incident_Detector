"""Turn one service's telemetry into at most a few anomalies per window.

All events for a service must arrive on the same Kafka partition. The
detector then owns that service's window in memory. See README.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from aid.config import EVIDENCE_LOG_LIMIT


@dataclass
class Rules:
    window_seconds: int = 30
    cooldown_seconds: int = 30
    retry_threshold: int = 5
    min_requests: int = 10
    error_ratio_threshold: float = 0.05
    cpu_threshold: float = 0.8
    cpu_min_samples: int = 3


@dataclass
class ServiceWindow:
    service: str
    rules: Rules
    points: deque = field(default_factory=deque)
    logs: deque = field(default_factory=lambda: deque(maxlen=20))
    last_fired: dict = field(default_factory=dict)

    def observe(self, record: dict) -> list[dict]:
        ts = _parse_ts(record["ts"])
        self._trim(ts)
        self.points.append(record)
        if record["kind"] == "log":
            self.logs.append(record)

        anomalies = []
        for anomaly in (
            self._retries(ts),
            self._error_ratio(ts),
            self._cpu(ts),
        ):
            if anomaly is None:
                continue
            previous = self.last_fired.get(anomaly["signal"])
            if previous and ts - previous < timedelta(seconds=self.rules.cooldown_seconds):
                continue
            self.last_fired[anomaly["signal"]] = ts
            anomalies.append(anomaly)
        return anomalies

    def _trim(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.rules.window_seconds)
        while self.points and _parse_ts(self.points[0]["ts"]) < cutoff:
            self.points.popleft()

    def _retries(self, now: datetime) -> dict | None:
        failed = [
            point
            for point in self.points
            if point["kind"] == "tool_call" and point["attributes"].get("error")
        ]
        by_tool: dict[str, list] = {}
        for point in failed:
            tool = str(point["attributes"].get("tool") or "unknown")
            by_tool.setdefault(tool, []).append(point)
        tripped = {
            tool: calls
            for tool, calls in by_tool.items()
            if len(calls) >= self.rules.retry_threshold
        }
        if not tripped:
            return None
        tool, calls = max(tripped.items(), key=lambda item: len(item[1]))
        count = len(calls)
        return self._anomaly(
            now,
            source="agent",
            signal=f"tool.retry.{tool}",
            value=count,
            severity="high" if count >= self.rules.retry_threshold * 2 else "medium",
            title=f"{self.service} retried {tool} {count} times",
            trigger=calls[-1],
        )

    def _error_ratio(self, now: datetime) -> dict | None:
        points = [point for point in self.points if point["signal"] == "http.error_ratio"]
        requests = sum(int(point["attributes"].get("requests", 0)) for point in points)
        errors = sum(int(point["attributes"].get("errors", 0)) for point in points)
        if requests < self.rules.min_requests:
            return None
        ratio = errors / requests
        if ratio < self.rules.error_ratio_threshold:
            return None
        return self._anomaly(
            now,
            source="application",
            signal="http.error_ratio",
            value=round(ratio, 4),
            severity="high" if ratio >= 0.2 else "medium",
            title=f"{self.service} HTTP error ratio is {ratio:.0%}",
            trigger=points[-1],
        )

    def _cpu(self, now: datetime) -> dict | None:
        points = [point for point in self.points if point["signal"] == "cpu.utilization"]
        recent = points[-self.rules.cpu_min_samples :]
        if len(recent) < self.rules.cpu_min_samples:
            return None
        if any(float(point["value"]) < self.rules.cpu_threshold for point in recent):
            return None
        average = sum(float(point["value"]) for point in recent) / len(recent)
        return self._anomaly(
            now,
            source="infrastructure",
            signal="cpu.utilization",
            value=round(average, 4),
            severity="high" if average >= 0.9 else "medium",
            title=f"{self.service} CPU is {average:.0%}",
            trigger=points[-1],
        )

    def _anomaly(
        self,
        now: datetime,
        *,
        source: str,
        signal: str,
        value: float,
        severity: str,
        title: str,
        trigger: dict,
    ) -> dict:
        start = now - timedelta(seconds=self.rules.window_seconds)
        return {
            "source": source,
            "service": self.service,
            "signal": signal,
            "value": value,
            "severity": severity,
            "title": title,
            "window_start": start.isoformat(),
            "window_end": now.isoformat(),
            "samples": evidence_samples(self.logs, trigger),
        }


def evidence_samples(logs: deque, trigger: dict) -> list[dict]:
    """The only telemetry that will be written to Supabase."""
    errors = [
        record
        for record in logs
        if str(record["attributes"].get("severity", "")).upper() in {"ERROR", "WARN"}
    ]
    chosen = (errors or list(logs))[-EVIDENCE_LOG_LIMIT:]
    samples = [_sample(record) for record in chosen]
    if trigger["kind"] != "log":
        samples.append(_sample(trigger))
    return samples


def _sample(record: dict) -> dict:
    payload = {
        "service": record["service"],
        "signal": record["signal"],
        "body": record.get("body"),
        "value": record.get("value"),
        "attributes": record.get("attributes") or {},
    }
    return {
        "kind": record["kind"],
        "observed_at": record["ts"],
        "payload": payload,
    }


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
