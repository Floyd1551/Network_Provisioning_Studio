"""Bounded HTTPS requests; redirects and automatic mutation retries are disabled."""
import http.cookiejar
import ipaddress
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


class HTTPS:
    simulated = False
    def __init__(self, host, port=443, ca_file=""):
        if not isinstance(host, str) or not host or any(c in host for c in "/@?#\\") or any(c.isspace() for c in host):
            raise ValueError("Enter a hostname or IP address without a URL path.")
        if not 1 <= int(port) <= 65535: raise ValueError("Invalid HTTPS port.")
        if ":" in host:
            ipaddress.IPv6Address(host); host = "[" + host + "]"
        elif not re.fullmatch(r"[A-Za-z0-9_.-]+", host): raise ValueError("Invalid hostname.")
        self.origin = f"https://{host}:{int(port)}"
        context = ssl.create_default_context(cafile=ca_file or None)
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(self.cookies))
        self.headers = {}

    def request(self, method, path, payload=None, form=None, xml=False):
        if not path.startswith("/") or path.startswith("//") or any(c in path for c in "?#\r\n"):
            raise ValueError("API paths must be fixed local paths.")
        headers = dict(self.headers)
        headers["Accept"] = "application/xml" if xml else "application/json"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8"); headers["Content-Type"] = "application/json"
        if form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8"); headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=45) as response:
                body = response.read(25_000_001)
                if len(body) > 25_000_000: raise RuntimeError("API response exceeds 25 MB; refusing a partial capture.")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"API HTTP {error.code}; check permissions, certificate and API compatibility.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError("HTTPS request failed or timed out. Verify certificate trust and reachability. A timed-out write may have applied; inspect the device before retrying.") from None
        if xml:
            if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper(): raise ValueError("Unsupported XML declarations.")
            from xml.etree import ElementTree
            try: return ElementTree.fromstring(body)
            except ElementTree.ParseError: raise ValueError("Invalid XML response.") from None
        try: result = json.loads(body)
        except (ValueError, UnicodeDecodeError): raise ValueError("Invalid JSON response.") from None
        if not isinstance(result, dict): raise ValueError("Expected an API object response.")
        return result

    def close(self): self.headers.clear(); self.cookies.clear()
