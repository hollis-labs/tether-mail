# tether-pulse (temp, v0)

Hooks write one small JSON file per live agent to local disk; `bin/pulse-collect` merges them
into one view. Temporary until a proper activity stream exists (Observability workstream,
Torque epic EP-20261014-0001). No network, no prompt bodies, secrets masked.

- `hooks/pulse-hook.py <claude|codex|agy> [event]` - the hook. Always exits 0.
- `lib/pulse.py` - paths, atomic write, redaction, process helpers.
- `bin/pulse-collect [--json]` - table or JSON rows. Falls back to `~/.claude/sessions/<pid>.json`
  for Claude sessions that have no pulse file yet (state derived, no last action).
- `claude/settings-hooks.snippet.json` - merge into `~/.claude/settings.json` (replace /ABS/PATH).
- `agy/hooks.snippet.json` - named hook for Agy (replace /ABS/PATH). Verified on agy 1.3.3 (`agy --dangerously-skip-permissions -p=...` in a planted `.agents/plugins/<name>/`): PreInvocation, PreToolUse/PostToolUse (matcher `.*`; the flat no-matcher form did NOT fire for tools), Stop. Hook inherits agy's env. A headless run whose tool is auto-denied never reaches Stop (row stays `working` until the pid dies).
- `codex/hooks.snippet.toml` - for `~/.codex/config.toml` (replace /ABS/PATH). Verified on codex-cli 0.162.1 end to end (`codex exec -c hooks.X=...`): SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop; payloads match Claude's (`tool_name`, `tool_input`, `session_id`). PermissionRequest not exercised; SessionEnd not exercised (dead pids are dropped by the collector anyway).

State lives in `$TETHER_PULSE_DIR` (default `~/.local/state/tether-pulse/<machine>/`). Override the
machine label with `TETHER_PULSE_MACHINE`. Declare an exact task with `AGENT_TASK=CW-...`;
otherwise the last CW id mentioned in a prompt or tool input is recorded as `inferred`.

## Row fields (pulse-collect --json)
machine, source (pulse|claude-session-file), tool, pid, session_id, name, cwd, project, tmux{session,pane},
state (working|idle|waiting|unknown), waiting_for, since, last_activity, last_action{tool,target,at,done},
subagents, task{id,confidence,source}, urn, confidence{state,last_action,task}, verified, stale, fetched_at.

## Tether-managed sessions
`pulse-collect --tether FILE` merges `{sessions:[...]}` as returned by `tether_session_list` (optionally with `live_state` from
`tether_session_health` per session), joined by pid; the row gets `source:"tether"` and a `tether{session_id,launch_id,project_id}` object.
Needed because managed workers run as another user (no readable `~/.claude/sessions`, no hooks). The collector does not call Tether itself yet;
the feed is meant to come from the hub/Outpost. Tested with a hand-written file built from live API output. No last action or task for these rows.

## Pulling another machine (v0 transport)
`bin/pulse-pull <machine> <ssh-target> [remote-root] [--loop SECONDS]` mirrors the remote's pulse dir into `<root>/<machine>/`
(rsync over ssh, BatchMode, read-only on the remote, a failed fetch keeps the old mirror and does not move `.fetched`).
Rows from it carry `verified:null` and `fetched_at`. Tested against a local path only; the real ssh route to the macbook and
macOS (BSD ps/rsync/python3) are untested.

## Not done yet
Live Tether feed (collector reads a file today); real macbook pull (waiting for Outpost); hub rollup; Codex PermissionRequest/SessionEnd.
