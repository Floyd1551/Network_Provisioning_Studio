import unittest
from unittest.mock import patch
from switch_configurator.transport import SerialTransport


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.is_open = True
        self.written = []
    @property
    def in_waiting(self): return len(self.chunks[0]) if self.chunks else 0
    def read(self, count): return self.chunks.pop(0) if self.chunks else b""
    def write(self, value): self.written.append(value)
    def reset_input_buffer(self): pass
    def close(self): self.is_open = False


class SerialTests(unittest.TestCase):
    def transport(self, chunks):
        transport = SerialTransport("FAKE", timeout=0.01)
        transport.hostname = "SW-01"
        transport.serial = FakeSerial(chunks)
        return transport

    def test_chunked_response_and_exact_prompt(self):
        transport = self.transport([b"show version\r\nCisco IOS text # is not a prompt\r\n", b"SW-", b"01#"])
        self.assertEqual(transport.command("show version"), "Cisco IOS text # is not a prompt")
        self.assertEqual(transport.serial.written, [b"show version\r"])

    def test_configuration_prompt(self):
        transport = self.transport([b"interface Gi1/0/1\r\nSW-01(config-if)#"])
        self.assertEqual(transport.command("interface Gi1/0/1"), "")

    def test_pagination_is_not_complete(self):
        with self.assertRaisesRegex(RuntimeError, "Paging"):
            self.transport([b"partial\r\n--More--"]).command("show running-config")

    def test_timeout_is_not_success(self):
        with self.assertRaises(TimeoutError): self.transport([b"partial data"]).command("show running-config")

    def test_different_host_prompt_is_not_success(self):
        with self.assertRaises(TimeoutError): self.transport([b"SW-02#"]).command("show version")

    def test_multiline_injection_rejected(self):
        with self.assertRaises(ValueError): self.transport([]).command("show version\nreload")

    def test_vendor_configuration_prompts(self):
        cases = (("hash", "OS10", b"OS10(conf-if-eth1/1/1)#"),
                 ("hash", "switch", b"switch(config-if-Et1)#"),
                 ("junos", "admin@switch", b"[edit]\nadmin@switch#"),
                 ("junos", "admin@switch", b"admin@switch>"),
                 ("exos", "LAB", b"* Slot-1 LAB.17 #"))
        for style, hostname, response in cases:
            with self.subTest(style=style, response=response):
                transport = self.transport([b"show test\nvalue\n" + response])
                transport.hostname, transport.prompt_style = hostname, style
                self.assertEqual(transport.command("show test"), "value")

    def test_initial_prompts_select_correct_dialect(self):
        for prompt, style, host in ((b"LAB#", "hash", "LAB"), (b"admin@LAB>", "junos", "admin@LAB"), (b"* Slot-1 LAB.1 #", "exos", "LAB")):
            with self.subTest(prompt=prompt):
                fake = FakeSerial([prompt])
                with patch("serial.Serial", return_value=fake):
                    transport = SerialTransport("FAKE", timeout=0.01)
                    transport.connect()
                    self.assertEqual((transport.prompt_style, transport.hostname), (style, host))
                    transport.close()
                    self.assertFalse(fake.is_open)

    def test_identity_probe_can_advance_a_paged_read_only_response(self):
        transport = self.transport([b"show version\nCisco IOS\n--More--", b"\nVersion 17.9\nSW-01#"])
        output = transport.probe("show version")
        self.assertIn("Version 17.9", output)
        self.assertEqual(transport.serial.written, [b"show version\r", b" "])
        self.assertFalse(transport.allow_paging)
        with self.assertRaises(ValueError): transport.probe("configure terminal")

    def test_login_and_unprivileged_prompts_are_rejected(self):
        for prompt in (b"Username:", b"Password:", b"Switch>"):
            fake = FakeSerial([prompt])
            with self.subTest(prompt=prompt), patch("serial.Serial", return_value=fake):
                with self.assertRaises(RuntimeError): SerialTransport("FAKE", timeout=0.01).connect()
                self.assertFalse(fake.is_open)


if __name__ == "__main__": unittest.main()
