"""Typed WriteProperty with an owned dispatch and transaction lifetime.

BACpypes3 0.0.110's convenience call schedules dispatch independently and leaves
the client state machine retrying after its application future is cancelled.
An uncertain command must remain journalled, but must not keep being transmitted
after the operator's operation has returned. This helper owns both lifetimes.
"""

from bacpypes3.apdu import ErrorRejectAbortNack, SimpleAckPDU, WritePropertyRequest
from bacpypes3.constructeddata import Array
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Null, ObjectIdentifier, PropertyIdentifier, Unsigned

from .bacnet_exchange import confirmed_exchange


async def write_property(app, address, object_id, property_id, value, *, priority=None):
    target = Address(address) if isinstance(address, str) else address
    vendor = await app.get_vendor_info(device_address=target)
    identifier = (
        await app.parse_object_identifier(object_id, vendor_info=vendor)
        if isinstance(object_id, str)
        else ObjectIdentifier(object_id)
    )
    array_index = None
    if isinstance(property_id, str):
        reference = await app.parse_property_reference(property_id, vendor_info=vendor)
        prop = reference.propertyIdentifier
        array_index = reference.propertyArrayIndex
    else:
        prop = PropertyIdentifier(property_id)
    object_class = vendor.get_object_class(identifier[0])
    if object_class is None:
        raise ValueError("BACnet write rejected: no known object class.")
    datatype = object_class.get_property_type(prop)
    if datatype is None:
        raise ValueError("BACnet write rejected: no known property type.")
    if issubclass(datatype, Array) and array_index is not None:
        datatype = Unsigned if array_index == 0 else datatype._subtype
    if not ((priority is not None) and isinstance(value, Null)) and not isinstance(value, datatype):
        value = datatype(value)
    request = WritePropertyRequest(
        objectIdentifier=identifier,
        propertyIdentifier=prop,
        propertyValue=value,
        destination=target,
    )
    if array_index is not None:
        request.propertyArrayIndex = array_index
    if priority is not None:
        request.priority = priority

    try:
        reply = await confirmed_exchange(app, request)
        if isinstance(reply, ErrorRejectAbortNack):
            raise ValueError("BACnet write rejected: " + str(reply))
        if (
            not isinstance(reply, SimpleAckPDU)
            or reply.pduSource != target
            or reply.apduInvokeID != request.apduInvokeID
            or reply.apduService != request.apduService
        ):
            raise ValueError("BACnet WriteProperty acknowledgement identity/service mismatch.")
    except ErrorRejectAbortNack as exc:
        raise ValueError("BACnet write rejected: " + str(exc)) from exc
