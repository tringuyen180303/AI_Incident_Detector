"""Write anomalies to Postgres or Supabase. Raw logs are not in this path."""

import json
import logging
import time

from confluent_kafka import Consumer

from aid.config import ANOMALY_TOPIC
from aid.kafka import consumer_config, wait_for_broker
from aid.store import make_store
from aid.summary import summarize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aid.engine")


def main() -> None:
    wait_for_broker()
    store = make_store()
    _wait_for_store(store)
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
