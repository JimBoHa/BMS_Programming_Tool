"""ReadProperty with explicit response identity and transaction retirement.

BACpypes3's convenience coroutine drops its application future on cancellation,
but its client state machine can continue retransmitting. Keep the exact
request identity so a caller's timeout retires only that exchange.
"""

from bacpypes3.apdu import ErrorRejectAbortNack, ReadPropertyACK, ReadPropertyRequest
from bacpypes3.appservice import COMPLETED
from bacpypes3.constructeddata import Array
from bacpypes3.errors import InvalidTag
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Atomic, ObjectIdentifier, PropertyIdentifier, Unsigned

from .bacnet_exchange import confirmed_exchange


async def read_property(app, address, object_id, property_id, array_index=None):
    target = Address(address) if isinstance(address, str) else address
    vendor = await app.get_vendor_info(device_address=target)
    identifier = (
        await app.parse_object_identifier(object_id, vendor_info=vendor)
        if isinstance(object_id, str)
        else ObjectIdentifier(object_id)
    )
    if isinstance(property_id, str):
        reference = await app.parse_property_reference(property_id, vendor_info=vendor)
        prop = reference.propertyIdentifier
        if reference.propertyArrayIndex is not None:
            if array_index is not None:
                raise ValueError("Array index conflict.")
            array_index = reference.propertyArrayIndex
    else:
        prop = PropertyIdentifier(property_id)
    request = ReadPropertyRequest(
        objectIdentifier=identifier,
        propertyIdentifier=prop,
        destination=target,
    )
    if array_index is not None:
        request.propertyArrayIndex = array_index
    try:
        reply = await confirmed_exchange(app, request)
        if isinstance(reply, ErrorRejectAbortNack):
            raise ValueError("BACnet read rejected: " + str(reply))
        wildcard_device = int(identifier[0]) == 8 and identifier[1] == 4194303
        if (
            not isinstance(reply, ReadPropertyACK)
            or reply.pduSource != target
            or (
                reply.objectIdentifier != identifier
                and not (
                    wildcard_device
                    and int(reply.objectIdentifier[0]) == 8
                    and 0 <= reply.objectIdentifier[1] <= 4194302
                )
            )
            or reply.propertyIdentifier != prop
            or reply.propertyArrayIndex != array_index
        ):
            raise ValueError("BACnet ReadProperty acknowledgement identity/property mismatch.")
        object_class = vendor.get_object_class(identifier[0])
        if object_class is None:
            raise ValueError("BACnet read rejected: -no object class-")
        datatype = object_class.get_property_type(prop)
        if datatype is None:
            raise ValueError("BACnet read rejected: -no property type-")
        if issubclass(datatype, Array) and array_index is not None:
            datatype = Unsigned if array_index == 0 else datatype._subtype
        value = reply.propertyValue.cast_out(datatype, null=issubclass(datatype, Atomic))
        if (
            int(identifier[0]) == 8
            and str(prop) == "object-identifier"
            and value != reply.objectIdentifier
        ):
            raise ValueError("BACnet Device identifier value differs from the acknowledged object.")
        return value
    except ErrorRejectAbortNack as exc:
        raise ValueError("BACnet read rejected: " + str(exc)) from exc
    except (InvalidTag, TypeError, AttributeError) as exc:
        raise ValueError("Malformed BACnet property value: " + str(exc)) from exc


def close_application(app):
    """Retire exchanges owned by this interface before closing its sockets."""
    service = getattr(app, "asap", None)
    for name in ("clientTransactions", "serverTransactions"):
        for transaction in list(getattr(service, name, ())):
            transaction.set_state(COMPLETED)
    for requests in list(getattr(app, "_requests", {}).values()):
        for request, future in list(requests):
            future.cancel()
            app._request_done(request, future)
    for collection in (
        getattr(app, "_who_is_futures", ()),
        getattr(getattr(app, "nse", None), "who_is_router_to_network_futures", ()),
        getattr(getattr(app, "nse", None), "initialize_routing_table_futures", ()),
    ):
        for observer in list(collection):
            observer.future.cancel()
    app.close()
