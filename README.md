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

## Hub-hosted sessions (one injector per session)
A session the Tether hub manages gets `TETHER_HOSTED_SESSION=<session id>` in its process
environment (daemon launches and worker-hosted launches both) and is woken by the hub's own
mailbox wake turn. Every piece here therefore does nothing when that variable is set: the
watchers exit 0 at once without polling, the Claude mod starts no watcher, and the Codex
and Agy hooks start no relay and inject nothing. Without it a hosted session got each
message twice (hub wake plus plugin), and N times when N sessions share a URN
(CW-20261021-0029). `TETHER_MAIL_ALLOW_HOSTED=1` overrides, for deliberate use only.
The plugin stays the delivery path for plain local sessions (no marker).

Known risk, stated plainly: in a hosted session the hub wake is the only push. If the hub
cannot wake it (no live session resolved for the address, the session is busy for a long
time, the hub is down), the message waits in the inbox until the agent pulls it; there is no
second injector to cover the gap. The wake retries on its own, and the agent's inbox-check
procedure is the backstop.

## Not injecting mail that is already read (non-hosted sessions)
Before injecting, the watcher (and the Codex relay when it queues a batch, and the Agy hook
when it drains its inbox file) asks the mailbox which of the batch is still unread, with one
`messages list --unread-only` call, and drops what is not: a streamed message can be read
between the hub pushing it and this process printing it, and mail waiting in a batch or an
inbox file is stale by the time it is delivered (CW-20261021-0029). The check fails open: a
CLI error, an empty or unreadable answer (anything that is not a list, or `{"messages": list-or-null}`
of rows with string ids), or a full page of 100 that does not show the id (it may be past the
page) still delivers; only a well-formed answer that does not list the id drops it. Limit: the message object carries no read state, so the
unread list is the evidence; the Claude mod's `$.prompt.submit` queues text behind a running
turn and has no hook to cancel it later, so only the moment of injection is checked.

Deployed copies: this repo is distributed by copying it into each agent's
`plugins/tether-mail` directory, so a merged change reaches an agent only when its copy is
updated.

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
