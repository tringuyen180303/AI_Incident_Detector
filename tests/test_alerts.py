import unittest

from aid.alerts import alert_message, opened_key, status_key


class AlertTests(unittest.TestCase):
    def test_opened_and_status_keys_stay_stable(self):
        self.assertEqual(opened_key("abc"), "opened:abc")
        self.assertEqual(status_key("abc", "acknowledged"), "status:abc:acknowledged")

    def test_message_carries_the_key_the_workers_dedupe_on(self):
        message = alert_message(
            key=opened_key("abc"),
            kind="opened",
            incident_id="abc",
            service="billing-agent",
            signal="tool.retry.charge_card",
            title="billing-agent retried charge_card 5 times",
            summary="The tool timed out.",
            severity="medium",
            status="open",
        )
        self.assertEqual(message["notification_key"], "opened:abc")
        self.assertEqual(message["kind"], "opened")


if __name__ == "__main__":
    unittest.main()
