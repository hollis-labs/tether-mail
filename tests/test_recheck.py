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

    def __init__(self, unread=(), stream=(), list_rc=0, list_out=None, unread_by_call=None):
        self.dir = tempfile.TemporaryDirectory()
        d = self.dir.name
        # unread_by_call[k] answers the (k+1)-th `messages list` (the last one repeats): the mailbox
        # changing while mail sits in a relay's batch.
        for k, ids in enumerate(unread_by_call or []):
            with open(os.path.join(d, "unread.%d.json" % (k + 1)), "w") as f:
                json.dump([{"id": i, "from": "f", "subject": "s", "body": "b"} for i in ids], f)
        self.n_by_call = len(unread_by_call or [])
        self.calls = os.path.join(d, "calls")
        with open(os.path.join(d, "unread.json"), "w") as f:
            json.dump([{"id": i, "from": "f", "subject": "s", "body": "b"} for i in unread] if list_out is None else list_out, f)
        with open(os.path.join(d, "stream.jsonl"), "w") as f:
            for i in stream:
                f.write(json.dumps({"id": i, "seq": 1, "from": "f", "subject": "s", "body": "b"}) + "\n")
        self.path = os.path.join(d, "cli")
        with open(self.path, "w") as f:
            f.write('#!/bin/sh\necho "$1 $2" >> "%s"\n'
                    'if [ "$1" = messages ]; then\n'
                    '  n=$(grep -c "^messages list" "%s"); f="%s/unread.$n.json"\n'
                    '  if [ %d -gt 0 ]; then [ -f "$f" ] || f="%s/unread.%d.json"; else f="%s/unread.json"; fi\n'
                    '  cat "$f"; exit %d\nfi\n'
                    'if [ "$1" = mailbox ]; then cat "%s/stream.jsonl"; exit 0; fi\n'
                    % (self.calls, self.calls, d, self.n_by_call, d, self.n_by_call, d, list_rc, d))
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


class CodexRelayTest(unittest.TestCase):
    """The relay batches streamed mail and queues it into the codex thread; mail read while it
    sat in the batch must not be queued. A fake codex records its `queue` calls."""

    RELAY = os.path.join(ROOT, "codex", "bin", "tether-mail-codex-relay")

    def run_relay(self, cli):
        self.addCleanup(cli.dir.cleanup)
        d = cli.dir.name
        codex = os.path.join(d, "codex")
        with open(codex, "w") as f:
            f.write('#!/bin/sh\necho "$@" >> "%s/queued"\n' % d)
        os.chmod(codex, os.stat(codex).st_mode | stat.S_IEXEC)
        parent = subprocess.Popen(["sleep", "30"])  # stands in for the codex process the relay follows
        self.addCleanup(parent.kill)
        env = {k: v for k, v in os.environ.items() if not k.startswith("TETHER_")}
        relay = subprocess.Popen([sys.executable, self.RELAY, "--thread", "t1", "--urn", URN, "--parent-pid", str(parent.pid),
                                  "--state-dir", d, "--cli", cli.path, "--codex", codex, "--batch-seconds", "0.3"],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            relay.wait(timeout=4)  # the fake stream ends, so the relay exits on its own
        except subprocess.TimeoutExpired:
            pass
        finally:
            if relay.poll() is None:
                relay.terminate()
            relay.wait(timeout=5)
        queued = os.path.join(d, "queued")
        relay.stdout.close()
        relay.stderr.close()
        parent.kill()
        parent.wait()
        if not os.path.exists(queued):
            return ""
        with open(queued) as f:
            return f.read()

    # The watcher subprocess already drops mail that is read before it prints it, so these tests
    # change the mailbox between the watcher's poll (call 1) and the relay's own recheck (call 2):
    # only the relay's filter can catch what was read while the batch waited.
    def test_mail_read_while_batched_is_not_queued(self):
        self.assertEqual(self.run_relay(FakeCLI(unread_by_call=[["m1"], []])), "")

    def test_mail_still_unread_is_queued_once(self):
        out = self.run_relay(FakeCLI(unread_by_call=[["m1"], ["m1"]]))
        self.assertEqual(out.count("queue --thread t1"), 1)
        self.assertIn("m1", out)


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
