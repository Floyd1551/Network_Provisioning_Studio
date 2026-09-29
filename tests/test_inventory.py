import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
import copy
from switch_configurator.inventory import DeviceProfile, Inventory, WindowsVault
from switch_configurator.storage import Store
from switch_configurator.qualification import capture
from switch_configurator.service import Service
from switch_configurator.transport import DemoTransport


class MemoryVault:
    def __init__(self): self.values = {}
    def save(self, ident, username, password, secret=""):
        self.values[ident] = dict(username=username, password=password, secret=secret)
    def read(self, ident): return self.values.get(ident)
    def delete(self, ident): self.values.pop(ident, None)


class InventoryTests(unittest.TestCase):
    def test_secrets_stay_out_of_metadata_and_endpoint_changes_forget_them(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Inventory(Store(directory), MemoryVault())
            profile = DeviceProfile("Lab", "cisco_ios", "192.0.2.10", username="operator", site="Home")
            inventory.save(profile, "unique-password", "unique-enable-secret")
            self.assertEqual(inventory.all(), [profile])
            self.assertEqual(inventory.credentials(profile.id)["password"], "unique-password")
            database = (Path(directory) / "history.sqlite3").read_bytes()
            self.assertNotIn(b"unique-password", database)
            self.assertNotIn(b"unique-enable-secret", database)
            profile.site = "Lab room"
            inventory.save(profile)
            self.assertIsNotNone(inventory.credentials(profile.id))
            old_profile = copy.deepcopy(profile)
            profile.host = "192.0.2.11"
            inventory.save(profile)
            self.assertIsNone(inventory.credentials(profile.id))
            inventory.save(profile, "replacement-password")
            with self.assertRaisesRegex(ValueError, "changed"):
                inventory.connection_credentials(old_profile)
            self.assertEqual(inventory.connection_credentials(profile)["password"], "replacement-password")
            inventory.remove(profile.id)
            self.assertEqual(inventory.all(), [])

    def test_capture_never_claims_hardware_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            device = Service(DemoTransport(), store).connect()
            simulated = json.loads((capture(store, device, True) / "report.json").read_text())
            self.assertEqual(simulated["source"], "simulation")
            self.assertEqual(simulated["qualification"], "not hardware tested")
            live = json.loads((capture(store, device, False) / "report.json").read_text())
            self.assertEqual(live["qualification"], "discovery captured; provisioning not validated")
            self.assertEqual(live["configuration_sha256"], simulated["configuration_sha256"])
            self.assertTrue(live["evidence"])

    @unittest.skipUnless(os.name == "nt", "Windows Credential Manager")
    def test_windows_vault_round_trip_and_delete(self):
        vault = WindowsVault()
        ident = str(uuid.uuid4())
        try:
            vault.save(ident, "test-user", "test-password-å", "test-secret")
            self.assertEqual(vault.read(ident), dict(username="test-user", password="test-password-å", secret="test-secret"))
        finally: vault.delete(ident)
        self.assertIsNone(vault.read(ident))
