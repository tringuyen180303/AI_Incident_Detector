import unittest

from aid.otlp import otlp_to_events


class OtlpTests(unittest.TestCase):
    def test_log_metric_and_failing_tool_span(self):
        events = otlp_to_events(
            {
                "resourceLogs": [
                    {
                        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                        "scopeLogs": [
                            {
                                "logRecords": [
                                    {
                                        "timeUnixNano": "1760000000000000000",
                                        "severityText": "ERROR",
                                        "body": {"stringValue": "POST /charge returned 503"},
                                    }
                                ]
                            }
                        ],
                    }
                ],
                "resourceMetrics": [
                    {
                        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "web-node"}}]},
                        "scopeMetrics": [
                            {
                                "metrics": [
                                    {
                                        "name": "system.cpu.utilization",
                                        "gauge": {
                                            "dataPoints": [
                                                {
                                                    "asDouble": 0.25,
                                                    "timeUnixNano": "1760000000000000000",
                                                    "attributes": [{"key": "state", "value": {"stringValue": "idle"}}],
                                                }
                                            ]
                                        },
                                    }
                                ]
                            }
                        ],
                    }
                ],
                "resourceSpans": [
                    {
                        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "billing-agent"}}]},
                        "scopeSpans": [
                            {
                                "spans": [
                                    {
                                        "name": "charge_card",
                                        "traceId": "abc",
                                        "spanId": "def",
                                        "endTimeUnixNano": "1760000000000000000",
                                        "status": {"code": 2, "message": "timeout"},
                                        "attributes": [
                                            {"key": "gen_ai.tool.name", "value": {"stringValue": "charge_card"}}
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        )
        by_kind = {item["kind"]: item for item in events}
        self.assertEqual(by_kind["log"]["body"], "POST /charge returned 503")
        self.assertEqual(by_kind["log"]["service"], "checkout")
        self.assertEqual(by_kind["metric"]["signal"], "cpu.utilization")
        self.assertAlmostEqual(by_kind["metric"]["value"], 0.75)
        self.assertEqual(by_kind["tool_call"]["attributes"]["tool"], "charge_card")
        self.assertTrue(by_kind["tool_call"]["attributes"]["error"])

    def test_internal_event_passes_through(self):
        original = {"kind": "log", "service": "checkout", "body": "already normalized"}
        self.assertEqual(otlp_to_events(original), [original])


if __name__ == "__main__":
    unittest.main()
