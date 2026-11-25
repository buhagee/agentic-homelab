"""Validate the small portable MCP contract and render Codex/OpenCode V2 values.

Schema1 is {"schema": 1, "servers": {name: definition}}. Every definition has
transport ("stdio" or "http") and optional enabled (default true). Stdio accepts
command, args, cwd and env_vars; HTTP accepts url, bearer_token_env_var and
env_http_headers (header-name -> environment-variable-name). No literal secret
environment/header values or client-specific OAuth/plugin settings are accepted.
The literal {home} expands only in stdio command, arguments and cwd.
"""

import json
from pathlib import Path
import re
from urllib.parse import urlsplit


NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
HEADER = re.compile(r"[!#$%&'*+.^_`|~A-Za-z0-9-]+\Z")


def parse_json(text, label):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Non-finite JSON number")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError):
        # Native configuration can contain credentials. Never include the input
        # or parser excerpt in a diagnostic, including on newer Python versions.
        raise ValueError(f"Invalid JSON in {label}; inspect the file locally.") from None


def _text(value, label, empty=False):
    if not isinstance(value, str) or (not empty and not value) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"Expected a non-control text value for {label}.")
    return value


def _variable(value):
    if not isinstance(value, str) or not ENV.fullmatch(value):
        raise ValueError("MCP environment references must be variable names, not values.")
    return value


def _url(value):
    _text(value, "MCP URL")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or any(c.isspace() for c in value)
                or "{" in value or "}" in value or "\\" in value):
            raise ValueError()
        _ = parsed.port
    except ValueError:
        raise ValueError("MCP URL must be HTTP(S), without credentials, query or fragment.") from None
    return value


def render(text: str, home: Path) -> tuple[dict, dict]:
    manifest = parse_json(text, "shared MCP manifest")
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "servers"}
            or type(manifest["schema"]) is not int or manifest["schema"] != 1
            or not isinstance(manifest["servers"], dict)):
        raise ValueError("Expected shared MCP schema1 with a servers object.")
    codex, opencode = {}, {}
    for name, server in sorted(manifest["servers"].items()):
        if not NAME.fullmatch(name) or not isinstance(server, dict):
            raise ValueError("Invalid shared MCP server name or definition.")
        kind = server.get("transport")
        if not isinstance(kind, str):
            raise ValueError(f"Invalid shared MCP transport for {name}.")
        allowed = {"transport", "enabled"}
        allowed |= ({"command", "args", "cwd", "env_vars"} if kind == "stdio" else
                    {"url", "bearer_token_env_var", "env_http_headers"} if kind == "http" else set())
        if kind not in {"stdio", "http"} or set(server) - allowed:
            raise ValueError(f"Unknown shared MCP fields or transport for {name}.")
        enabled = server.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError(f"MCP enabled must be a boolean for {name}.")
        c, o = {"enabled": enabled}, {"disabled": not enabled}
        if kind == "stdio":
            def expand(value, label, empty=False):
                return _text(value, label, empty).replace("{home}", str(home))

            command = expand(server.get("command"), "MCP command")
            args = server.get("args", [])
            if not isinstance(args, list):
                raise ValueError(f"MCP args must be an array for {name}.")
            args = [expand(arg, "MCP argument", True) for arg in args]
            c.update(command=command, args=args)
            o.update(type="local", command=[command, *args])
            if "cwd" in server:
                cwd = expand(server["cwd"], "MCP cwd")
                if not Path(cwd).is_absolute():
                    raise ValueError(f"MCP cwd must be absolute or start with {{home}} for {name}.")
                c["cwd"] = o["cwd"] = cwd
            if "env_vars" in server:
                variables = server["env_vars"]
                if not isinstance(variables, list):
                    raise ValueError(f"MCP env_vars must be an array for {name}.")
                variables = [_variable(item) for item in variables]
                if len(variables) != len(set(variables)):
                    raise ValueError(f"Duplicate MCP environment reference for {name}.")
                c["env_vars"] = variables
                o["environment"] = {item: "{env:" + item + "}" for item in variables}
        else:
            url = _url(server.get("url"))
            c["url"] = url
            o.update(type="remote", url=url)
            headers = server.get("env_http_headers", {})
            if not isinstance(headers, dict):
                raise ValueError(f"MCP env_http_headers must be an object for {name}.")
            seen = set()
            mapped = {}
            for header, variable in headers.items():
                if not HEADER.fullmatch(header) or header.lower() in seen:
                    raise ValueError(f"Invalid or duplicate MCP HTTP header for {name}.")
                seen.add(header.lower())
                mapped[header] = _variable(variable)
            if "env_http_headers" in server:
                c["env_http_headers"] = mapped
                o["headers"] = {key: "{env:" + value + "}" for key, value in mapped.items()}
            if "bearer_token_env_var" in server:
                if "authorization" in seen:
                    raise ValueError(f"Conflicting MCP Authorization references for {name}.")
                variable = _variable(server["bearer_token_env_var"])
                c["bearer_token_env_var"] = variable
                o.setdefault("headers", {})["Authorization"] = "Bearer {env:" + variable + "}"
        codex[name], opencode[name] = c, o
    return codex, opencode
