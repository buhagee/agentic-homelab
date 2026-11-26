#!/usr/bin/python3
"""Use the local operations broker from either native harness."""
import argparse
import json
import os
import socket
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("monitor", "list", "storage", "prune"):
        commands.add_parser(action, allow_abbrev=False)
    for action in ("status", "logs", "start", "stop", "restart"):
        command = commands.add_parser(action, allow_abbrev=False)
        kinds = ("containers", "units", "gateway") if action == "status" else ("containers", "units")
        command.add_argument("kind", choices=kinds)
        command.add_argument("target")
    sudo_command = commands.add_parser("sudo", allow_abbrev=False)
    sudo_command.add_argument("argv", nargs=argparse.REMAINDER)
    request = vars(parser.parse_args())
    if request["action"] == "sudo":
        argv = request["argv"]
        if argv and argv[0] == "--":
            argv = argv[1:]
        if not argv:
            print("Operations request failed: sudo requires a command", file=sys.stderr)
            return 1
        request["argv"] = argv
        request["password"] = os.environ.get("QACEY_SUDO_PASSWORD", "")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(310)
            connection.connect("/run/qacey-dev-ops.sock")
            connection.sendall((json.dumps(request) + "\n").encode())
            with connection.makefile("rb") as stream:
                response = json.loads(stream.readline(1024 * 1024))
        if response.get("ok") is not True:
            raise ValueError(response.get("error", "request failed"))
        result = response["result"]
        print(result if isinstance(result, str) else json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print("Operations request failed: " + str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
