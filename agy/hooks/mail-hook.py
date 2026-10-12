#!/usr/bin/env python3
"""Agy hook for tether-mail.  Usage: mail-hook.py pre | stop | tool

  pre   (PreInvocation) start the per-conversation relay if needed, drain the inbox,
        inject new mail as a persistent system message.
  stop  (Stop) if mail arrived before the agent finished, return decision "continue"
        with the framed mail as the reason (agy injects it as a system message).
  tool  (PreToolUse, matcher run_command) until the session is registered, prefix the
        agent's own shell command with tether-mail-agy-register, which runs in agy's
        tool environment (the only place ANTIGRAVITY_LS_ADDRESS/_CSRF_TOKEN exist).

Quiet no-op unless $TETHER_AGENT_URN is set. Always exits 0 with JSON on stdout.
"""
import json, os, subprocess, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import tmail  # noqa: E402

URN = os.environ.get("TETHER_AGENT_URN", "").strip()
CLI = os.environ.get("TETHER_MAIL_CLI", "tether-remote")
DECISION = "ask"
KIND = os.environ.get("TETHER_MAIL_AGY_INJECT", "system")  # system | ephemeral | user


def ensure_relay(cid):
    try:
        if tmail.alive(int(open(tmail.path(cid, ".relay.pid")).read().strip())):
            return
    except (OSError, ValueError):
        pass
    pid = tmail.agy_ancestor()
    if not pid:
        return
    argv = [sys.executable, os.path.join(tmail.BIN, "tether-mail-agy-relay"),
            "--conversation", cid, "--urn", URN, "--agy-pid", str(pid), "--cli", CLI]
    log = open(tmail.path(cid, ".relay.log"), "ab")
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                     start_new_session=True, close_fds=True)


def inject(text):
    if KIND == "ephemeral":
        return {"injectSteps": [{"ephemeralMessage": text}]}
    if KIND == "user":
        return {"injectSteps": [{"userMessage": text}]}
    return {"injectSteps": [{"systemMessage": {"systemMessage": text}}]}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    cid = payload.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID", "")
    out = {}
    if not URN or not cid:
        if mode != "tool":
            print("{}")
        return
    mails = []
    try:
        if mode == "pre":
            ensure_relay(cid)
            mails = tmail.drain_inbox(cid)
            if mails:
                out = inject(tmail.frame(mails, URN, CLI))
        elif mode == "stop":
            mails = tmail.drain_inbox(cid)
            if mails:
                out = {"decision": "continue", "reason": tmail.frame(mails, URN, CLI)}
        elif mode == "tool":
            # Opt-in only. Prepend (never edit) a silent registration step to the first
            # run_command of a conversation that has no .session file yet.
            args = (payload.get("toolCall") or {}).get("args") or {}
            cmd = args.get("CommandLine")
            name = (payload.get("toolCall") or {}).get("name")
            marker = tmail.path(cid, ".reg-attempted")
            if os.environ.get("TETHER_MAIL_AGY_REGISTER") == "1" and name == "run_command" \
                    and isinstance(cmd, str) and cmd.strip() \
                    and not os.path.exists(tmail.path(cid, ".session")) \
                    and not os.path.exists(marker):
                open(marker, "w").close()
                out = {"decision": DECISION, "overwrite": {"CommandLine": tmail.with_registration(cmd)}}
    except Exception as e:  # never break the agent loop; put mail back
        if mails:
            tmail.append_inbox(cid, mails)
        print("tether-mail hook error: %s" % e, file=sys.stderr)
        out = {}
    if mode == "tool" and not out:
        return  # PreToolUse: empty stdout = no opinion; "{}" would be read as a denial
    print(json.dumps(out, ensure_ascii=False))


main()
