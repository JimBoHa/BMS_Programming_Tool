"""Native NAE HTTPS/SOAP authentication and bounded engineering reads.

The peer is the engine itself. No JCT/SCT API, executable or SDK is used.
This transport admits no configuration mutation, command or restore method.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import re
import secrets
import ssl
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import httpx
from defusedxml.ElementTree import fromstring
from defusedxml.minidom import parseString

SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
LOGIN_NS = "http://johnsoncontrols.com/MetasysIII/WebServices/Security/LoginService/"
SUPPORT_NS = "http://johnsoncontrols.com/MetasysIII/WebServices/Item/Support"
NAV_NS = "http://johnsoncontrols.com/MetasysIII/WebServices/Item/MonitoringAndCommanding"
INTEGRATION_NS = "http://johnsoncontrols.com/MetasysIII/WebServices/Integration"
BASE = "/MetasysIII/WS/"
MAX_RESPONSE = 4 * 1024 * 1024
READS = {
    ("Item/Support.asmx", "GetConfigView"): SUPPORT_NS,
    ("Item/Support.asmx", "GetPropertyList"): SUPPORT_NS,
    ("Item/Support.asmx", "GetClassInfo"): SUPPORT_NS,
    ("Item/MonitoringAndCommanding.asmx", "GetNavView"): NAV_NS,
    ("Item/MonitoringAndCommanding.asmx", "GetViewList"): NAV_NS,
    ("Item/MonitoringAndCommanding.asmx", "GetView"): NAV_NS,
    ("Item/MonitoringAndCommanding.asmx", "ReadPropertyMultiple"): NAV_NS,
    ("Integration/Integration.asmx", "GetEngView"): INTEGRATION_NS,
}


class NaeSoapError(ValueError):
    pass


def native_origin(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or "\\" in value
    ):
        raise ValueError("Use an explicit native-engine HTTPS origin without paths or credentials.")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid native-engine HTTPS port.")
    return str(httpx.URL(value)).rstrip("/")


class NaeHttps:
    def __init__(self, origin, client):
        self.origin = native_origin(origin)
        if str(client.base_url).rstrip("/") != self.origin:
            raise ValueError("Native HTTPS transport differs from the selected engine.")
        self.client = client
        self.header = None
        self.account = None
        self.generation = None
        self.lock = asyncio.Lock()

    def __repr__(self):
        return f"NaeHttps(authenticated={self.header is not None})"

    @classmethod
    async def connect(cls, origin, fingerprint, *, username, password):
        origin = native_origin(origin)
        if type(fingerprint) is not str or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("A trusted native-engine SHA-256 certificate fingerprint is required.")
        address = urlsplit(origin)
        pem = await asyncio.to_thread(
            ssl.get_server_certificate, (address.hostname, address.port or 443), timeout=5
        )
        if not secrets.compare_digest(
            hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest(), fingerprint
        ):
            raise ValueError("The native engine certificate changed; credentials were not sent.")
        context = ssl.create_default_context(cadata=pem)
        # The explicit leaf pin binds this exact selected origin, including NAE
        # self-signed certificates whose name does not include an IP SAN.
        context.check_hostname = False
        client = httpx.AsyncClient(
            base_url=origin,
            verify=context,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(8, connect=5),
        )
        instance = cls(origin, client)
        try:
            await instance.login(username=username, password=password)
            return instance
        except BaseException:
            await client.aclose()
            raise

    async def _request(self, endpoint, method, namespace, fields=(), *, authenticated=True):
        if (
            authenticated
            and (endpoint, method) not in READS
            and (endpoint, method) != ("Security/LoginService.asmx", "Logout")
        ):
            raise ValueError("Native HTTPS profile does not admit this operation.")
        if not authenticated and (endpoint, method) != (
            "Security/LoginService.asmx",
            "LoginOverSecureConnection",
        ):
            raise ValueError("Native HTTPS profile does not admit this unauthenticated operation.")
        if namespace != (
            LOGIN_NS if endpoint == "Security/LoginService.asmx" else READS.get((endpoint, method))
        ):
            raise ValueError("Native HTTPS operation namespace changed.")
        if authenticated and self.header is None:
            raise ValueError("Sign in to the selected NAE explicitly first.")
        header_bytes = b""
        if authenticated:
            header = self.header.cloneNode(True)
            header.ownerDocument.renameNode(header, namespace, "LoginResult")
            header.setAttribute("xmlns", namespace)
            header_bytes = b"<soap:Header>" + header.toxml(encoding="utf-8") + b"</soap:Header>"
        action = ET.Element(method, {"xmlns": namespace})
        for key, value in fields:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key):
                raise ValueError("Invalid native SOAP parameter name.")
            element = ET.SubElement(action, key)
            if isinstance(value, ET.Element):
                if method == "ReadPropertyMultiple" and key == value.tag == "readRequest":
                    # This parameter is a typed WSDL structure, unlike the
                    # XmlElement credential payload wrapped by the data field.
                    action.remove(element)
                    action.append(copy.deepcopy(value))
                else:
                    element.append(copy.deepcopy(value))
            elif type(value) is bool:
                element.text = "true" if value else "false"
            else:
                element.text = str(value)
        payload = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            + ('<soap:Envelope xmlns:soap="' + SOAP + '">').encode()
            + header_bytes
            + b"<soap:Body>"
            + ET.tostring(action, encoding="utf-8")
            + b"</soap:Body></soap:Envelope>"
        )
        if len(payload) > 65536:
            raise ValueError("Native SOAP request exceeds its byte budget.")
        path = BASE + endpoint
        peer = urlsplit(self.origin)
        host = "[" + peer.hostname + "]" if ":" in peer.hostname else peer.hostname
        request = self.client.build_request(
            "POST",
            path,
            content=payload,
            headers={
                "POST": path,
                "Host": host + ":" + str(peer.port or 443),
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": '"' + namespace.rstrip("/") + "/" + method + '"',
                "Connection": "close",
                "User-Agent": "BMS-Studio/native-engine",
            },
        )
        request.headers.pop("accept-encoding", None)
        async with asyncio.timeout(12):
            reply = await self.client.send(request, stream=True)
            try:
                raw = bytearray()
                async for block in reply.aiter_bytes():
                    if len(raw) + len(block) > MAX_RESPONSE:
                        raise NaeSoapError("Native engine response exceeded its byte budget.")
                    raw.extend(block)
                try:
                    document = fromstring(
                        raw, forbid_dtd=True, forbid_entities=True, forbid_external=True
                    )
                except Exception:
                    raise NaeSoapError(
                        "Native engine returned an invalid bounded SOAP response."
                    ) from None
                if document.tag != "{" + SOAP + "}Envelope":
                    raise NaeSoapError("Native response is not a SOAP 1.1 envelope.")
                bodies = document.findall("{" + SOAP + "}Body")
                if len(bodies) != 1 or len(bodies[0]) != 1:
                    raise NaeSoapError("Native SOAP response has ambiguous body framing.")
                result = bodies[0][0]
                if result.tag == "{" + SOAP + "}Fault":
                    # Never reflect arbitrary server text that could echo the
                    # supplied password, username, credential XML or token.
                    message = " ".join(result.itertext())
                    if "Invalid Credentials" in message:
                        raise NaeSoapError("The native NAE rejected this account.")
                    raise NaeSoapError("The native NAE refused this SOAP operation.")
                if (
                    reply.status_code != 200
                    or result.tag != "{" + namespace + "}" + method + "Response"
                ):
                    raise NaeSoapError("Native SOAP response differs from its requested operation.")
                return result, bytes(raw)
            finally:
                await reply.aclose()

    async def login(self, *, username, password):
        if (
            type(username) is not str
            or not 1 <= len(username) <= 200
            or type(password) is not str
            or not 1 <= len(password) <= 1000
            or any(c in username + password for c in "\x00\r\n")
        ):
            raise ValueError("Explicit existing native-engine credentials are required.")
        async with self.lock:
            if self.header is not None:
                raise ValueError("Close the current native-engine session before signing in again.")
            node = ET.Element("Credentials", {"xmlns": LOGIN_NS})
            for key, value in (
                ("UserName", username),
                ("Password", password),
                ("Domain", "Metasys Local"),
                ("IsPasswordEncrypted", "false"),
            ):
                ET.SubElement(node, key).text = value
            try:
                result, raw = await self._request(
                    "Security/LoginService.asmx",
                    "LoginOverSecureConnection",
                    LOGIN_NS,
                    [("data", node)],
                    authenticated=False,
                )
            finally:
                for element in node.iter():
                    element.text = None
            items = list(result)
            if (
                len(items) != 1
                or items[0].tag.rsplit("}", 1)[-1] != "LoginOverSecureConnectionResult"
            ):
                raise NaeSoapError("Native login did not supply an explicit result.")
            candidate = items[0]
            tokens = [e for e in candidate.iter() if e.tag.rsplit("}", 1)[-1] == "securityToken"]
            names = [e.text for e in candidate.iter() if e.tag.rsplit("}", 1)[-1] == "UserName"]
            if (
                len(tokens) != 1
                or not (len(tokens[0]) or tokens[0].text)
                or len(names) != 1
                or str(names[0]).casefold() != username.casefold()
            ):
                raise NaeSoapError(
                    "Native login identity/token structure is unsupported; no read authority was granted."
                )
            dom = parseString(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
            nodes = [n for n in dom.getElementsByTagNameNS("*", "LoginOverSecureConnectionResult")]
            if len(nodes) != 1:
                raise NaeSoapError("Native login result framing is ambiguous.")
            original = nodes[0]
            self.header = original.cloneNode(True)
            # Carry original namespace bindings and prefixes for opaque token
            # content. Re-encoding it with arbitrary new prefixes can invalidate
            # native token signatures or older engine parsers.
            current = original
            while current is not None and getattr(current, "attributes", None) is not None:
                for index in range(current.attributes.length):
                    attr = current.attributes.item(index)
                    if (
                        attr.name == "xmlns" or attr.name.startswith("xmlns:")
                    ) and not self.header.hasAttribute(attr.name):
                        self.header.setAttribute(attr.name, attr.value)
                current = current.parentNode
            self.account, self.generation = username, secrets.token_hex(16)
            return {
                "authenticated": True,
                "account": username,
                "origin": self.origin,
                "peer": "native-nae-https",
                "jct_sct_required": False,
                "configuration_write_available": False,
            }

    async def config_view(self, reference, class_id, class_version):
        """Read a creation/configuration definition, including DEFAULT values.

        This is not a capture of the referenced object's current settings.
        Use native object views for current values and independent readback.
        """
        if (
            type(reference) is not str
            or not 1 <= len(reference) <= 512
            or any(c in reference for c in "\x00\r\n")
        ):
            raise ValueError("Use the exact native engine reference.")
        if (
            type(class_id) is not int
            or not 1 <= class_id <= 65535
            or type(class_version) is not str
            or not re.fullmatch(r"\d{1,3}\.\d{1,3}", class_version)
        ):
            raise ValueError("Use the exact native class identifier/version.")
        async with self.lock:
            result, _ = await self._request(
                "Item/Support.asmx",
                "GetConfigView",
                SUPPORT_NS,
                [("reference", reference), ("classID", class_id), ("classVersion", class_version)],
            )
            return result

    @staticmethod
    def _reference(reference, *, root=False):
        if (
            type(reference) is not str
            or not (0 if root else 1) <= len(reference) <= 512
            or any(c in reference for c in "\x00\r\n")
        ):
            raise ValueError("Use the exact native engine reference.")

    async def navigation(self, reference="", *, depth=1, extensions=False):
        self._reference(reference, root=True)
        if type(depth) is not int or not 0 <= depth <= 2 or type(extensions) is not bool:
            raise ValueError("Use a bounded native hierarchy read.")
        async with self.lock:
            result, _ = await self._request(
                "Item/MonitoringAndCommanding.asmx",
                "GetNavView",
                NAV_NS,
                [
                    ("reference", reference),
                    ("viewType", "Hardware"),
                    ("viewId", 0),
                    ("recursiveDepth", depth),
                    ("includeExtensions", extensions),
                    ("classId", -1),
                    ("classVersion", "1"),
                ],
            )
            # classId is a descendant-class FILTER, not selected-object identity.
            # -1 requests unfiltered children; identity comes from response nodes.
            return result

    async def views(self, reference, *, edit_mode=False):
        self._reference(reference)
        if type(edit_mode) is not bool:
            raise ValueError("Use an explicit native view mode.")
        async with self.lock:
            result, _ = await self._request(
                "Item/MonitoringAndCommanding.asmx",
                "GetViewList",
                NAV_NS,
                [
                    ("reference", reference),
                    ("activeViewsOnly", True),
                    ("returnDefaultView", False),
                    ("editMode", edit_mode),
                    ("useDictionary", False),
                ],
            )
            return result

    async def view(self, reference, view_id, *, edit_mode=False):
        self._reference(reference)
        if type(view_id) is not int or not 0 <= view_id <= 65535 or type(edit_mode) is not bool:
            raise ValueError("Use a discovered native view identifier and explicit view mode.")
        async with self.lock:
            result, _ = await self._request(
                "Item/MonitoringAndCommanding.asmx",
                "GetView",
                NAV_NS,
                [
                    ("reference", reference),
                    ("viewId", view_id),
                    ("editMode", edit_mode),
                    ("useDictionary", False),
                ],
            )
            return result

    async def engineering_view(self, reference):
        self._reference(reference)
        async with self.lock:
            result, _ = await self._request(
                "Integration/Integration.asmx",
                "GetEngView",
                INTEGRATION_NS,
                [("reference", reference), ("engParam1", 0), ("engParam2", 0), ("engParam3", "")],
            )
            return result

    async def read_properties(self, reference, properties):
        self._reference(reference)
        if (
            type(properties) is not list
            or not 1 <= len(properties) <= 64
            or any(type(p) is not int or not 0 <= p <= 65535 for p in properties)
            or len(set(properties)) != len(properties)
        ):
            raise ValueError("Use a bounded distinct list of native property identifiers.")
        request = ET.Element("readRequest", {"useDictionary": "false"})
        items = ET.SubElement(request, "items")
        ET.SubElement(
            items,
            "item",
            {
                "reference": reference,
                "propertyList": " ".join(str(p) for p in properties),
            },
        )
        async with self.lock:
            result, _ = await self._request(
                "Item/MonitoringAndCommanding.asmx",
                "ReadPropertyMultiple",
                NAV_NS,
                [("reference", reference), ("readRequest", request)],
            )
            return result

    async def close(self):
        async with self.lock:
            try:
                if self.header is not None:
                    await self._request("Security/LoginService.asmx", "Logout", LOGIN_NS)
            finally:
                self.header, self.account, self.generation = None, None, None
                await self.client.aclose()
