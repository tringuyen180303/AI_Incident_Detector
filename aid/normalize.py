"""Copy OTLP records from the collector onto the telemetry topic.

This step is stateless. Scale it by running more copies. Partitioning
only starts to matter on the telemetry topic, where the key is the service.
"""

import json
import logging

from confluent_kafka import Consumer

from aid.config import OTLP_LOGS_TOPIC, OTLP_METRICS_TOPIC, OTLP_TRACES_TOPIC, TELEMETRY_TOPIC
from aid.kafka import consumer_config, producer, wait_for_broker
from aid.otlp import otlp_to_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aid.normalize")


def main() -> None:
    wait_for_broker()
    reader = Consumer(consumer_config("normalizer", "aid-normalize"))
    writer = producer("aid-normalize")
    reader.subscribe([OTLP_LOGS_TOPIC, OTLP_METRICS_TOPIC, OTLP_TRACES_TOPIC])
    log.info("normalizing otlp topics onto %s", TELEMETRY_TOPIC)
    while True:
        message = reader.poll(1.0)
        if message is None:
            continue
        if message.error():
            log.error("read failed: %s", message.error())
            continue
        try:
            payload = json.loads(message.value())
            records = otlp_to_events(payload)
        except Exception:
            log.exception("skipping malformed otlp record")
            reader.commit(message=message)
            continue
        try:
            for record in records:
                writer.produce(
                    TELEMETRY_TOPIC,
                    key=record["service"].encode(),
                    value=json.dumps(record).encode(),
                )
            writer.flush(5)
        except Exception:
            log.exception("normalize publish failed; the record will be read again")
            continue
        if records:
            log.info("forwarded %s telemetry records", len(records))
        reader.commit(message=message)


if __name__ == "__main__":
    main()
