"""Local, opt-in production diagnostics and bounded existing-container actions."""
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time

POLICY = Path("/etc/qacey-dev-ops/policy.json")
IDENTITY = Path("/etc/qacey-dev/installation.json")
STATE = Path("/var/lib/qacey-dev-ops")
DEPLOY_LOCK = Path("/run/lock/qacey-deploy.lock")
SOCKET = "/run/qacey-dev-ops.sock"
DOCKER = ("/usr/bin/docker", "--host", "unix:///var/run/docker.sock",
          "--config", "/etc/qacey-dev-ops")
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/root",
       "LC_ALL": "C", "SYSTEMD_PAGER": "cat", "SYSTEMD_COLORS": "0"}
MUTATIONS = {"start", "stop", "restart"}
READS = {"status", "logs"}
SERVICE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}\Z")
UNIT = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}\.(?:service|socket)\Z")
GATEWAY_SERVICES = {"adapter", "oauth"}
CID = re.compile(r"[0-9a-f]{64}\Z")
MAX_BYTES = 65536
COOLDOWN = 60

class Denied(ValueError):
    pass

def unique(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Denied("duplicate JSON key")
        result[key] = value
    return result

def decode(raw):
    return json.loads(raw, object_pairs_hook=unique)

def root_file(path):
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Denied("untrusted policy directory")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise Denied("untrusted policy file")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise Denied("policy too large")
    return decode(raw)

def validate_settings(value):
    required = {"operator", "containers", "units"}
    if not isinstance(value, dict) or not required <= value.keys() <= required | {"gateway"}:
        raise Denied("expected operator, containers and units, with optional gateway")
    if not isinstance(value["operator"], str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value["operator"]):
        raise Denied("invalid operator")
    for category, pattern, allowed in (("containers", SERVICE, READS | MUTATIONS),
                                      ("units", UNIT, READS)):
        entries = value[category]
        if not isinstance(entries, dict) or len(entries) > 100:
            raise Denied("invalid allowlist")
        for name, actions in entries.items():
            if (not pattern.fullmatch(name) or not isinstance(actions, list) or not actions
                    or any(not isinstance(action, str) or action not in allowed for action in actions)
                    or len(set(actions)) != len(actions)):
                raise Denied("invalid target or action")
            if category == "containers" and name in {"opencode-docker-control", "traefik", "cloudflared"} and set(actions) & MUTATIONS:
                raise Denied("control and ingress services are not mutable")
    gateway = value.get("gateway", {})
    if (not isinstance(gateway, dict) or not gateway.keys() <= GATEWAY_SERVICES
            or any(actions != ["status"] for actions in gateway.values())):
        raise Denied("gateway permits status only for adapter and oauth")
    return value

def identity():
    record = root_file(IDENTITY)
    if record.get("schema") != 1 or record.get("ready") is not True:
        raise Denied("development installation not ready")
    account = pwd.getpwnam(record["user"])
    if (account.pw_uid <= 0 or account.pw_uid != record["uid"]
            or account.pw_gid != record["gid"] or account.pw_dir != record["home"]):
        raise Denied("development identity mismatch")
    return account

def policy():
    value = root_file(POLICY)
    validate_settings(value)
    account = identity()
    operator = pwd.getpwnam(value["operator"])
    if operator.pw_uid in (0, account.pw_uid):
        raise Denied("invalid deployment operator")
    return value, account, operator

def capture(argv, *, logs=False, timeout=15):
    """Bound output and time, never execute a shell or return command diagnostics."""
    process = subprocess.Popen(argv, env=ENV, cwd="/", stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT if logs else subprocess.DEVNULL,
                               start_new_session=True)
    deadline = time.monotonic() + timeout
    data = bytearray()
    truncated = False
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise Denied("operation timed out; inspect actual state before retrying")
                block = os.read(process.stdout.fileno(), min(8192, MAX_BYTES + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
                if len(data) > MAX_BYTES:
                    if not logs:
                        raise Denied("unexpected oversized response")
                    truncated = True
                    break
        if not truncated and process.wait(timeout=max(.01, deadline - time.monotonic())) != 0:
            raise Denied("command failed; inspect locally")
    except subprocess.TimeoutExpired:
        raise Denied("operation timed out; inspect actual state before retrying") from None
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.stdout.close()
        process.wait()
    text = data[:MAX_BYTES].decode("utf-8", errors="replace")
    # Avoid terminal escape/control sequences; logs can still contain private data.
    text = "".join(c if c in "\n\t" or c.isprintable() else "?" for c in text)
    return text + ("\n[output truncated]" if truncated else "")

def container_id(name, *, project="qacey-platform"):
    output = capture([*DOCKER, "container", "ls", "--all", "--no-trunc",
                      "--filter", "label=com.docker.compose.project=" + project,
                      "--filter", "label=com.docker.compose.service=" + name,
                      "--format", "{{.ID}}"])
    ids = output.splitlines()
    if len(ids) != 1 or not CID.fullmatch(ids[0]):
        raise Denied("expected exactly one existing approved container")
    return ids[0]

def gateway_status(target):
    identifier = container_id(target, project="qacey-dev-web")
    output = capture([*DOCKER, "container", "inspect", "--format",
                      "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}\n"
                      "{{json .State.Error}}", identifier])
    status, _, error_json = output.partition("\n")
    error = json.loads(error_json)
    if not error:
        return status
    if (target == "adapter" and "/run/qacey-dev-proxy" in error
            and "no such file or directory" in error):
        return status + " error=proxy-directory-missing"
    return status + " error=container-start-failed"

def mutation_lock(operator):
    fd = os.open(DEPLOY_LOCK, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != operator.pw_uid
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise Denied("deployment lock is not trusted")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Denied("platform deployment or another operation is active") from None
        if not os.path.samestat(info, DEPLOY_LOCK.lstat()):
            raise Denied("deployment lock changed")
        return fd
    except BaseException:
        os.close(fd)
        raise

def rate_limit():
    info = STATE.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise Denied("untrusted operations state")
    path = STATE / "last-action"
    now = int(time.time())
    try:
        previous = root_file(path)
    except FileNotFoundError:
        previous = 0
    if type(previous) is not int or previous < 0 or now - previous < COOLDOWN:
        raise Denied("mutation cooldown; try later")
    with tempfile.NamedTemporaryFile(dir=STATE, delete=False) as stream:
        pending = Path(stream.name)
        try:
            stream.write(str(now).encode())
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)

def host_metrics():
    disks = {}
    for path in ("/", "/mnt/ssd", "/mnt/hdd1", "/mnt/hdd2"):
        if path != "/" and not os.path.ismount(path):
            disks[path] = {"mounted": False}
            continue
        fs = os.statvfs(path)
        disks[path] = {"mounted": True, "total_bytes": fs.f_blocks * fs.f_frsize,
                       "available_bytes": fs.f_bavail * fs.f_frsize}
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
            memory[key + "_kib"] = int(value.split()[0])
    return {"load_average": os.getloadavg(), "cpu_count": os.cpu_count(),
            "memory": memory, "disks": disks}

def dispatch(request, settings, operator):
    if request == {"action": "monitor"}:
        return host_metrics()
    if request == {"action": "list"}:
        return {"containers": settings["containers"], "units": settings["units"],
                "gateway": settings.get("gateway", {})}
    if not isinstance(request, dict) or set(request) != {"action", "kind", "target"}:
        raise Denied("invalid request")
    action, kind, target = (request[k] for k in ("action", "kind", "target"))
    if not all(isinstance(value, str) for value in (action, kind, target)):
        raise Denied("invalid request")
    if kind == "gateway":
        if action != "status" or target not in settings.get("gateway", {}):
            raise Denied("operation not allowed")
        return gateway_status(target)
    if kind not in ("containers", "units") or action not in settings[kind].get(target, []):
        raise Denied("operation not allowed")
    if kind == "units":
        if action == "status":
            return capture(["/usr/bin/systemctl", "show", "--no-pager",
                            "--property=LoadState,ActiveState,SubState,Result,UnitFileState", target])
        return capture(["/usr/bin/journalctl", "--no-pager", "--output=cat",
                        "--lines=100", "--unit=" + target], logs=True)
    if action in MUTATIONS:
        fd = mutation_lock(operator)
        try:
            identifier = container_id(target)
            rate_limit()
            print("qacey-dev-ops: " + action + " " + target, file=sys.stderr, flush=True)
            capture([*DOCKER, "container", action, identifier], timeout=60)
            return "accepted; check status for resulting health"
        finally:
            os.close(fd)
    identifier = container_id(target)
    if action == "status":
        return capture([*DOCKER, "container", "inspect", "--format",
                        "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}",
                        identifier])
    return capture([*DOCKER, "container", "logs", "--tail", "100", identifier], logs=True)

def serve(connection):
    connection.settimeout(5)
    try:
        settings, account, operator = policy()
        _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != account.pw_uid:
            raise Denied("unauthorized peer")
        with connection.makefile("rb") as stream:
            line = stream.readline(4097)
            if len(line) > 4096 or not line.endswith(b"\n"):
                raise Denied("invalid request size")
            value = dispatch(decode(line), settings, operator)
        response = {"ok": True, "result": value}
    except Denied as exc:
        response = {"ok": False, "error": str(exc)}
    except Exception:
        response = {"ok": False, "error": "request failed; inspect service diagnostics locally"}
    connection.sendall((json.dumps(response, ensure_ascii=True) + "\n").encode())

if __name__ == "__main__":
    with socket.socket(fileno=0) as connection:
        serve(connection)
