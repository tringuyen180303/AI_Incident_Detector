"""Publish a steady stream, then a short spike, onto the telemetry topic.

The spike is what makes the first incidents appear. Replace this process
with the collector once a real app or agent is exporting OTLP.
"""

import json
import logging
import time
from datetime import datetime, timezone

from aid.events import event
from aid.kafka import producer, wait_for_broker
from aid.config import TELEMETRY_TOPIC

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aid.produce")


def main() -> None:
    wait_for_broker()
    writer = producer("aid-produce")
    started = time.monotonic()
    log.info("publishing telemetry to %s", TELEMETRY_TOPIC)
    while True:
        cycle = (time.monotonic() - started) % 90
        spike = 12 <= cycle < 28
        _emit(writer, spike)
        writer.poll(0)
        time.sleep(1)


def _emit(writer, spike: bool) -> None:
    now = datetime.now(timezone.utc)
    _send(
        writer,
        event(
            kind="metric",
            source="application",
            service="checkout",
            signal="http.error_ratio",
            ts=now,
            value=0.4 if spike else 0.0,
            attributes={"requests": 10, "errors": 4 if spike else 0},
        ),
    )
    _send(
        writer,
        event(
            kind="metric",
            source="infrastructure",
            service="web-node",
            signal="cpu.utilization",
            ts=now,
            value=0.93 if spike else 0.22,
            attributes={"host": "web-node"},
        ),
    )
    _send(
        writer,
        event(
            kind="tool_call",
            source="agent",
            service="billing-agent",
            signal="tool.retry" if spike else "tool.call",
            ts=now,
            body="charge_card timed out" if spike else "charge_card ok",
            attributes={"tool": "charge_card", "error": spike},
        ),
    )
    if spike:
        for service, source, body in (
            ("checkout", "application", "POST /charge returned 503"),
            ("billing-agent", "agent", "tool charge_card failed, retrying"),
            ("web-node", "infrastructure", "cpu saturation on web-node"),
        ):
            _send(
                writer,
                event(
                    kind="log",
                    source=source,
                    service=service,
                    signal="log",
                    ts=now,
                    body=body,
                    attributes={"severity": "ERROR"},
                ),
            )
    elif int(now.timestamp()) % 5 == 0:
        _send(
            writer,
            event(
                kind="log",
                source="application",
                service="checkout",
                signal="log",
                ts=now,
                body="checkout healthy",
                attributes={"severity": "INFO"},
            ),
        )


def _send(writer, record: dict) -> None:
    log.info("%s", json.dumps(record))
    writer.produce(
        TELEMETRY_TOPIC,
        key=record["service"].encode(),
        value=json.dumps(record).encode(),
        on_delivery=_delivery,
    )


def _delivery(err, _msg) -> None:
    if err is not None:
        log.error("publish failed: %s", err)


if __name__ == "__main__":
    main()
