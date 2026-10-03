import unittest
from collections import deque
from datetime import datetime, timedelta, timezone

from aid.events import event
from aid.windows import Rules, ServiceWindow, evidence_samples


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def at(seconds, **kwargs):
    return event(ts=START + timedelta(seconds=seconds), **kwargs)


class WindowTests(unittest.TestCase):
    def test_retry_threshold_fires_once(self):
        window = ServiceWindow("billing-agent", Rules(window_seconds=30, cooldown_seconds=30, retry_threshold=5))
        fired = []
        for second in range(8):
            fired.extend(
                window.observe(
                    at(
                        second,
                        kind="tool_call",
                        source="agent",
                        service="billing-agent",
                        signal="tool.retry",
                        body="charge_card timed out",
                        attributes={"tool": "charge_card", "error": True},
                    )
                )
            )
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["signal"], "tool.retry.charge_card")
        self.assertEqual(fired[0]["value"], 5)

    def test_error_ratio_waits_for_enough_requests(self):
        window = ServiceWindow(
            "checkout",
            Rules(window_seconds=30, min_requests=10, error_ratio_threshold=0.05),
        )
        self.assertEqual(
            window.observe(
                at(
                    0,
                    kind="metric",
                    source="application",
                    service="checkout",
                    signal="http.error_ratio",
                    value=1,
                    attributes={"requests": 4, "errors": 4},
                )
            ),
            [],
        )
        fired = window.observe(
            at(
                1,
                kind="metric",
                source="application",
                service="checkout",
                signal="http.error_ratio",
                value=0.2,
                attributes={"requests": 10, "errors": 2},
            )
        )
        self.assertEqual(fired[0]["signal"], "http.error_ratio")
        self.assertEqual(fired[0]["value"], round(6 / 14, 4))

    def test_cpu_needs_three_high_samples_in_a_row(self):
        window = ServiceWindow(
            "web-node",
            Rules(window_seconds=30, cpu_min_samples=3, cpu_threshold=0.8),
        )
        for second, value in enumerate((0.95, 0.95)):
            self.assertEqual(window.observe(self._cpu(second, value)), [])
        fired = window.observe(self._cpu(2, 0.95))
        self.assertEqual(fired[0]["source"], "infrastructure")
        self.assertGreaterEqual(fired[0]["value"], 0.9)

        dipped = ServiceWindow(
            "web-node",
            Rules(window_seconds=30, cpu_min_samples=3, cpu_threshold=0.8, cooldown_seconds=0),
        )
        for second, value in enumerate((0.95, 0.1, 0.95, 0.95)):
            self.assertEqual(dipped.observe(self._cpu(second, value)), [])

    def test_evidence_keeps_five_error_logs(self):
        logs = deque(maxlen=20)
        for index in range(12):
            logs.append(
                at(
                    index,
                    kind="log",
                    source="application",
                    service="checkout",
                    signal="log",
                    body=f"line {index}",
                    attributes={"severity": "ERROR" if index % 2 == 0 else "INFO"},
                )
            )
        samples = evidence_samples(logs, self._cpu(0, 0.9))
        log_samples = [sample for sample in samples if sample["kind"] == "log"]
        self.assertEqual(len(log_samples), 5)
        self.assertTrue(all(sample["payload"]["attributes"]["severity"] == "ERROR" for sample in log_samples))
        self.assertEqual(samples[-1]["kind"], "metric")

    def _cpu(self, second, value):
        return at(
            second,
            kind="metric",
            source="infrastructure",
            service="web-node",
            signal="cpu.utilization",
            value=value,
        )


if __name__ == "__main__":
    unittest.main()
