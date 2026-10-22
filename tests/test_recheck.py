"""CW-20261021-0029: mail the mailbox shows as already read is not injected, and the
check fails open (an error or an unreadable answer still delivers)."""
import importlib.machinery, importlib.util, json, os, stat, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCH = os.path.join(ROOT, "claude", "bin", "tether-mail-watch")
URN = "msg://agent/agent-mux/test"


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FakeCLI:
    """tether-remote stand-in: `messages list` answers from a file, `mailbox watch` streams
    the messages in a second file; every call is recorded."""

    def __init__(self, unread=(), stream=(), list_rc=0, list_out=None):
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        self.calls = os.path.join(d, "calls")
        with open(os.path.join(d, "unread.json"), "w") as f:
            json.dump([{"id": i, "from": "f", "subject": "s", "body": "b"} for i in unread] if list_out is None else list_out, f)
        with open(os.path.join(d, "stream.jsonl"), "w") as f:
            for i in stream:
                f.write(json.dumps({"id": i, "seq": 1, "from": "f", "subject": "s", "body": "b"}) + "\n")
        self.path = os.path.join(d, "cli")
        with open(self.path, "w") as f:
            f.write('#!/bin/sh\necho "$1 $2" >> "%s"\n'
                    'if [ "$1" = messages ]; then cat "%s/unread.json"; exit %d; fi\n'
                    'if [ "$1" = mailbox ]; then cat "%s/stream.jsonl"; exit 0; fi\n' % (self.calls, d, list_rc, d))
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IEXEC)

    def count(self, what):
        if not os.path.exists(self.calls):
            return 0
        with open(self.calls) as f:
            return sum(1 for l in f if l.strip() == what)


class FilterTest(unittest.TestCase):
    def setUp(self):
        self.w = load(WATCH, "watch_under_test")

    def keep(self, cli, ids):
        self.addCleanup(cli.dir.cleanup)
        return [m["id"] for m in self.w.filter_unread(cli.path, URN, [{"id": i} for i in ids])]

    def test_read_mail_is_dropped_unread_kept(self):
        self.assertEqual(self.keep(FakeCLI(unread=["a"]), ["a", "b"]), ["a"])

    def test_one_list_call_for_a_whole_batch(self):
        cli = FakeCLI(unread=["a", "b"])
        self.keep(cli, ["a", "b", "c"])
        self.assertEqual(cli.count("messages list"), 1)

    def test_cli_failure_delivers(self):
        self.assertEqual(self.keep(FakeCLI(unread=[], list_rc=3), ["a"]), ["a"])

    def test_unreadable_answer_delivers(self):
        self.assertEqual(self.keep(FakeCLI(list_out="not json"), ["a"]), ["a"])

    def test_a_full_page_without_the_id_delivers(self):
        full = [{"id": "x%d" % i} for i in range(self.w.RECHECK_LIMIT)]
        self.assertEqual(self.keep(FakeCLI(list_out=full), ["late"]), ["late"])

    def test_empty_batch_makes_no_call(self):
        cli = FakeCLI()
        self.addCleanup(cli.dir.cleanup)
        self.assertEqual(self.w.filter_unread(cli.path, URN, []), [])
        self.assertEqual(cli.count("messages list"), 0)


class StreamTest(unittest.TestCase):
    def run_stream(self, cli):
        self.addCleanup(cli.dir.cleanup)
        env = {k: v for k, v in os.environ.items() if not k.startswith("TETHER_")}
        try:
            r = subprocess.run([sys.executable, WATCH, "--urn", URN, "--cli", cli.path, "--mode", "stream", "--format", "json"],
                               env=env, capture_output=True, text=True, timeout=4)
            out, err = r.stdout, r.stderr
        except subprocess.TimeoutExpired as e:  # the watcher loops forever; the output so far is what we want
            out, err = (e.stdout or b"").decode(), (e.stderr or b"").decode()
        return [json.loads(l)["id"] for l in out.splitlines() if l.strip()], err

    def test_a_streamed_message_read_in_the_meantime_is_not_injected(self):
        ids, err = self.run_stream(FakeCLI(unread=[], stream=["m1"]))
        self.assertEqual(ids, [])
        self.assertIn("no longer unread", err)

    def test_a_streamed_message_still_unread_is_injected_once(self):
        ids, _ = self.run_stream(FakeCLI(unread=["m1"], stream=["m1"]))
        self.assertEqual(ids, ["m1"])


class AgyTest(unittest.TestCase):
    def test_agy_inbox_drops_mail_read_while_it_waited(self):
        os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
        sys.path.insert(0, os.path.join(ROOT, "agy", "lib"))
        import tmail
        cli = FakeCLI(unread=["keep"])
        self.addCleanup(cli.dir.cleanup)
        got = tmail.unread_only([{"id": "keep"}, {"id": "gone"}], URN, cli.path)
        self.assertEqual([m["id"] for m in got], ["keep"])


if __name__ == "__main__":
    unittest.main()
