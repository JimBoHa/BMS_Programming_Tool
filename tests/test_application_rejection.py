from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from bacpypes3.apdu import Error, SimpleAckPDU, WritePropertyMultipleError, WritePropertyRequest
from bacpypes3.basetypes import ErrorType, ObjectPropertyReference
from bacpypes3.constructeddata import Any
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Real
from bms_tool.application_files import ApplicationFiles, rejection_text


def multiple_error():
    return WritePropertyMultipleError(
        errorType=ErrorType(errorClass="property", errorCode="write-access-denied"),
        firstFailedWriteAttempt=ObjectPropertyReference(
            objectIdentifier=(631, 42), propertyIdentifier=3887
        ),
    )


@pytest.mark.parametrize("returned", [False, True])
async def test_complex_rejection_preserves_the_protocol_cause_instead_of_formatter_failure(
    monkeypatch, returned
):
    error = multiple_error()
    with pytest.raises(AttributeError):
        str(error)
    session = {"app": object(), "target": Address("100:7")}
    requests = []

    async def exchange(app, request, **kwargs):
        requests.append(request)
        if returned:
            return error
        raise error

    @asynccontextmanager
    async def receive(session, request):
        yield {}

    monkeypatch.setattr("bms_tool.application_files.confirmed_exchange", exchange)
    files = ApplicationFiles(SimpleNamespace(_guard=lambda session: None), writable_files={3})
    files.wire = SimpleNamespace(receive=receive, validate=lambda *args: {})
    request = WritePropertyRequest(
        objectIdentifier=(2, 10), propertyIdentifier=85, propertyValue=Any(Real(1))
    )
    with pytest.raises(ValueError, match="property: write-access-denied") as caught:
        await files.exchange(session, request, SimpleAckPDU)
    assert caught.value.__cause__ is error
    assert len(requests) == 1


def test_simple_error_retains_its_class_and_code():
    error = Error(service_choice=15, errorClass="property", errorCode="unknown-property")
    assert rejection_text(error) == "property: unknown-property"


def test_unknown_broken_formatter_still_has_a_bounded_diagnostic():
    class Broken(Exception):
        def __str__(self):
            raise AttributeError("missing vendor field")

    assert rejection_text(Broken()) == "Broken"
