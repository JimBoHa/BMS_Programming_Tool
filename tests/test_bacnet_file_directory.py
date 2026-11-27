"""Read a large, synthetic BACnet object directory through an actual UDP peer."""

import hashlib
import json

import pytest
from bacpypes3.local.device import ArrayOfObjectIdentifier
from bacpypes3.primitivedata import ObjectIdentifier

from .test_bacnet_files import link as link


def directory(server, monkeypatch):
    server.device_object.configurationFiles = []
    identifiers = list(server.objectIdentifier) + [ObjectIdentifier((2, i)) for i in range(98)]
    monkeypatch.setattr(
        type(server.device_object),
        "objectList",
        property(lambda _: ArrayOfObjectIdentifier(identifiers)),
    )
    return identifiers


async def test_directory_reads_every_index_and_retains_the_exact_file_capture(link, monkeypatch):
    server, _, files, target = link
    ids = directory(server, monkeypatch)
    files.operation_timeout = 12
    pages = []
    handler = server.do_ReadPropertyMultipleRequest

    async def track(request):
        (access,) = request.listOfReadAccessSpecs
        assert access.objectIdentifier == server.device_object.objectIdentifier
        assert all(
            str(p.propertyIdentifier) == "object-list" for p in access.listOfPropertyReferences
        )
        pages.append([int(p.propertyArrayIndex) for p in access.listOfPropertyReferences])
        await handler(request)

    monkeypatch.setattr(server, "do_ReadPropertyMultipleRequest", track)
    inspection = await files.inspect_config(**target)
    assert inspection["advertised_files"] == ["file,31", "file,32"]
    assert inspection["object_list_count"] == len(ids)
    expected_hash = hashlib.sha256(
        json.dumps([str(v) for v in ids], separators=(",", ":")).encode()
    ).hexdigest()
    assert inspection["object_list_sha256"] == expected_hash
    assert [i for page in pages for i in page] == list(range(1, len(ids) + 1)) * 2
    assert all(1 <= len(page) <= 20 for page in pages) and len(pages) < len(ids)
    chosen = inspection["files"][0]
    receipt = await files.read_raw_file(
        inspection["id"], chosen["object_id"], chosen["metadata_sha256"]
    )
    assert files.capture_data(receipt["id"])[1] == server.payload
    assert [i for page in pages for i in page] == list(range(1, len(ids) + 1)) * 4


async def test_directory_rejection_preserves_existing_single_index_support(link, monkeypatch):
    from bacpypes3.apdu import RejectPDU

    server, _, files, target = link
    ids = directory(server, monkeypatch)
    files.operation_timeout = 12
    rejected = []

    async def unsupported(request):
        rejected.append(request.apduInvokeID)
        await server.response(RejectPDU(reason="unrecognized-service", context=request))

    monkeypatch.setattr(server, "do_ReadPropertyMultipleRequest", unsupported)
    inspection = await files.inspect_config(**target)
    assert inspection["object_list_count"] == len(ids)
    assert inspection["advertised_files"] == ["file,31", "file,32"]
    assert len(rejected) == 1
    singles = [i for prop, i in server.property_requests if prop == "object-list" and i]
    assert singles == list(range(1, len(ids) + 1)) * 2


async def test_wrong_batch_index_cannot_supply_file_membership(link, monkeypatch):
    server, _, files, target = link
    directory(server, monkeypatch)
    files.operation_timeout = 12
    handler = server.do_ReadPropertyMultipleRequest

    async def wrong_index(request):
        refs = request.listOfReadAccessSpecs[0].listOfPropertyReferences
        refs[0].propertyArrayIndex = int(refs[1].propertyArrayIndex)
        await handler(request)

    monkeypatch.setattr(server, "do_ReadPropertyMultipleRequest", wrong_index)
    with pytest.raises(ValueError, match="property/index identity mismatch"):
        await files.inspect_config(**target)
    assert not server.atomic_requests


@pytest.mark.parametrize("permitted", [True, False], ids=["optional-service", "read-denied"])
async def test_per_element_service_limits_and_access_errors(link, monkeypatch, permitted):
    from bacpypes3.apdu import ReadPropertyMultipleACK
    from bacpypes3.basetypes import ErrorType, ReadAccessResultElementChoice

    server, _, files, target = link
    ids = directory(server, monkeypatch)
    files.operation_timeout = 12
    respond = server.response
    rejected = []

    async def reject_element(reply):
        if isinstance(reply, ReadPropertyMultipleACK):
            entry = reply.listOfReadAccessResults[0].listOfResults[1]
            rejected.append(int(entry.propertyArrayIndex))
            error = (
                ErrorType(errorClass="services", errorCode="optionalFunctionalityNotSupported")
                if permitted
                else ErrorType(errorClass="property", errorCode="readAccessDenied")
            )
            entry.readResult = ReadAccessResultElementChoice(propertyAccessError=error)
        await respond(reply)

    monkeypatch.setattr(server, "response", reject_element)
    if not permitted:
        with pytest.raises(ValueError, match="read-access-denied"):
            await files.inspect_config(**target)
        assert [i for p, i in server.property_requests if p == "object-list" and i] == []
        assert not server.atomic_requests
        return
    result = await files.inspect_config(**target)
    assert rejected == [2] and result["object_list_count"] == len(ids)
    assert result["advertised_files"] == ["file,31", "file,32"]
    singles = [i for prop, i in server.property_requests if prop == "object-list" and i]
    assert singles[0] == 2 and singles[-len(ids) :] == list(range(1, len(ids) + 1))


async def test_duplicates_across_pages_reject_the_inventory(link, monkeypatch):
    server, _, files, target = link
    ids = directory(server, monkeypatch)
    ids[-1] = ids[0]
    with pytest.raises(ValueError, match="duplicate object identifiers"):
        await files.inspect_config(**target)
    assert not server.atomic_requests and not files.captures()
