"""Explicit platform registry. Unknown hardware is never treated as Cisco."""
from .base import CiscoIOS
from .cli import EOS, NXOS, ArubaCX, DellOS10, JetStream
from .extreme import ExtremeEXOS
from .junos import JunosELS

DRIVERS = {cls.id: cls for cls in (CiscoIOS, EOS, ArubaCX, JunosELS, ExtremeEXOS, DellOS10, JetStream, NXOS)}


def get_driver(driver_id):
    try: return DRIVERS[driver_id]()
    except KeyError: raise ValueError(f"Unsupported platform: {driver_id}") from None


def identify(output):
    matches = [cls() for cls in DRIVERS.values() if cls().matches(output)]
    if len(matches) > 1: raise ValueError("Ambiguous platform identity. Select a platform explicitly.")
    return matches[0] if matches else None
