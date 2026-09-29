import copy
import tempfile
import unittest
from unittest.mock import patch
from switch_configurator.storage import Store
from switch_configurator.firewall_api.demo import SonicDemo
from switch_configurator.firewall_api.http import HTTPS, NoRedirect
from switch_configurator.firewall_api.sonicos import SonicOS
from switch_configurator.firewall_api.service import APIService
from switch_configurator.firewall_api.panos import PANOS
from switch_configurator.firewall_api.demo import PANDemo
from switch_configurator.firewall_api.demo import CheckPointDemo
from switch_configurator.firewall_api.checkpoint import CheckPoint


RULE = dict(name="Lab HTTPS", source="Lab clients", destination="Lab server", service="HTTPS", from_zone="LAN", to_zone="WAN", action="allow")


class FirewallAPITests(unittest.TestCase):
    def checkpoint(self, directory):
        adapter = CheckPoint(CheckPointDemo(), "demo", "test-password", "Network", "Lab", "Lab gateway")
        service = APIService(adapter, Store(directory)); service.connect()
        return service

    def test_checkpoint_fresh_sessions_publish_install_and_target_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.checkpoint(directory)
            rule = {k: v for k, v in RULE.items() if k not in ("from_zone", "to_zone")}
            plan = service.preview([rule]); after, path = service.apply(plan)
            self.assertEqual(service.transport.sessions, 3)
            self.assertEqual(after.data["rules"][0]["source"], ["network-1"])
            install = next(body for command, body in service.transport.sent if command == "install-policy")
            self.assertEqual(install["targets"], ["Lab gateway"])
            self.assertFalse(install["threat-prevention"])
            self.assertEqual(len(service.transport.tasks), 2)
            for file in path.iterdir(): self.assertNotIn("test-password", file.read_text())

    def test_checkpoint_stale_snapshot_blocks_writes_and_install_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            rule = {k: v for k, v in RULE.items() if k not in ("from_zone", "to_zone")}
            service = self.checkpoint(directory); plan = service.preview([rule])
            service.transport.collections["show-hosts"][0]["ipv4-address"] = "192.0.2.99"
            with self.assertRaisesRegex(RuntimeError, "changed since review"): service.apply(plan)
            self.assertFalse(any(command == "add-access-rule" for command, _ in service.transport.sent))
            plan = service.preview([rule]); service.transport.fail_install = True
            with self.assertRaisesRegex(RuntimeError, "Policy installation did not succeed"): service.apply(plan)
            self.assertIn("failed", service.store.history()[0][2])

    def test_checkpoint_rejects_truncated_pagination_and_unexpected_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.checkpoint(directory)
            with patch.object(service.adapter, "call", return_value={"objects": [], "total": 10}):
                with self.assertRaisesRegex(RuntimeError, "Truncated"): service.adapter.collect("show-hosts")
            with patch.object(service.adapter, "call", return_value={"tasks": [{"task-id": "other", "status": "succeeded"}]}):
                with self.assertRaisesRegex(RuntimeError, "identity"): service.adapter.wait_task({"task-id": "expected"}, "Publish")

    def pan(self, directory):
        service = APIService(PANOS(PANDemo(), "demo", "test-api-key"), Store(directory))
        service.connect()
        return service

    def test_panos_native_xml_locks_commit_job_and_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.pan(directory)
            rule = dict(RULE, from_zone="trust", to_zone="untrust")
            plan = service.preview([rule])
            self.assertIn("<service><member>HTTPS</member></service>", plan.operations[0]["form"]["element"])
            after, path = service.apply(plan)
            service.adapter.verify(plan, after)
            self.assertEqual(service.transport.locks, set())
            for file in path.iterdir(): self.assertNotIn("test-api-key", file.read_text())
            self.assertTrue(any(f.get("cmd", "").startswith("<show><jobs>") for f in service.transport.sent))

    def test_panos_existing_locks_or_candidate_are_untouched(self):
        from xml.etree import ElementTree as ET
        with tempfile.TemporaryDirectory() as directory:
            for locked in (True, False):
                service = self.pan(directory)
                plan = service.preview([dict(RULE, from_zone="trust", to_zone="untrust")])
                if locked: service.transport.locks.add("config")
                else: ET.SubElement(service.transport.candidate, "unrelated").text = "pending"
                with self.assertRaises(RuntimeError): service.apply(plan)
                self.assertFalse(any(f.get("action") == "set" or f["type"] == "commit" for f in service.transport.sent))
                if locked: self.assertIn("config", service.transport.locks)
                else: self.assertIsNotNone(service.transport.candidate.find("unrelated"))

    def test_panos_foreign_candidate_after_staging_prevents_commit(self):
        from xml.etree import ElementTree as ET
        with tempfile.TemporaryDirectory() as directory:
            service = self.pan(directory); plan = service.preview([dict(RULE, from_zone="trust", to_zone="untrust")])
            original = service.transport.request
            def request(*args, **kwargs):
                response = original(*args, **kwargs)
                if kwargs.get("form", {}).get("action") == "set": ET.SubElement(service.transport.candidate, "unrelated").text = "changed"
                return response
            service.transport.request = request
            with self.assertRaisesRegex(RuntimeError, "Unrelated candidate"): service.apply(plan)
            self.assertFalse(any(f["type"] == "commit" for f in service.transport.sent))
            self.assertEqual(service.transport.locks, set())

    def test_panos_failed_commit_never_reports_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.pan(directory); service.transport.fail_job = True
            plan = service.preview([dict(RULE, from_zone="trust", to_zone="untrust")])
            with self.assertRaisesRegex(RuntimeError, "commit failed"): service.apply(plan)
            self.assertTrue(service.adapter.dirty)
            self.assertIn("failed", service.store.history()[0][2])
            self.assertEqual(service.transport.locks, set())

    def service(self, directory):
        transport = SonicDemo()
        adapter = SonicOS(transport, "test-user", "not-a-real-password")
        service = APIService(adapter, Store(directory)); service.connect()
        return service

    def test_native_rule_deployment_commit_readback_and_no_credentials_in_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory); plan = service.preview([RULE])
            rule = plan.operations[0]["body"]["access_rules"][0]["ipv4"]
            self.assertEqual(rule["source"], {"address": {"name": "Lab clients"}, "port": {"any": True}})
            self.assertEqual(rule["priority"], {"end": True})
            self.assertEqual(rule["schedule"], {"always_on": True})
            after, path = service.apply(plan)
            self.assertEqual(after.data["rules"]["access_rules"][0]["ipv4"]["name"], "Lab HTTPS")
            for file in path.iterdir(): self.assertNotIn("not-a-real-password", file.read_text())
            self.assertEqual(service.store.history()[0][2], "API configuration verified")
            service.close(); self.assertEqual(service.transport.headers, {})

    def test_pending_and_concurrent_configuration_are_not_committed(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory); plan = service.preview([RULE])
            service.transport.pending = {"unrelated": [{"pending": "MODIFY"}]}
            with self.assertRaisesRegex(RuntimeError, "pending configuration"): service.apply(plan)
            self.assertFalse(any(m == "POST" and p.endswith("/config/pending") for m, p, _ in service.transport.sent))
            service.transport.pending = {}
            service.transport.data["/zones"]["zones"].append({"name": "DMZ"})
            with self.assertRaisesRegex(RuntimeError, "changed since review"): service.apply(plan)

    def test_added_foreign_pending_change_blocks_commit_and_preserves_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory); plan = service.preview([RULE])
            original = service.transport.request
            def request(method, path, payload=None, **kwargs):
                result = original(method, path, payload, **kwargs)
                if method == "POST" and path.endswith("/access-rules/ipv4"):
                    service.transport.pending["interfaces"] = [{"pending": "MODIFY"}]
                return result
            service.transport.request = request
            with self.assertRaisesRegex(RuntimeError, "Unexpected pending"): service.apply(plan)
            service.close()
            self.assertTrue(service.transport.pending)
            self.assertFalse(any(m == "DELETE" or (m == "POST" and p.endswith("/config/pending")) for m, p, _ in service.transport.sent))

    def test_tampered_plan_missing_objects_and_unapplied_rules_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.service(directory); plan = service.preview([RULE])
            with self.assertRaises(RuntimeError): service.adapter.verify(plan, service.discover())
            plan.operations[0]["body"]["access_rules"][0]["ipv4"]["management"] = True
            with self.assertRaisesRegex(ValueError, "modified"): service.apply(plan)
            with self.assertRaisesRegex(ValueError, "existing IPv4"): service.preview([dict(RULE, source="missing")])

    def test_https_rejects_redirects_and_uses_verified_context(self):
        for host in ("http://firewall", "user@firewall", "firewall/path", "firewall\n"):
            with self.assertRaises(ValueError): HTTPS(host)
        with patch("ssl.create_default_context") as context, patch("urllib.request.build_opener"):
            transport = HTTPS("firewall.example", ca_file="trusted.pem")
            context.assert_called_once_with(cafile="trusted.pem")
            self.assertEqual(transport.origin, "https://firewall.example:443")
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere"))
