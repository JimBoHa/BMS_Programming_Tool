"""Explicit authenticated JCT archive reads, separate from online field authority.

Uses the installed configuration service's archive API. An archive object GUID
is scoped to that archive; it is not silently substituted for an online GUID.
This first connection profile exposes no archive edits or device transfer jobs.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlencode, urlsplit

from .metasys_configuration_api import MetasysApiError, MetasysConfigurationApi, guid, origin

PROFILE = "jct-archive-connection/1"
OFFLINE_PREFIX = "/offline/api/private-api"
TOOL_PREFIX = "/tool/api/v1"


def archive_name(value):
    if (
        type(value) is not str
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,127}", value)
        or value != value.strip()
    ):
        raise ValueError("Use an explicit supported archive name without paths or query syntax.")
    return value


class JctConfigurationApi(MetasysConfigurationApi):
    prefix = OFFLINE_PREFIX
    referer_path = "/UIOffline/"

    def _admitted_path(self, method, path):
        if method == "POST":
            return path == self.prefix + "/Authentication/LogIn"
        if method != "GET":
            return False
        if path in (
            self.prefix + "/Authentication/GetPreLoginState",
            TOOL_PREFIX + "/version",
            TOOL_PREFIX + "/archives",
        ):
            return True
        archive_prefix = self.prefix + "/v5/archives/"
        if not path.startswith(archive_prefix):
            return False
        segment = path[len(archive_prefix) :].split("/", 1)[0]
        try:
            if quote(archive_name(unquote(segment)), safe="") != segment:
                return False
        except ValueError:
            return False
        return bool(
            re.fullmatch(
                re.escape(self.prefix)
                + r"/v5/archives/[A-Za-z0-9_%-]+/(?:networkDevices|objects)(?:/[0-9a-f-]{36}(?:/objects|/attributes/instanceNumber)?)?(?:\?[A-Za-z0-9%=&._-]+)?",
                path,
            )
        )

    def _archive(self, name):
        return self.prefix + "/v5/archives/" + quote(archive_name(name), safe="")

    async def tool_version(self):
        reply = await self._request("GET", TOOL_PREFIX + "/version")
        if any(
            type(reply.data.get(key)) is not int or reply.data[key] < 0
            for key in ("major", "minor", "patch", "build")
        ):
            raise MetasysApiError("Configuration service returned an invalid tool version.")
        return reply.data

    async def archives(self):
        reply = await self._request("GET", TOOL_PREFIX + "/archives")
        items = reply.data.get("items")
        if type(items) is not list or len(items) > 128:
            raise MetasysApiError("Archive inventory was absent or exceeded its limit.")
        seen = set()
        for item in items:
            if type(item) is not dict:
                raise MetasysApiError("Archive inventory contains an invalid item.")
            name = archive_name(item.get("name"))
            if name.casefold() in seen:
                raise MetasysApiError("Archive inventory contains ambiguous names.")
            seen.add(name.casefold())
        return reply.data

    async def network_devices(self, name):
        reply = await self._request("GET", self._archive(name) + "/networkDevices?pageSize=1000")
        if type(reply.data.get("items")) is not list or len(reply.data["items"]) > 1000:
            raise MetasysApiError("Archive network inventory was absent or exceeded its limit.")
        return reply.data

    async def archive_object(self, name, object_id, *, view="viewNameEnumSet.configView"):
        identifier = guid(object_id)
        if view not in (
            "viewNameEnumSet.configView",
            "viewNameEnumSet.hardwareView",
            "viewNameEnumSet.focusView",
        ):
            raise ValueError("Unsupported archive object view.")
        reply = await self._request(
            "GET",
            self._archive(name)
            + "/objects/"
            + identifier
            + "?"
            + urlencode({"viewId": view, "includeSchema": "true"}),
        )
        if guid(reply.data.get("item", {}).get("id")) != identifier:
            raise MetasysApiError("Archive object identity differs from the requested GUID.")
        return reply.data

    async def archive_children(self, name, object_id):
        reply = await self._request(
            "GET",
            self._archive(name)
            + "/objects/"
            + guid(object_id)
            + "/objects?"
            + urlencode({"depth": 1, "flatten": "true", "includeExtensions": "true"}),
        )
        if type(reply.data.get("items")) is not list:
            raise MetasysApiError("Archive children were not supplied.")
        return reply.data

    async def archive_source(self, name, object_id):
        return (
            await self._request(
                "GET",
                self._archive(name)
                + "/objects/"
                + guid(object_id)
                + "/attributes/instanceNumber?includeSchema=true",
            )
        ).data

    def archive_resource_guid(self, url, name):
        if type(url) is not str:
            raise ValueError("Missing archive resource URL.")
        parsed = urlsplit(url)
        if (
            origin(f"{parsed.scheme}://{parsed.netloc}") != self.origin
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Archive resource changed origin or includes a query.")
        match = re.fullmatch(
            re.escape(self._archive(name)) + r"/objects/([0-9a-f-]{36})", parsed.path, re.IGNORECASE
        )
        if match is None:
            raise ValueError("Archive resource differs from the selected archive or collection.")
        return guid(match[1])


def inspection_projection(document):
    """Mask credentials in a display response, including schema defaults.

    This projection is neither a native backup nor an editable document.
    """
    sensitive = re.compile(r"password|passwd|secret|token|private.?key|api.?key|credential", re.I)
    secret_fields, pending, visited = set(), [document], 0
    while pending:
        value = pending.pop()
        visited += 1
        if visited > 100000:
            raise ValueError("Archive inspection exceeds its node budget.")
        if isinstance(value, dict):
            properties = value.get("properties", {})
            if isinstance(properties, dict):
                for key, spec in properties.items():
                    if isinstance(spec, dict) and (
                        spec.get("format") == "password"
                        or str(spec.get("metasysType", "")).lower()
                        in ("password", "encryptedstring")
                    ):
                        secret_fields.add(key)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    redacted = []

    def project(value, path="", depth=0):
        if depth > 64:
            raise ValueError("Archive inspection exceeds its nesting budget.")
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                child = path + "/" + key
                if sensitive.search(key) or key in secret_fields:
                    result[key] = "[credential withheld]"
                    redacted.append(child)
                else:
                    result[key] = project(item, child, depth + 1)
            return result
        if isinstance(value, list):
            return [
                project(item, path + "/" + str(index), depth + 1)
                for index, item in enumerate(value)
            ]
        return value

    return {
        "document": project(document),
        "redacted_fields": redacted,
        "editable": False,
        "native_backup": False,
    }
