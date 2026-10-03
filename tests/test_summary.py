import unittest

from aid.summary import build_prompt


class SummaryPromptTests(unittest.TestCase):
    def test_previous_incident_is_part_of_the_packet(self):
        prompt = build_prompt(
            {
                "service": "billing-agent",
                "source": "agent",
                "signal": "tool.retry.charge_card",
                "value": 6,
                "window_start": "2026-10-03T19:00:00+00:00",
                "window_end": "2026-10-03T19:00:30+00:00",
                "samples": [
                    {
                        "kind": "log",
                        "observed_at": "2026-10-03T19:00:30+00:00",
                        "payload": {"body": "charge_card timed out", "value": None, "attributes": {}},
                    }
                ],
            },
            [
                {
                    "title": "billing-agent retried charge_card 5 times",
                    "summary": "The charge service timed out.",
                    "status": "resolved",
                    "value": 5,
                    "created_at": "2026-10-03T18:00:00+00:00",
                }
            ],
        )
        self.assertIn("The charge service timed out.", prompt)
        self.assertIn("tool.retry.charge_card", prompt)
        self.assertIn("previous_incidents", prompt)


if __name__ == "__main__":
    unittest.main()
