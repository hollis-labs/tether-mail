#!/usr/bin/env python3
"""tether-pulse hook: record what this agent is doing in a small local JSON file.

Usage: pulse-hook.py <tool> [event]      tool = claude | codex | agy
Event comes from the payload (hook_event_name) or, for Agy, the second argument.

Local disk only: no network, no prompt bodies stored.  Always exits 0.  Prints nothing,
except where Agy needs a JSON object on stdout (PreInvocation/Stop); Agy PreToolUse/PostToolUse
must print nothing (any output without a `decision` there denies the tool).
"""
import json, os, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import pulse  # noqa: E402

AGENT_NAMES = {"claude": ("claude",), "codex": ("codex",), "agy": ("agy",)}
WORKING = "working"
IDLE = "idle"
WAITING = "waiting"


def session_id(tool, p):
    if tool == "agy":
        return p.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID", "")
    return p.get("session_id") or p.get("thread_id") or ""


def transition(tool, event, p, doc):
    """Return (state, waiting_for) for this event, or (None, None) to leave the state alone."""
    if tool == "agy":
        return {"PreInvocation": (WORKING, ""), "PreToolUse": (WORKING, ""), "PostToolUse": (WORKING, ""),
                "PostInvocation": (WORKING, ""), "Stop": (IDLE, "")}.get(event, (None, None))
    # claude, and codex (codex event names beyond SessionStart are unverified; unknown ones are ignored)
    if event == "SessionStart":
        return IDLE, ""
    if event in ("UserPromptSubmit", "PreToolUse", "PostToolUse"):
        return WORKING, ""
    if event == "PermissionRequest":
        return WAITING, "permission prompt"
    if event == "Notification":
        kind = p.get("notification_type") or ""
        if kind == "permission_prompt":
            return WAITING, "permission prompt"
        if kind == "idle_prompt":
            return IDLE, ""
        if kind == "elicitation_dialog":
            return WAITING, "user input"
        return None, None
    if event == "Stop":
        return IDLE, ""
    return None, None


def run():
    tool = sys.argv[1] if len(sys.argv) > 1 else ""
    if tool not in AGENT_NAMES:
        return
    try:
        p = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        p = {}
    event = p.get("hook_event_name") or (sys.argv[2] if len(sys.argv) > 2 else "")
    sid = session_id(tool, p)
    if not sid or not event:
        return
    path = pulse.file_for(tool, sid, create=True)
    if event == "SessionEnd":
        try:
            os.unlink(path)
        except OSError:
            pass
        return
    doc = pulse.read(path)
    now = pulse.now_ms()
    if not doc:
        pid = pulse.ancestor(AGENT_NAMES[tool])
        doc = {"v": 1, "machine": pulse.machine(), "tool": tool, "session_id": sid, "pid": pid,
               "proc_start": pulse.proc_start(pid) if pid else "", "started_at": now, "subagents": 0}
    cwd = p.get("cwd") or ""
    if cwd:
        doc["cwd"] = cwd
    tm = pulse.tmux_info()
    if tm:
        doc["tmux"] = tm
    urn = os.environ.get("TETHER_AGENT_URN", "").strip()
    if urn:
        doc["urn"] = urn

    state, waiting = transition(tool, event, p, doc)
    if state and state != doc.get("state"):
        doc["state"], doc["state_since"] = state, now
    if state:
        doc["waiting_for"] = waiting
    doc["last_event"], doc["updated_at"] = event, now

    # last action: the tool being run (Claude/Codex tool_name; Agy toolCall.name)
    name, tin = p.get("tool_name"), p.get("tool_input")
    if tool == "agy" and isinstance(p.get("toolCall"), dict):
        name, tin = p["toolCall"].get("name"), p["toolCall"].get("args")
    if event in ("PreToolUse", "PostToolUse") and name:
        doc["last_action"] = {"tool": pulse.clean(name, 40), "target": pulse.action_target(name, tin),
                              "at": now, "done": event == "PostToolUse"}

    if event == "SubagentStart":
        doc["subagents"] = int(doc.get("subagents", 0)) + 1
    elif event == "SubagentStop":
        doc["subagents"] = max(0, int(doc.get("subagents", 0)) - 1)

    # task: declared (env) beats inferred (a CW id mentioned in the prompt or tool input)
    declared = os.environ.get("AGENT_TASK", "").strip()
    if declared:
        doc["task"] = {"id": declared, "confidence": "exact", "source": "env"}
    else:
        seen = pulse.find_task(p.get("prompt"), json.dumps(tin) if tin else "")
        if seen and doc.get("task", {}).get("confidence") != "exact":
            doc["task"] = {"id": seen, "confidence": "inferred", "source": "mention"}

    pulse.write_atomic(path, doc)


def main():
    try:
        run()
    except Exception as e:  # never break the agent loop
        print("tether-pulse hook error: %s" % e, file=sys.stderr)
    # Agy PreInvocation/Stop expect a JSON object; PreToolUse/PostToolUse must stay silent.
    if len(sys.argv) > 2 and sys.argv[1] == "agy" and sys.argv[2] in ("PreInvocation", "Stop", "PostInvocation"):
        print("{}")


main()
