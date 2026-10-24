"""Independent native peers with numeric cases a browser must not re-encode."""

from bacpypes3.basetypes import (
    LogDataLogData,
    NotificationParameters,
    NotificationParametersOutOfRange,
)
from bacpypes3.local.device import DeviceObject
from bacpypes3.local.networkport import NetworkPortObject

from .test_bacnet_event_log import device as event_device
from .test_bacnet_event_log import notification
from .test_bacnet_event_log import record as event_record
from .test_bacnet_history import HistoryDevice, log
from .test_bacnet_history_multiple import device as multiple_device
from .test_bacnet_history_multiple import record as multiple_record

NUMBERS = (2.0, -0.0, 1e-7, 1e20)
PROFILES = {
    "history": ("trend-log,1", "device,4190101"),
    "history-multiple": ("trend-log-multiple,1", "device,4190102"),
    "event-log": ("event-log,1", "device,4190103"),
}


def numeric_peer(profile, port):
    if profile == "history":
        server = HistoryDevice.from_object_list(
            [
                DeviceObject(
                    objectIdentifier=("device", 4190101), objectName="Authored numeric log"
                ),
                NetworkPortObject(
                    f"127.0.0.1:{port}",
                    objectIdentifier=("network-port", 1),
                    objectName="Authored numeric loopback",
                ),
            ]
        )
        server.setup([log(value) for value in NUMBERS])
    elif profile == "history-multiple":
        server = multiple_device(port)
        server.history.logDeviceObjectProperty = server.history.logDeviceObjectProperty[:1]
        server.history.logBuffer = [
            multiple_record(values=[LogDataLogData(realValue=value)]) for value in NUMBERS
        ]
    else:
        assert profile == "event-log"
        server = event_device(port)
        server.history.logBuffer = [
            event_record(
                value=notification(
                    eventValues=NotificationParameters(
                        outOfRange=NotificationParametersOutOfRange(
                            exceedingValue=value,
                            statusFlags=[1, 0, 0, 0],
                            deadband=2.0,
                            exceededLimit=80.0,
                        )
                    )
                )
            )
            for value in NUMBERS
        ] + [event_record("timeChange", -0.0)]
    count = len(server.history.logBuffer)
    server.history.recordCount = count
    server.history.totalRecordCount = 100 + count - 1
    server.sequences = list(range(100, 100 + count))
    return server
