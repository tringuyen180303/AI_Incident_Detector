"""One alert, many consumers. The key keeps a service's alerts in order."""

import json

from aid.config import NOTIFICATIONS_TOPIC


def opened_key(incident_id: str) -> str:
    return f"opened:{incident_id}"


def status_key(incident_id: str, status: str) -> str:
    return f"status:{incident_id}:{status}"


def alert_message(
    *,
    key: str,
    kind: str,
    incident_id: str,
    service: str,
    signal: str,
    title: str,
    summary: str,
    severity: str,
    status: str,
) -> dict:
    return {
        "notification_key": key,
        "kind": kind,
        "incident_id": incident_id,
        "service": service,
        "signal": signal,
        "title": title,
        "summary": summary,
        "severity": severity,
        "status": status,
    }


def publish_alert(writer, message: dict) -> None:
    writer.produce(
        NOTIFICATIONS_TOPIC,
        key=f"{message['service']}|{message['signal']}".encode(),
        value=json.dumps(message).encode(),
    )
    writer.flush(10)
