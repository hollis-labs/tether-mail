"""CW-20261114-0018: the watcher passes the routing fields the Claude mod triages on
(attention, awaiting, to, kind, handles) through, only when the message carries them."""
import importlib.machinery, importlib.util, os, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "claude", "bin", "tether-mail-watch")


def load():
    loader = importlib.machinery.SourceFileLoader("tether_mail_watch", PATH)
    spec = importlib.util.spec_from_loader("tether_mail_watch", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class ToMailTest(unittest.TestCase):
    def setUp(self):
        self.to_mail = load().to_mail

    def test_plain_message_keeps_the_old_shape(self):
        m = self.to_mail({"id": "m1", "from": "a", "payload": {"subject": "s", "body": "b"}})
        self.assertEqual(m, {"id": "m1", "from": "a", "subject": "s", "body": "b"})

    def test_routing_fields_pass_through_from_top_level_payload_or_metadata(self):
        m = self.to_mail({
            "id": "m1", "from": "a", "to": "msg://agent/x/b", "kind": "request",
            "payload": {"subject": "s", "body": "b", "attention": "human"},
            "metadata": {"awaiting": "@archie"},
        })
        self.assertEqual(m["to"], "msg://agent/x/b")
        self.assertEqual(m["kind"], "request")
        self.assertEqual(m["attention"], "human")
        self.assertEqual(m["awaiting"], "@archie")
        self.assertNotIn("from_handle", m)

    def test_hub_metadata_wins_over_the_sender_payload(self):
        m = self.to_mail({"id": "m1", "payload": {"attention": "human"}, "metadata": {"attention": "none"}})
        self.assertEqual(m["attention"], "none")

    def test_non_string_values_are_dropped(self):
        m = self.to_mail({"id": "m1", "attention": {"x": 1}, "payload": {}})
        self.assertNotIn("attention", m)


if __name__ == "__main__":
    unittest.main()
