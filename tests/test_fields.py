"""CW-20261114-0018: the watcher passes the routing fields the Claude mod triages on
(attention, awaiting, to, kind, handles) through, only when the message carries them."""
import importlib.machinery, importlib.util, os, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "claude", "bin", "tether-mail-watch")
ENVELOPE = "application/vnd.tether.envelope.v1+json"  # Tether: internal/messaging/envelope


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

    def test_urgency_comes_from_hub_metadata(self):
        m = self.to_mail({"id": "m1", "payload": {"urgency": "very-low"}, "metadata": {"urgency": "high"}})
        self.assertEqual(m["urgency"], "high")

    def test_envelope_kind_is_kept_apart_from_the_tool_kind(self):
        m = self.to_mail({"id": "m1", "kind": "request", "content_type": ENVELOPE,
                          "payload": {"kind": "question", "body": "b"}})
        self.assertEqual(m["kind"], "request")
        self.assertEqual(m["envelope_kind"], "question")
        self.assertNotIn("envelope_kind", self.to_mail({"id": "m2", "kind": "request", "payload": {}}))

    def test_untyped_mail_never_gets_envelope_kind(self):
        # An untyped request whose payload happens to say kind:update stays a request
        # (the mod then classifies it action), whatever else its payload claims.
        for ct in (None, "", "application/json", "text/plain"):
            msg = {"id": "m1", "kind": "request", "payload": {"kind": "update", "schema": "tether.envelope/v1"}}
            if ct is not None:
                msg["content_type"] = ct
            m = self.to_mail(msg)
            self.assertEqual(m["kind"], "request")
            self.assertNotIn("envelope_kind", m)

    def test_every_watcher_copy_is_byte_identical(self):
        with open(PATH, "rb") as f:
            want = f.read()
        for host in ("codex", "agy"):
            with open(os.path.join(ROOT, host, "bin", "tether-mail-watch"), "rb") as f:
                self.assertEqual(f.read(), want, host)

    def test_every_watcher_copy_passes_the_same_fields(self):
        msg = {"id": "m1", "kind": "notice", "content_type": ENVELOPE, "payload": {"kind": "update"}, "metadata": {"urgency": "low"}}
        want = self.to_mail(msg)
        for host in ("codex", "agy"):
            path = os.path.join(ROOT, host, "bin", "tether-mail-watch")
            loader = importlib.machinery.SourceFileLoader("tmw_" + host, path)
            spec = importlib.util.spec_from_loader("tmw_" + host, loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)
            self.assertEqual(mod.to_mail(msg), want, host)

    def test_non_string_values_are_dropped(self):
        m = self.to_mail({"id": "m1", "attention": {"x": 1}, "payload": {}})
        self.assertNotIn("attention", m)


if __name__ == "__main__":
    unittest.main()
