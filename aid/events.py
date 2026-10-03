from datetime import datetime, timezone


def event(
    *,
    kind: str,
    source: str,
    service: str,
    signal: str,
    ts: datetime | None = None,
    value: float | None = None,
    body: str | None = None,
    attributes: dict | None = None,
) -> dict:
    when = ts or datetime.now(timezone.utc)
    return {
        "kind": kind,
        "source": source,
        "service": service,
        "signal": signal,
        "ts": when.isoformat(),
        "value": value,
        "body": body,
        "attributes": attributes or {},
    }
