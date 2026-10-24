"""Owned authored loopback BACnet peer; no site addresses or product overlays."""

# ruff: noqa: E402, I001 -- verify isolated roots/payload before importing application/test recipes.

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

# -I -S makes target and dependency admission explicit; no .pth or PYTHONPATH.
assert sys.flags.isolated and sys.flags.no_site
helper = Path(os.environ['BMS_MODEL_HELPER_ROOT']).resolve()
expected = Path(os.environ['BMS_MODEL_EXPECTED_ROOT']).resolve()
dependency = Path(os.environ['BMS_MODEL_DEPENDENCY_ROOT']).resolve()
assert dependency.is_dir() and expected.is_dir()
assert not Path.cwd().resolve().is_relative_to(helper)
sys.path[:0] = [str(expected), str(dependency)]
installed = bool(os.environ.get('BMS_TEST_INSTALLED_TARGET'))
manifest = None
if installed:
    assert expected == Path(os.environ['BMS_TEST_INSTALLED_TARGET']).resolve()
    manifest = json.loads(Path(os.environ['BMS_TEST_INSTALLED_MANIFEST']).read_text())
    assert Path(manifest['target']).resolve() == expected
    assert manifest['source_commit'] == os.environ['BMS_EXPECTED_SOURCE']
    assert len(manifest['wheel_sha256']) == 64


def check_payload():
    if manifest:
        for member, digest in manifest['payload'].items():
            path = expected / member
            assert path.resolve().is_relative_to(expected)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, member
        for member, digest in manifest['ui_files'].items():
            assert hashlib.sha256((expected / 'bms_tool/web_assets' / member).read_bytes()).hexdigest() == digest


check_payload()
import bms_tool
from bms_tool import resources
from bms_tool.bacnet_read import close_application
from bacpypes3.object import AnalogInputObject

assert Path(bms_tool.__file__).resolve().is_relative_to(expected)
if installed:
    assert not resources.source_checkout()
    assert resources.web_directory().is_relative_to(expected)
    distribution = json.loads((expected / 'bms_tool/data/distribution.json').read_text())
    if source := os.environ.get('BMS_EXPECTED_SOURCE'):
        assert distribution['source_commit'] == source
for name in ('tests/test_connections.py', 'tests/test_model_transport_routed.py'):
    assert (helper / name).is_file()
sys.path.append(str(helper))  # Test recipes only; expected backend root already wins.
from tests.test_connections import application, free_udp
from tests.test_model_transport_routed import RoutedProxy
import tests.test_connections as connections_recipe
import tests.test_model_transport_routed as routed_recipe
assert Path(connections_recipe.__file__).resolve() == helper / 'tests/test_connections.py'
assert Path(routed_recipe.__file__).resolve() == helper / 'tests/test_model_transport_routed.py'


def identity(phase):
    check_payload()
    modules = {}
    for name, module in tuple(sys.modules.items()):
        if name == 'bms_tool' or name.startswith('bms_tool.'):
            path = Path(module.__file__).resolve()
            assert path.is_relative_to(expected), name
            if manifest:
                assert str(path.relative_to(expected)) in manifest['payload'], name
            modules[name] = str(path)
    return {
        'phase': phase, 'mode': 'installed' if installed else 'source',
        'isolated': bool(sys.flags.isolated), 'no_site': bool(sys.flags.no_site),
        'source_checkout': bool(resources.source_checkout()),
        'package': str(Path(bms_tool.__file__).resolve()),
        'web': str(resources.web_directory()), 'loaded_modules': modules,
        'target': str(expected), 'helper_root': str(helper),
        'working_directory': str(Path.cwd().resolve()),
        'payload_count': len(manifest['payload']) if manifest else None,
        'wheel_sha256': manifest['wheel_sha256'] if manifest else None,
        'source_commit': manifest['source_commit'] if manifest else None,
    }


def exclusive(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


async def main():
    port = free_udp()
    peer = application(port, 4190123)
    peer.device_object.modelName = sys.argv[1]
    peer.add_object(AnalogInputObject(
        objectIdentifier=('analog-input', 31), objectName='Authored loopback temperature',
        deviceType='UI IN1', presentValue=72.5, units='degrees-fahrenheit',
        reliability='no-fault-detected', statusFlags=[0, 0, 0, 0], outOfService=False,
    ))
    calls = []
    for name in ('do_ReadPropertyRequest', 'do_ReadPropertyMultipleRequest'):
        original = getattr(peer, name)

        async def tracking(request, original=original, name=name):
            calls.append(name)
            return await original(request)

        setattr(peer, name, tracking)
    proxy = transport = ready = None
    try:
        if sys.argv[2] == 'routed':
            transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: RoutedProxy(('127.0.0.1', port)), local_addr=('127.0.0.1', 0)
            )
        ready = {
            'address': f'127.0.0.1:{port}', 'device': 'device,4190123',
            'client_address': f'127.0.0.1:{free_udp()}',
            'router': proxy.endpoint if proxy else None,
            'package': str(Path(bms_tool.__file__).resolve()),
            'source_checkout': bool(resources.source_checkout()),
            'helper_root': str(helper),
            'helper_sha256': {name: hashlib.sha256((helper / name).read_bytes()).hexdigest() for name in ('tests/test_connections.py', 'tests/test_model_transport_routed.py')},
        }
        exclusive(os.environ['BMS_MODEL_IDENTITY'], identity('startup'))
        print('MODEL_TRANSPORT_PEER=' + json.dumps(ready), flush=True)
        await asyncio.to_thread(sys.stdin.readline)
    finally:
        if transport:
            transport.close()
        close_application(peer)
        await asyncio.sleep(0.02)
        evidence = {
            'ready': ready, 'native_reads': calls,
            'routed_requests': proxy.requests if proxy else [],
            'routed_responses': proxy.responses if proxy else [],
            'proxy_errors': proxy.errors if proxy else [],
            'pending_proxy_clients': len(proxy.clients) if proxy else 0,
            'qualification': 'Actual local UDP BACnet services and original routed envelopes; authored peer, no physical MS/TP/controller acceptance.',
        }
        Path(os.environ['BMS_MODEL_EVIDENCE']).write_text(json.dumps(evidence, indent=2) + '\n')
        exclusive(os.environ['BMS_MODEL_IDENTITY'] + '.post.json', identity('post_shutdown'))


asyncio.run(main())
