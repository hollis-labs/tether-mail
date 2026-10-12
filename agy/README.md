# tether-mail / agy

Plugin-shaped (`agy plugin validate agy/` passes; not installed). Needs `$TETHER_AGENT_URN` in agy's environment; otherwise every hook is a no-op.

- `hooks.json` - named hook `tether-mail`: PreInvocation (start relay, drain inbox, inject), Stop (decision `continue` if mail arrived), PreToolUse/run_command (one-time self-registration, see below).
- `hooks/mail-hook.py pre|stop|tool`, `lib/tmail.py` (paths, framing, atomic inbox drain via rename + flock).
- `bin/tether-mail-agy-relay` - one per conversation, started by the hook; exits when the agy pid is gone. Delivers via `agy agentapi send-message` if `<cid>.session` exists, else appends to `~/.local/state/tether-mail/agy/<cid>.jsonl` for the hooks.
- `bin/tether-mail-agy-register` - run inside an agy tool shell; writes `<cid>.session` (0600: LS address + CSRF token + agy pid). Never prints the token.
- `bin/tether-mail-watch` - copy of the shared watcher.

## Findings (agy 1.3.3)
- Injection kind: use `{"systemMessage":{"systemMessage":"..."}}` (default). It persists in history as a SYSTEM_MESSAGE step ("not actually sent by the user"). `ephemeralMessage` lasts one model call only (forgotten next call); `userMessage` persists but is attributed to the user and shown in the TUI. Plain-string `systemMessage` is silently dropped. Override with `TETHER_MAIL_AGY_INJECT=ephemeral|user`.
- `toolCall` in `injectSteps` does NOT work from command hooks (every shape fails with `unknown injected step type: <nil>`, in PreInvocation and PostInvocation).
- Registration instead: see "Opt-in registration" below.
- Hook cwd = dir of hooks.json. Hook's parent chain: sh -> agy (pid found via ps). Hooks hot-reload.
- Preset `ANTIGRAVITY_CSRF_TOKEN` / `ANTIGRAVITY_LS_ADDRESS` are ignored (agy generates a UUID token, picks the port). Port is discoverable via `lsof -a -p <agy pid> -iTCP -sTCP:LISTEN` (second listener); token is not.
- tmux fallback: `tmux load-buffer`, `paste-buffer -p`, then `send-keys Enter` separately. Works idle; mid-turn is queued. Pasted text is a USER turn. After launch the pane may sit in view-mode (`send-keys -X cancel` first); trust prompt ignored send-keys in a fresh dir.

## Planting as a workspace plugin (Tether boot dir) - verified, agy 1.3.3
`planted/` is the exact boot-dir shape; `planted/launch-profile-injection.yaml` is the `injection.native_files` snippet. Verified with a scratch boot dir shaped like Tether's (AGENTS.md, boot.md, `.agents/plugins/tether-mail/`), with NO `<boot>/.agents/hooks.json`:
- agy discovers `<cwd>/.agents/plugins/<name>/` and enables it; its `hooks.json` runs in both `agy -p` and interactive. The real hook started the relay with the right agy pid, which exited with agy.
- Manifest: root `plugin.json` (`{"name":"tether-mail"}`) is enough.
- Hook cwd = the plugin dir (so `python3 ./hooks/mail-hook.py` works). `$PLUGIN_ROOT` is NOT set in hooks, and no `PLUGIN_*` in tool shells. The plugin's `bin/` is NOT on PATH (neither in hooks nor in the agent's shell) for a workspace plugin; call scripts by path.
- Trust: `-p` shows no prompt; interactive in a never-seen dir shows "Do you trust the contents of this project?" once (it persists in `trustedWorkspaces` in settings.json, so a launcher using fresh dirs each time gets it each time interactively).

## Opt-in registration (idle delivery via send-message)
Off by default. Turn on by launching agy with `TETHER_MAIL_AGY_REGISTER=1` (plus `TETHER_AGENT_URN`). With it unset the PreToolUse hook prints nothing (printing `{}` or any result without `decision` DENIES the tool) and delivery degrades to the hook inbox (active sessions) plus a tmux paste (idle, if in tmux).

Only the FIRST `run_command` of a conversation with no `<cid>.session` is touched (marker `<cid>.reg-attempted`). The hook returns `{"decision":"ask","overwrite":{"CommandLine":"<prefix><original>"}}`; the prefix is exactly (path unquoted when it has no shell-special characters, else single-quoted):

    <plugin>/bin/tether-mail-agy-register >/dev/null 2>&1 </dev/null ; 

Subshell-free: the register script is an external process, so it cannot change cwd/env/options/traps. It exits 0 on every path (own SIGALRM handler at 4 s, excepthook, missing env), so the original's exit status is untouched. Equivalence suite (27 cases x bash/zsh/sh x with/without agy env): 162 runs, 0 differences in stdout/stderr/exit status. Hung register (test hook `TETHER_MAIL_REGISTER_TEST_HANG=I-UNDERSTAND-THIS-IS-A-TEST`): original output and exit code correct, +4.0 s, no stray processes. The earlier `( reg ) ... || : ;` form was also 0-diff but is not split by agy and cannot be allow-listed; it is gone.

## Permission findings (agy 1.3.3)
- **Rules** are `permissions.allow|deny|ask` entries `command(<prefix>)` (also `read_url(...)`). Three scopes in `/permissions`: Project, Shared with Antigravity, Global.
  - Global: `~/.gemini/antigravity-cli/settings.json` `permissions.allow` (verified honored).
  - Project: `~/.gemini/config/projects/<projectId>.json` -> `permissionGrants.permissionGrants.allow` (verified). CLI sessions use `default-cli-project` (one file for ALL cwd's) unless launched `agy --project <id>`; with a pre-created `<id>.json` containing grants, `--project <id>` honors them (verified), a folderUri inside the project file does NOT auto-select it, and `--new-project` makes an agy-created project (name = cwd basename, folderUri = cwd) with no grants.
  - Shared: file not identified. The binary also has `permission_grants_workspace:` keys and LS RPCs `AddPermissionGrants`/`RemovePermissionGrants`; not file-plantable.
- **No workspace/boot-dir/plugin-level rule exists.** Rules in `plugin.json` fields (`permissions`, `permissionGrants`), plugin-dir and `.agents/` and boot-root `settings.json|permissions.json|config.json|settings.local.json` were all ignored (`uname` still prompted).
- **Matching** (persisted rule `command(/abs/path/tether-mail-agy-register)`, conversation had `echo` allowed): agy SPLITS compounds on `;`, `&&`, `&` and judges segments separately, on the raw string, with a token boundary.
  - no prompt: `reg >/dev/null 2>&1 </dev/null ; echo hi`; `reg && echo hi`; `reg ; echo hi`; bare `reg`; `reg --evil-arg` (arguments are accepted, the register script ignores argv).
  - prompt for the other segment only: `reg ; uname`, `reg ; touch X`, `reg & touch X` (X not created).
  - prompt (rule does NOT match): `reg-other`, `reg $(touch X)`, `reg > file`, `"reg"`, `'reg'` (quoted), `/x/../bin/reg`. Quoted forms never match, hence the unquoted prefix.
  - So the rule can only approve running that exact path (any args); it cannot approve a different command appended with `;`/`&&`/`&`. Residual: anything that can write that path can make it run unprompted (same as any allow rule).
  - Old subshell form: not split, suggestion is the whole prefix, no rule helps.
- **Recommendation.** Ship the hooks planted (`planted/`), registration stays opt-in. To remove the single extra prompt, the user (not Tether) adds ONE allow rule once: Global via `/permissions` or `settings.json`, or a Tether-dedicated project (`~/.gemini/config/projects/tether-mail.json` with the grant, launch with `--project tether-mail`, e.g. `planted/project-tether-mail.json`). Because the rule is keyed on the absolute path, the register script needs a STABLE path (a per-boot-dir path means one rule per agent): install `tether-mail-agy-register` (and its `lib/`) at a fixed location and make the prefix point there, or accept one prompt. Tether cannot plant the rule itself.

Known frictions: `decision` is mandatory when `overwrite` is used (omitted or `allowTool:false` => the tool is DENIED). `ask` means the permission check sees the rewritten command: a user who allow-listed `echo` is prompted once for that first command (unavoidable; no hook field makes the check evaluate the original; `ask` + `permissionOverrides:["command(<original>)"]` still prompted on the rewritten text). Users without allow-lists get the same single prompt as without the hook, but it displays the prefix, and its "always allow" options key on the prefix, not the original; do not choose them. With `--dangerously-skip-permissions` no prompt. `$?` at the very start of a command reads 0.

