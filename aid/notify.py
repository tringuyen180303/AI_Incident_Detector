"""Deliver alerts. Each channel is its own consumer group, so workers scale apart."""

import json
import logging
import sys
import time
from urllib import error, request

from confluent_kafka import Consumer

from aid.config import NOTIFICATIONS_TOPIC, NOTIFY_WEBHOOK_URL
from aid.kafka import consumer_config, wait_for_broker
from aid.store import make_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aid.notify")

CHANNELS = {"board", "webhook"}


def main() -> None:
    channel = sys.argv[1] if len(sys.argv) > 1 else ""
    if channel not in CHANNELS:
        raise SystemExit("usage: python -m aid.notify board|webhook")
    wait_for_broker()
    store = make_store()
    _wait_for_store(store)
    config = consumer_config(f"notify-{channel}", f"aid-notify-{channel}")
    config["auto.offset.reset"] = "earliest"
    reader = Consumer(config)
    reader.subscribe([NOTIFICATIONS_TOPIC])
    log.info("notification channel %s reading %s", channel, NOTIFICATIONS_TOPIC)
    while True:
        message = reader.poll(1.0)
        if message is None:
            continue
        if message.error():
            log.error("read failed: %s", message.error())
            continue
        try:
            alert = json.loads(message.value())
            _deliver(store, channel, alert)
        except Exception:
            log.exception("delivery failed; the alert will be read again")
            continue
        reader.commit(message=message)


def _deliver(store, channel: str, alert: dict) -> None:
    if channel == "webhook":
        if not _post_webhook(alert):
            log.info("webhook worker kept %s %s on the log", alert["service"], alert["kind"])
            return
    store.record_notification(alert, channel)
    log.info("delivered %s to %s via %s", alert["notification_key"], alert["service"], channel)


def _post_webhook(alert: dict) -> bool:
    if not NOTIFY_WEBHOOK_URL:
        return False
    body = json.dumps(alert).encode()
    req = request.Request(
        NOTIFY_WEBHOOK_URL,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=8) as response:
            response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"webhook {exc.code}: {detail}") from exc
    return True


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
