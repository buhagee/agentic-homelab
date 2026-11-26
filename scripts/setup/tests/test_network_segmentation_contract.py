import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.platform.yml"

DATA_NETWORKS = {
    "immich-data": {"immich-postgres", "immich-redis", "immich-server"},
    "paperless-data": {"paperless-postgres", "paperless-redis", "paperless"},
}
DATA_STORES = {
    "immich-postgres": "immich-data",
    "immich-redis": "immich-data",
    "paperless-postgres": "paperless-data",
    "paperless-redis": "paperless-data",
}
OWNERS = {
    "immich-server": "immich-data",
    "paperless": "paperless-data",
}
OWNER_NETWORKS = {
    "immich-server": {"qacey-proxy", "qacey-internal", "immich-data"},
    "paperless": {"qacey-proxy", "qacey-internal", "paperless-data"},
}


def service_block(text, name):
    match = re.search(
        rf"^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_.-]+:\s*$|\Z)",
        text,
        re.M | re.S,
    )
    if not match:
        raise AssertionError(f"missing service: {name}")
    return match.group(1)


def service_names(text):
    body = text.split("\nservices:", 1)[1]
    end = re.search(r"^networks:", body, re.M)
    body = body[: end.start()] if end else body
    return re.findall(r"^  ([A-Za-z0-9_.-]+):\s*$", body, re.M)


def networks_section(text):
    match = re.search(r"^networks:\n(.*?)(?=^volumes:|\Z)", text, re.M | re.S)
    if not match:
        raise AssertionError("missing networks section")
    return match.group(1)


def network_block(text, name):
    match = re.search(
        rf"^  {re.escape(name)}:\n((?:    .*\n|\n)*)",
        networks_section(text),
        re.M,
    )
    if not match:
        raise AssertionError(f"missing network: {name}")
    return match.group(1)


def has_network(block, network):
    pattern = r"(?m)^      (?:- )?" + re.escape(network) + r"(?::(?:\s*\{\})?)?\s*$"
    return bool(re.search(pattern, block))


def networks_in(block):
    match = re.search(r"(?m)^    networks:\n((?:      [^ \n].*\n)+)", block)
    if not match:
        return set()
    names = set()
    for line in match.group(1).splitlines():
        value = line.strip()
        if value.startswith("- "):
            names.add(value[2:].strip())
        else:
            names.add(value.split(":", 1)[0].strip())
    return names


class NetworkSegmentationContractTests(unittest.TestCase):
    def setUp(self):
        self.text = COMPOSE.read_text(encoding="utf-8")

    def test_data_networks_are_internal(self):
        for name in DATA_NETWORKS:
            block = network_block(self.text, name)
            self.assertIn(f"name: qacey-{name}", block, name)
            self.assertIn("internal: true", block, name)

    def test_data_stores_are_isolated(self):
        for service, network in DATA_STORES.items():
            block = service_block(self.text, service)
            self.assertEqual(networks_in(block), {network}, service)
            self.assertNotRegex(block, r"(?m)^    ports:")

    def test_owning_apps_keep_edge_networks_and_join_data(self):
        for service, expected in OWNER_NETWORKS.items():
            block = service_block(self.text, service)
            self.assertEqual(networks_in(block), expected, service)

    def test_has_network_accepts_compose_network_syntaxes(self):
        list_form = "    networks:\n      - alpha\n"
        empty_mapping = "    networks:\n      beta: {}\n"
        bare_mapping = "    networks:\n      gamma:\n"
        nested_mapping = "    networks:\n      delta:\n        ipv4_address: 172.31.255.9\n"
        for block, name in (
            (list_form, "alpha"),
            (empty_mapping, "beta"),
            (bare_mapping, "gamma"),
            (nested_mapping, "delta"),
        ):
            self.assertTrue(has_network(block, name), name)

    def test_each_data_network_has_only_expected_members(self):
        for network, expected in DATA_NETWORKS.items():
            members = {
                name
                for name in service_names(self.text)
                if has_network(service_block(self.text, name), network)
            }
            self.assertEqual(members, expected, network)


if __name__ == "__main__":
    unittest.main()
