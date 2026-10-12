# tether-mail

Get Tether mailbox messages in front of coding agents without them polling.
Envelope format ("You've got mail" box + exact read/mark commands) is shared.

| Host | Piece | Status |
| --- | --- | --- |
| Claude Code | `claude/` — mod (spawns `bin/tether-mail-watch`, `$.prompt.submit`) | working as a hot-reloaded dev mod; not yet tested as an installed plugin |
| Codex | `codex/` — SessionStart hook starts a detached relay; relay uses `codex queue --thread <id>` | idle-session delivery verified live (throwaway tmux Codex, `-c` hook override); relay dies with Codex |
| Agy | `agy/` — plugin-shaped: PreInvocation/Stop hooks drain a per-conversation inbox; relay uses `agy agentapi send-message` once the session self-registers (PreToolUse rewrite) | active, idle and mid-turn verified in tmux; plugin not installed |

## Pieces
- `*/bin/tether-mail-watch` (claude, codex, agy: byte-identical copies) — one JSON line per new unread message. Default: `<cli> mailbox watch` (SSE, Tether PR hollis-labs/tether#242), polling catch-up, falls back to `messages list --unread-only` when the hub lacks the route (CLI exit 4 / quick failure). Keep the three copies in sync until there is a single source.
- `codex/bin/tether-mail-codex-relay` — per-thread, single-instance (pidfile), batches 1.5 s, exits when the codex pid is gone.
- `codex/hooks/session-start.py` — reads `session_id` (== thread id), needs `$TETHER_AGENT_URN`, prints one context line.

## Not verified
- Installing as a real Codex plugin (`codex plugin ...`, `.codex-plugin/plugin.json` schema, `$PLUGIN_ROOT` expansion in hook commands, `/hooks` trust review). Tested only via `-c hooks.SessionStart=[...]` + `--dangerously-bypass-hook-trust`.
- Mid-turn delivery through the relay (the `codex queue` semantics were verified separately: queued until the running turn ends).
- Sessions started with a different `CODEX_HOME`.
- The Agy side.

## Security
Mail bodies become model input. The envelope tells the model they are data, not instructions. Any process running as the user can already `codex queue` into any session; the relay adds no new exposure.

## Requirements
Python 3, a Tether hub, and the `tether-remote` CLI (override with the `cli` option). Set `$TETHER_AGENT_URN` (or the Claude mod's `urn` option) to the mailbox to watch.

## Status
Experimental. Written against Tether's `mailbox watch` and the Claude Code mods API; interfaces for Codex and Agy hooks are partly undocumented and may change.
