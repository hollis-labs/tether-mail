"""CW-20261021-0029: a hub-hosted session (TETHER_HOSTED_SESSION set) is woken by the
hub, so no tether-mail piece may inject there; everything else is unchanged."""
import json, os, stat, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHERS = [os.path.join(ROOT, d, "bin", "tether-mail-watch") for d in ("claude", "codex", "agy")]
CODEX_HOOK = os.path.join(ROOT, "codex", "hooks", "session-start.py")
AGY_HOOK = os.path.join(ROOT, "agy", "hooks", "mail-hook.py")
URN = "msg://agent/agent-mux/test"


class Env:
    """A fake tether-remote that records every call and lists one unread message."""

    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.calls = os.path.join(self.dir.name, "calls")
        self.cli = os.path.join(self.dir.name, "fake-cli")
        body = '#!/bin/sh\necho "$@" >> "%s"\n' % self.calls + \
               'echo \'[{"id":"m1","from":"msg://agent/a","subject":"hi","body":"hello"}]\'\n'
        with open(self.cli, "w") as f:
            f.write(body)
        os.chmod(self.cli, os.stat(self.cli).st_mode | stat.S_IEXEC)

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("TETHER_", "ANTIGRAVITY_"))}
        e.update(TETHER_MAIL_CLI=self.cli, TETHER_AGENT_URN=URN, XDG_STATE_HOME=self.dir.name)
        e.update(extra)
        return e

    def called(self):
        return os.path.exists(self.calls) and open(self.calls).read().strip() != ""


class WatcherTest(unittest.TestCase):
    def run_watch(self, path, **extra):
        env = Env()
        self.addCleanup(env.dir.cleanup)
        r = subprocess.run([sys.executable, path, "--once", "--format", "json"], env=env.env(**extra),
                           capture_output=True, text=True, timeout=20)
        return r, env

    def test_hosted_session_starts_nothing_and_never_calls_the_hub(self):
        for path in WATCHERS:
            with self.subTest(path=path):
                r, env = self.run_watch(path, TETHER_HOSTED_SESSION="sess-1")
                self.assertEqual(r.returncode, 0)
                self.assertEqual(r.stdout, "")
                self.assertIn("hub-hosted", r.stderr)
                self.assertFalse(env.called(), "a hosted session must not even poll the mailbox")

    def test_local_session_delivers_as_before(self):
        for path in WATCHERS:
            with self.subTest(path=path):
                r, env = self.run_watch(path)
                self.assertEqual(r.returncode, 0)
                self.assertEqual(json.loads(r.stdout)["id"], "m1")

    def test_blank_marker_is_not_hosted(self):
        r, _ = self.run_watch(WATCHERS[0], TETHER_HOSTED_SESSION="  ")
        self.assertEqual(json.loads(r.stdout)["id"], "m1")

    def test_explicit_override_runs_in_a_hosted_session(self):
        r, _ = self.run_watch(WATCHERS[0], TETHER_HOSTED_SESSION="sess-1", TETHER_MAIL_ALLOW_HOSTED="1")
        self.assertEqual(json.loads(r.stdout)["id"], "m1")

    def test_the_three_watcher_copies_are_identical(self):
        bodies = set()
        for p in WATCHERS:
            with open(p, "rb") as f:
                bodies.add(f.read())
        self.assertEqual(len(bodies), 1)


class HookTest(unittest.TestCase):
    def test_codex_hook_starts_no_relay_when_hosted(self):
        env = Env()
        self.addCleanup(env.dir.cleanup)
        payload = json.dumps({"session_id": "thread-1"})
        r = subprocess.run([sys.executable, CODEX_HOOK], input=payload, env=env.env(TETHER_HOSTED_SESSION="sess-1"),
                           capture_output=True, text=True, timeout=20)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(env.dir.name, "tether-mail")), "no relay state may be created")

    def test_codex_hook_still_starts_a_relay_locally(self):
        env = Env()
        self.addCleanup(env.dir.cleanup)
        r = subprocess.run([sys.executable, CODEX_HOOK], input=json.dumps({"session_id": "thread-1"}), env=env.env(),
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0)
        self.assertIn("relay is on", r.stdout)
        # the relay exits on its own once its parent is gone; make sure nothing lingers
        subprocess.run(["pkill", "-f", "tether-mail-codex-relay --thread thread-1"], capture_output=True)

    def test_agy_hook_is_inert_when_hosted(self):
        env = Env()
        self.addCleanup(env.dir.cleanup)
        for mode in ("pre", "stop"):
            with self.subTest(mode=mode):
                r = subprocess.run([sys.executable, AGY_HOOK, mode], input=json.dumps({"conversationId": "c1"}),
                                   env=env.env(TETHER_HOSTED_SESSION="sess-1"), capture_output=True, text=True, timeout=20)
                self.assertEqual((r.returncode, json.loads(r.stdout)), (0, {}))
        self.assertFalse(env.called())


if __name__ == "__main__":
    unittest.main()
