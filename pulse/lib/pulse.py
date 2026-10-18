"""Shared bits for tether-pulse: where state lives, atomic writes, process helpers, redaction.

Hooks write one small JSON file per live agent under
<root>/<machine>/<tool>-<session>.json.  Nothing here touches the network.
"""
import json, os, re, socket, subprocess, sys, tempfile, time

sys.dont_write_bytecode = True

TASK_RE = re.compile(r"\bCW-\d{8}-\d{4}\b")
# Explicit secret shapes; STRICT adds a long opaque-token catch for free-form command text.
_SECRET = re.compile(r"(?i)(sk-[A-Za-z0-9_\-]{12,}|bearer\s+[A-Za-z0-9._\-]{12,}"
                     r"|(?:token|secret|password|passwd|api[_-]?key)\s*[=:]\s*\S+)")
_OPAQUE = re.compile(r"(?<![A-Za-z0-9/._~\-])[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9/._~\-])")


_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def worker_label(root=None):
    """The label the Tether worker on this machine reports to the hub, or "".

    The worker reads <root>/<machine> to relay activity, and the hub names the machine by this
    label, so hooks must write under the same name. A hook started outside a shell that exports
    TETHER_PULSE_MACHINE (Codex or Agy launched from a terminal, say) would otherwise fall back to
    the hostname and land where the worker never looks. The label is a directory name, so only a
    plain name is accepted.
    """
    path = os.path.join(root or os.path.expanduser("~/.tether-worker"), "config.json")
    try:
        with open(path) as f:
            label = json.load(f).get("label")
    except (OSError, ValueError, AttributeError):
        return ""
    return label if isinstance(label, str) and _LABEL.fullmatch(label) else ""


def machine():
    """TETHER_PULSE_MACHINE, else the Tether worker's label, else the short hostname."""
    return (os.environ.get("TETHER_PULSE_MACHINE") or worker_label()
            or socket.gethostname().split(".")[0])


def root():
    base = os.environ.get("TETHER_PULSE_DIR")
    if not base:
        base = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "tether-pulse")
    return base


def machine_dir(create=False):
    d = os.path.join(root(), machine())
    if create:
        os.makedirs(root(), mode=0o700, exist_ok=True)
        os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def file_for(tool, sid, create=False):
    assert sid and "/" not in sid and not sid.startswith("."), "bad session id"
    return os.path.join(machine_dir(create), "%s-%s.json" % (tool, sid))


def read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_atomic(path, doc):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def now_ms():
    return int(time.time() * 1000)


def _ps(args, timeout=2):
    env = dict(os.environ, LC_ALL="C")
    try:
        return subprocess.run(["ps"] + args, capture_output=True, text=True, timeout=timeout, env=env).stdout.strip()
    except Exception:
        return ""


def proc_start(pid):
    """Process start time string; with the pid it identifies a process even across pid reuse."""
    return _ps(["-o", "lstart=", "-p", str(pid)])


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True


def ancestor(names, start=None):
    """pid of the nearest ancestor whose command name starts with one of `names`; 0 if none."""
    pid = start or os.getppid()
    for _ in range(10):
        out = _ps(["-o", "ppid=,comm=", "-p", str(pid)]).split(None, 1)
        if len(out) < 2:
            return 0
        try:
            ppid, comm = int(out[0]), os.path.basename(out[1].strip())
        except ValueError:
            return 0
        if any(comm.startswith(n) for n in names):
            return pid
        if ppid <= 1:
            return 0
        pid = ppid
    return 0


def tmux_info():
    pane = os.environ.get("TMUX_PANE", "")
    if not pane:
        return None
    try:
        out = subprocess.run(["tmux", "display-message", "-p", "-t", pane, "#{session_name}\t#{window_index}.#{pane_index}"],
                             capture_output=True, text=True, timeout=1.5).stdout.strip().split("\t")
        if len(out) == 2 and out[0]:
            return {"session": out[0], "pane": out[1], "pane_id": pane}
    except Exception:
        pass
    return {"pane_id": pane}


def clean(s, n=120, strict=False):
    """One line, control chars gone, secrets masked, truncated."""
    s = " ".join(str(s).split())
    s = "".join(c for c in s if c.isprintable())
    s = _SECRET.sub("[redacted]", s)
    if strict:
        s = _OPAQUE.sub(lambda m: "[redacted]" if re.search(r"\d", m.group(0)) and re.search(r"[A-Za-z]", m.group(0)) else m.group(0), s)
    return s if len(s) <= n else s[: n - 1] + "…"


def action_target(tool_name, tool_input):
    """Short, redacted description of what a tool call is acting on. Never the whole input."""
    if not isinstance(tool_input, dict):
        return ""
    for k in ("file_path", "path", "notebook_path", "pattern", "url", "query", "CommandLine", "command", "description"):
        v = tool_input.get(k)
        if isinstance(v, str) and v.strip():
            return clean(v, 120, strict=k in ("CommandLine", "command", "url", "query"))
    return ""


def find_task(*texts):
    for t in texts:
        if isinstance(t, str):
            m = TASK_RE.findall(t)
            if m:
                return m[-1]
    return ""
