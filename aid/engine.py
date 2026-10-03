"""Write anomalies to Postgres or Supabase. Raw logs are not in this path."""

import json
import logging
import time

from confluent_kafka import Consumer

from aid.alerts import alert_message, opened_key, publish_alert
from aid.config import ANOMALY_TOPIC
from aid.kafka import consumer_config, producer, wait_for_broker
from aid.store import make_store
from aid.summary import summarize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aid.engine")


def main() -> None:
    wait_for_broker()
    store = make_store()
    _wait_for_store(store)
    writer = producer("aid-engine")
    _announce_open(store, writer)
    reader = Consumer(consumer_config("incident-engine", "aid-engine"))
    reader.subscribe([ANOMALY_TOPIC])
    log.info("writing incidents to %s", store.name)
    while True:
        message = reader.poll(1.0)
        if message is None:
            continue
        if message.error():
            log.error("read failed: %s", message.error())
            continue
        try:
            anomaly = json.loads(message.value())
        except json.JSONDecodeError:
            log.exception("skipping malformed anomaly")
            reader.commit(message=message)
            continue
        try:
            prior = store.recent_matches(anomaly["service"], anomaly["signal"])
            still_open = next((item for item in prior if item["status"] == "open"), None)
            if still_open:
                summary, summary_source = still_open["summary"], still_open["summary_source"]
            else:
                summary, summary_source = summarize(anomaly, prior)
            result = store.open_or_append(anomaly, summary, summary_source)
            if result["created"] or not result.get("notified"):
                _publish_opened(writer, anomaly, summary, result["id"])
                store.mark_notified(result["id"])
        except Exception:
            log.exception("incident write failed; the anomaly will be read again")
            continue
        log.info(
            "%s incident %s with %s log samples",
            "opened" if result["created"] else "updated",
            result["id"],
            sum(1 for sample in anomaly["samples"] if sample["kind"] == "log"),
        )
        reader.commit(message=message)


def _announce_open(store, writer) -> None:
    for row in store.unnotified():
        _publish_opened(writer, row, row["summary"], row["id"], status=row["status"])
        store.mark_notified(row["id"])
        log.info("announced open incident %s", row["id"])


def _publish_opened(writer, source: dict, summary: str, incident_id: str, status: str = "open") -> None:
    publish_alert(
        writer,
        alert_message(
            key=opened_key(incident_id),
            kind="opened",
            incident_id=incident_id,
            service=source["service"],
            signal=source["signal"],
            title=source["title"],
            summary=summary,
            severity=source["severity"],
            status=status,
        ),
    )


def _wait_for_store(store) -> None:
    last_error = None
    for _ in range(30):
        try:
            store.ping()
            return
        except Exception as exc:
            last_error = exc
            log.warning("database not ready: %s", exc)
            time.sleep(2)
    raise SystemExit(f"database did not become ready: {last_error}")


if __name__ == "__main__":
    main()
