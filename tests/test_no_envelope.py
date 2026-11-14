"""CW-20261114-0018 follow-up: the boxed "YOU'VE GOT MAIL" envelope is gone from every
code path. Each host gets one compact pointer line per message, never the body."""
import importlib.machinery, importlib.util, os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHERS = [os.path.join(ROOT, *p) for p in (
    ("claude", "bin", "tether-mail-watch"), ("codex", "bin", "tether-mail-watch"),
    ("agy", "bin", "tether-mail-watch"),
    ("agy", "planted", ".agents", "plugins", "tether-mail", "bin", "tether-mail-watch"),
)]
BOX = re.compile("[┌┐└┘│├┤]")


def load(path):
    loader = importlib.machinery.SourceFileLoader("watch_%d" % abs(hash(path)), path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class NoEnvelope(unittest.TestCase):
    def test_no_source_file_produces_the_box(self):
        hits = []
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "__pycache__")]
            for f in files:
                p = os.path.join(d, f)
                # Test files name the box only to assert it is absent.
                if p == os.path.abspath(__file__) or re.search(r"\.test\.tsx?$", f):
                    continue
                try:
                    text = open(p, encoding="utf-8").read()
                except (UnicodeDecodeError, OSError):
                    continue
                if "YOU'VE GOT MAIL" in text.upper().replace("’", "'") or BOX.search(text):
                    hits.append(os.path.relpath(p, ROOT))
        self.assertEqual(hits, [])

    def test_every_watcher_prints_one_compact_line_without_the_body(self):
        m = {"id": "m_1", "from": "msg://agent/agent-mux/tether", "subject": "deploy done",
             "body": "SECRET-BODY " * 40}
        for path in WATCHERS:
            out = load(path).envelope(m, "msg://agent/me", "tether-remote")
            self.assertEqual(out.count("\n"), 0, path)
            self.assertTrue(out.startswith("📬 deploy done · from @tether · m_1"), (path, out))
            self.assertIn("tether-remote messages get m_1 --as msg://agent/me", out)
            self.assertNotIn("SECRET-BODY", out)

    def test_watcher_copies_stay_identical(self):
        texts = {open(p).read() for p in WATCHERS[:3]}
        self.assertEqual(len(texts), 1)


if __name__ == "__main__":
    unittest.main()
