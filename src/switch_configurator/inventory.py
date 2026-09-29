"""Saved endpoints contain metadata only; secrets live in Windows Credential Manager."""
from dataclasses import dataclass, asdict, field
import ctypes
from ctypes import wintypes
import json
import os
import uuid


@dataclass
class DeviceProfile:
    name: str
    platform: str
    host: str
    port: int = 22
    username: str = ""
    site: str = ""
    role: str = ""
    model: str = ""
    firmware: str = ""
    transport: str = "SSH"
    trust_file: str = ""
    id: str = ""
    api_context: dict = field(default_factory=dict)

    def validate(self):
        if not self.id: self.id = str(uuid.uuid4())
        uuid.UUID(self.id)
        if not self.name.strip() or not self.host.strip(): raise ValueError("Name and host/COM port are required.")
        if not isinstance(self.port, int) or not 1 <= self.port <= 65535: raise ValueError("Invalid port.")
        if self.transport not in ("SSH", "Serial", "HTTPS API"): raise ValueError("Unsupported connection type.")
        for key, value in asdict(self).items():
            if key == "port": continue
            if key == "api_context":
                if not isinstance(value, dict) or set(value) - {"vsys", "domain", "layer", "package", "target"} or any(not isinstance(v, str) or len(v) > 200 or any(ord(c) < 32 for c in v) for v in value.values()):
                    raise ValueError("Invalid API scope settings.")
                continue
            if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 32 for c in value): raise ValueError("Invalid inventory field: " + key)


class WindowsVault:
    prefix = "NetworkProvisioningStudio/"
    def __init__(self):
        if os.name != "nt": raise RuntimeError("Secure credential storage requires Windows Credential Manager.")
        class Credential(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                        ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
        self.Credential = Credential
        self.api = ctypes.WinDLL("advapi32", use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredDeleteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredFree.restype = None

    def target(self, ident): return self.prefix + str(uuid.UUID(ident))

    def save(self, ident, username, password, secret=""):
        data = json.dumps({"password": password, "secret": secret}).encode("utf-8")
        if len(data) > 2560: raise ValueError("Credential is too large for Windows Credential Manager.")
        blob = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        credential = self.Credential(Type=1, TargetName=self.target(ident), CredentialBlobSize=len(data),
                                     CredentialBlob=blob, Persist=2, UserName=username)
        try:
            if not self.api.CredWriteW(ctypes.byref(credential), 0): raise ctypes.WinError(ctypes.get_last_error())
        finally: ctypes.memset(blob, 0, len(data))

    def read(self, ident):
        pointer = ctypes.POINTER(self.Credential)()
        if not self.api.CredReadW(self.target(ident), 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168: return None
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            credential = pointer.contents
            data = json.loads(ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize).decode("utf-8"))
            return {"username": credential.UserName, **data}
        finally: self.api.CredFree(pointer)

    def delete(self, ident):
        if not self.api.CredDeleteW(self.target(ident), 1, 0) and ctypes.get_last_error() != 1168:
            raise ctypes.WinError(ctypes.get_last_error())


class Inventory:
    def __init__(self, store, vault=None):
        self.store, self.vault = store, vault
        with store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, metadata TEXT NOT NULL)")

    def secure_store(self):
        if self.vault is None: self.vault = WindowsVault()
        return self.vault

    def save(self, profile, password=None, secret=""):
        profile.validate()
        previous = next((p for p in self.all() if p.id == profile.id), None)
        binding = lambda p: (p.platform, p.host, p.port, p.username, p.transport, p.api_context)
        if previous and binding(previous) != binding(profile) and password is None:
            self.secure_store().delete(profile.id)
        if password is not None: self.secure_store().save(profile.id, profile.username, password, secret)
        with self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO devices VALUES (?,?)", (profile.id, json.dumps(asdict(profile))))
        return profile.id

    def all(self):
        with self.store.db() as db:
            return [DeviceProfile(**json.loads(row[0])) for row in db.execute("SELECT metadata FROM devices ORDER BY json_extract(metadata, '$.site'), json_extract(metadata, '$.name')")]

    def remove(self, ident):
        self.secure_store().delete(ident)
        with self.store.db() as db: db.execute("DELETE FROM devices WHERE id=?", (ident,))

    def credentials(self, ident): return self.secure_store().read(ident)

    def connection_credentials(self, profile):
        current = next((p for p in self.all() if p.id == profile.id), None)
        fields = ("platform", "host", "port", "username", "transport", "trust_file", "api_context")
        if current is None or any(getattr(current, key) != getattr(profile, key) for key in fields):
            raise ValueError("The saved connection changed or was removed. Load it again before connecting.")
        return self.credentials(profile.id)

    def forget_credentials(self, ident): self.secure_store().delete(ident)
