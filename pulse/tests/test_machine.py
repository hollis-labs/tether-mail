"""machine() picks the name the Tether worker reads: env override, then worker label, then hostname."""
import json, os, socket, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import pulse  # noqa: E402


class MachineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saved = dict(os.environ)
        os.environ.pop("TETHER_PULSE_MACHINE", None)
        self._expand = os.path.expanduser
        os.path.expanduser = lambda p: p.replace("~", self.dir, 1) if p.startswith("~") else p
        self.host = socket.gethostname().split(".")[0]

    def tearDown(self):
        os.path.expanduser = self._expand
        os.environ.clear()
        os.environ.update(self.saved)

    def config(self, body):
        os.makedirs(os.path.join(self.dir, ".tether-worker"), exist_ok=True)
        with open(os.path.join(self.dir, ".tether-worker", "config.json"), "w") as f:
            f.write(body if isinstance(body, str) else json.dumps(body))

    def test_worker_label_beats_hostname(self):
        self.config({"label": "home-laptop"})
        self.assertEqual(pulse.machine(), "home-laptop")

    def test_env_beats_worker_label(self):
        self.config({"label": "home-laptop"})
        os.environ["TETHER_PULSE_MACHINE"] = "override"
        self.assertEqual(pulse.machine(), "override")

    def test_no_worker_falls_back_to_hostname(self):
        self.assertEqual(pulse.machine(), self.host)

    def test_unusable_label_falls_back_to_hostname(self):
        for bad in ({"label": "../x"}, {"label": "a/b"}, {"label": ""}, {"label": 7}, {"label": ".hidden"}, {}, "not json", "[1]"):
            self.config(bad)
            self.assertEqual(pulse.machine(), self.host, bad)


if __name__ == "__main__":
    unittest.main()
