"""Window one service at a time and publish anomalies.

Run more copies of this process to scale. Kafka gives each copy a subset
of the telemetry partitions. Do not also split a service across copies:
the record key is the service name, so that cannot happen.
"""

import json
import logging

from confluent_kafka import Consumer

from aid.config import (
    ANOMALY_TOPIC,
    COOLDOWN_SECONDS,
    CPU_MIN_SAMPLES,
    CPU_THRESHOLD,
    ERROR_RATIO_THRESHOLD,
    MIN_REQUESTS,
    RETRY_THRESHOLD,
    TELEMETRY_TOPIC,
    WINDOW_SECONDS,
)
from aid.kafka import consumer_config, producer, wait_for_broker
from aid.windows import Rules, ServiceWindow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aid.detect")


def main() -> None:
    wait_for_broker()
    rules = Rules(
        window_seconds=WINDOW_SECONDS,
        cooldown_seconds=COOLDOWN_SECONDS,
        retry_threshold=RETRY_THRESHOLD,
        min_requests=MIN_REQUESTS,
        error_ratio_threshold=ERROR_RATIO_THRESHOLD,
        cpu_threshold=CPU_THRESHOLD,
        cpu_min_samples=CPU_MIN_SAMPLES,
    )
    windows: dict[str, ServiceWindow] = {}
    reader = Consumer(consumer_config("detector", "aid-detect"))
    writer = producer("aid-detect")
    reader.subscribe([TELEMETRY_TOPIC])
    log.info("detecting on %s", TELEMETRY_TOPIC)
    while True:
        message = reader.poll(1.0)
        if message is None:
            continue
        if message.error():
            log.error("read failed: %s", message.error())
            continue
        try:
            record = json.loads(message.value())
        except json.JSONDecodeError:
            log.exception("skipping malformed telemetry")
            reader.commit(message=message)
            continue
        service = record.get("service")
        if not service or "kind" not in record:
            reader.commit(message=message)
            continue
        window = windows.setdefault(service, ServiceWindow(service, rules))
        try:
            for anomaly in window.observe(record):
                writer.produce(
                    ANOMALY_TOPIC,
                    key=f"{anomaly['service']}|{anomaly['signal']}".encode(),
                    value=json.dumps(anomaly).encode(),
                )
                log.info("anomaly %s %s=%s", anomaly["service"], anomaly["signal"], anomaly["value"])
            writer.flush(5)
        except Exception:
            log.exception("anomaly publish failed; the record will be read again")
            continue
        reader.commit(message=message)


if __name__ == "__main__":
    main()
