import importlib.util
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("dev_ops_test", ROOT / "infrastructure/dev-ops/broker.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"operator": "operator", "containers": {"search": ["status", "logs", "restart"]},
                         "units": {"example.service": ["status", "logs"]}}
        self.operator = SimpleNamespace(pw_uid=1234)

    def test_policy_is_strict(self):
        self.assertEqual(ops.validate_settings(self.settings), self.settings)
        for kind, target, actions in (("containers", "--all", ["status"]),
                                      ("containers", "search", ["exec"]),
                                      ("units", "example.service", ["restart"]),
                                      ("containers", "traefik", ["restart"]),
                                      ("containers", "search", ["logs", "logs"])):
            bad = {"operator": "operator", "containers": {}, "units": {}}
            bad[kind][target] = actions
            with self.subTest(bad=bad), self.assertRaises(ops.Denied):
                ops.validate_settings(bad)
        with self.assertRaises(ops.Denied):
            ops.decode('{"action":"status","action":"restart"}')

    def test_request_cannot_add_flags_or_access_unapproved_targets(self):
        for request in ({"action":"logs","kind":"containers","target":"--all"},
                        {"action":"restart","kind":"units","target":"example.service"},
                        {"action":"status","kind":"containers","target":"other"},
                        {"action":"logs","kind":"containers","target":"search","tail":10000},
                        {"action":[],"kind":"containers","target":"search"}):
            with patch.object(ops, "capture") as call, self.assertRaises(ops.Denied):
                ops.dispatch(request, self.settings, self.operator)
            call.assert_not_called()

    def test_container_status_uses_fixed_project_and_exact_id(self):
        cid = "a" * 64
        with patch.object(ops, "capture", side_effect=[cid+"\n", "running healthy"]) as call:
            result = ops.dispatch({"action":"status","kind":"containers","target":"search"},
                                  self.settings,self.operator)
        self.assertEqual(result, "running healthy")
        self.assertIn("label=com.docker.compose.project=qacey-platform", call.call_args_list[0].args[0])
        self.assertIn("label=com.docker.compose.service=search", call.call_args_list[0].args[0])
        self.assertEqual(call.call_args_list[1].args[0][-1],cid)
        self.assertNotIn(".Config", call.call_args_list[1].args[0][-2])

    def test_gateway_status_uses_exact_project_and_reports_only_safe_errors(self):
        settings = ops.validate_settings(dict(self.settings, gateway={"adapter": ["status"]}))
        cid = "a" * 64
        cases = (("running no-healthcheck", "", "running no-healthcheck"),
                 ("exited no-healthcheck", "open /run/qacey-dev-proxy: no such file or directory",
                  "exited no-healthcheck error=proxy-directory-missing"),
                 ("exited no-healthcheck", "private details", "exited no-healthcheck error=container-start-failed"))
        for state, error, expected in cases:
            with self.subTest(expected=expected), patch.object(
                    ops, "capture", side_effect=[cid + "\n", state + "\n" + json.dumps(error)]) as call:
                result = ops.dispatch({"action": "status", "kind": "gateway", "target": "adapter"},
                                      settings, self.operator)
                self.assertEqual(result, expected)
                self.assertIn("label=com.docker.compose.project=qacey-dev-web", call.call_args_list[0].args[0])
                self.assertIn("label=com.docker.compose.service=adapter", call.call_args_list[0].args[0])
                self.assertEqual(call.call_args_list[1].args[0][-1], cid)

    def test_gateway_rejects_unlisted_targets_and_any_non_status_action(self):
        settings = ops.validate_settings(dict(self.settings, gateway={"adapter": ["status"]}))
        for target, actions in (("traefik", ["status"]), ("adapter", ["status", "restart"]),
                                ("oauth", ["logs"])):
            with self.assertRaises(ops.Denied):
                ops.validate_settings(dict(settings, gateway={target: actions}))
        for action, target in (("status", "oauth"), ("restart", "adapter"), ("logs", "adapter")):
            with patch.object(ops, "capture") as call, self.assertRaises(ops.Denied):
                ops.dispatch({"action": action, "kind": "gateway", "target": target}, settings, self.operator)
            call.assert_not_called()

    def test_socket_unit_can_be_inspected(self):
        name = "qacey-dev-proxy.socket"
        settings = ops.validate_settings(dict(self.settings, units={name: ["status"]}))
        with patch.object(ops, "capture", return_value="ActiveState=active") as call:
            ops.dispatch({"action": "status", "kind": "units", "target": name}, settings, self.operator)
        self.assertEqual(call.call_args.args[0][-1], name)

    def test_ambiguous_container_never_mutates(self):
        with patch.object(ops, "capture", return_value=("a"*64+"\n"+"b"*64+"\n")), self.assertRaises(ops.Denied):
            ops.container_id("search")

    def test_mutation_uses_lock_and_rate_limit(self):
        with patch.object(ops, "mutation_lock", return_value=9) as lock, \
             patch.object(ops, "rate_limit", side_effect=ops.Denied("cooldown")), \
             patch.object(ops, "container_id", return_value="a"*64), \
             patch.object(ops, "capture") as call, patch.object(ops.os,"close") as close:
            with self.assertRaises(ops.Denied):
                ops.dispatch({"action":"restart","kind":"containers","target":"search"},self.settings,self.operator)
            call.assert_not_called()
            lock.assert_called_once_with(self.operator)
            close.assert_called_once_with(9)

    def test_successful_mutation_uses_existing_container_not_compose(self):
        with patch.object(ops, "mutation_lock", return_value=9), patch.object(ops, "rate_limit"), \
             patch.object(ops, "container_id", return_value="a"*64), \
             patch.object(ops, "capture") as call, patch.object(ops.os,"close"):
            ops.dispatch({"action":"restart","kind":"containers","target":"search"},self.settings,self.operator)
        self.assertEqual(call.call_args.args[0][-3:], ["container","restart","a"*64])

    def test_unit_output_is_limited_to_selected_unit_and_fields(self):
        with patch.object(ops,"capture",return_value="ActiveState=active") as call:
            ops.dispatch({"action":"status","kind":"units","target":"example.service"},self.settings,self.operator)
        self.assertEqual(call.call_args.args[0][-1],"example.service")
        self.assertNotIn("Environment",str(call.call_args))

    def test_peer_identity_checked_before_dispatch(self):
        left, right = socket.socketpair()
        with left, right, patch.object(ops,"policy",return_value=(self.settings,SimpleNamespace(pw_uid=0 if ops.os.getuid()!=0 else 999),self.operator)), \
             patch.object(ops,"dispatch") as dispatch:
            ops.serve(left)
            response = json.loads(right.recv(4096))
        self.assertFalse(response["ok"])
        dispatch.assert_not_called()

    def test_capture_bounds_logs_and_strips_terminal_escape(self):
        output = ops.capture([sys.executable,"-c","print('\\x1b[31m'+'a'*70000)"],logs=True)
        self.assertIn("[output truncated]",output)
        self.assertNotIn("\x1b",output)
        with self.assertRaises(ops.Denied):
            ops.capture([sys.executable,"-c","print('a'*70000)"])

    def test_capture_timeout(self):
        with self.assertRaises(ops.Denied):
            ops.capture([sys.executable,"-c","import time; time.sleep(2)"],timeout=.05)

if __name__ == "__main__":
    unittest.main()
