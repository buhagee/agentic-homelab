#!/usr/bin/python3
"""Use the local operations broker from either native harness."""
import argparse
import json
import socket
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("monitor", "list"):
        commands.add_parser(action, allow_abbrev=False)
    for action in ("status", "logs", "start", "stop", "restart"):
        command = commands.add_parser(action, allow_abbrev=False)
        command.add_argument("kind", choices=("containers", "units"))
        command.add_argument("target")
    request = vars(parser.parse_args())
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(75)
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
