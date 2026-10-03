import logging
import time

from confluent_kafka import KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from aid.config import (
    ANOMALY_PARTITIONS,
    ANOMALY_RETENTION_MS,
    ANOMALY_TOPIC,
    BROKERS,
    OTLP_LOGS_TOPIC,
    OTLP_METRICS_TOPIC,
    OTLP_PARTITIONS,
    OTLP_TRACES_TOPIC,
    TELEMETRY_PARTITIONS,
    TELEMETRY_RETENTION_MS,
    TELEMETRY_TOPIC,
)

log = logging.getLogger("aid.kafka")

CLIENT = {
    "bootstrap.servers": BROKERS,
    "message.max.bytes": 10_000_000,
}


def wait_for_broker() -> None:
    last_error = None
    for _ in range(30):
        try:
            ensure_topics()
            return
        except Exception as exc:
            last_error = exc
            log.warning("kafka not ready: %s", exc)
            time.sleep(2)
    raise SystemExit(f"kafka did not become ready: {last_error}")


def ensure_topics() -> None:
    admin = AdminClient(CLIENT)
    specs = [
        (TELEMETRY_TOPIC, TELEMETRY_PARTITIONS, TELEMETRY_RETENTION_MS),
        (ANOMALY_TOPIC, ANOMALY_PARTITIONS, ANOMALY_RETENTION_MS),
        (OTLP_LOGS_TOPIC, OTLP_PARTITIONS, TELEMETRY_RETENTION_MS),
        (OTLP_METRICS_TOPIC, OTLP_PARTITIONS, TELEMETRY_RETENTION_MS),
        (OTLP_TRACES_TOPIC, OTLP_PARTITIONS, TELEMETRY_RETENTION_MS),
    ]
    existing = set(admin.list_topics(timeout=10).topics)
    missing = [
        NewTopic(
            name,
            num_partitions=partitions,
            replication_factor=1,
            config={"retention.ms": retention},
        )
        for name, partitions, retention in specs
        if name not in existing
    ]
    if not missing:
        return
    futures = admin.create_topics(missing)
    for name, future in futures.items():
        try:
            future.result()
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise
        log.info("topic %s is ready", name)


def producer(client_id: str) -> Producer:
    return Producer({**CLIENT, "client.id": client_id, "linger.ms": 20, "compression.type": "lz4"})


def consumer_config(group: str, client_id: str) -> dict:
    return {
        **CLIENT,
        "client.id": client_id,
        "group.id": group,
        "auto.offset.reset": "latest",
        "enable.auto.commit": False,
        "session.timeout.ms": 10000,
    }
