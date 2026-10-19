# MS/TP implementation and verification provenance

Recorded 2026-10-19. This notice describes the direct serial implementation and its external verification reference. It does not change the repository's Apache-2.0 license or relicense upstream material.

## Repository implementation

[mstp.py](../backend/bms_tool/mstp.py) and [mstp_bacnet.py](../backend/bms_tool/mstp_bacnet.py) are separately written Python code. They implement mathematical CRCs, bounded framing and protocol state using the published MS/TP concepts and the reference behavior described below. Upstream source was read during development; this was not a clean-room process. No upstream C source text, CRC lookup table, object file, library or executable is included in these modules or their runtime package.

The focused Python tests retain small numeric protocol check vectors and wire fixtures. The wire fixtures include authored Who-Is/I-Am and ReadProperty request/response payloads checked against a separate C encoder. They are not copied controller applications or captures of a building network. Neither the tests nor the production transport downloads, links or loads BACnet-stack C code at runtime.

Runtime imports use the existing pinned BACpypes3 and pyserial dependencies. Their installed distributions and license metadata remain separate from the BACnet-stack verification checkout. This notice does not replace those packages' own licenses.

## External reference

The primary reference was [bacnet-stack/bacnet-stack](https://github.com/bacnet-stack/bacnet-stack), pinned to revision `e295d20baba977132b47bc09f61f28e12f2dfac3`. Its source identifies Steve Karg as author of the legacy MS/TP and CRC implementation; Kerry Lynn is identified on the COBS source. The checkout, including upstream license files, remains outside this repository at `../Reference_Sources/bacnet-stack`.

| Referenced file | SHA-256 of the checked file |
|---|---|
| [`src/bacnet/datalink/mstp.c`](https://github.com/bacnet-stack/bacnet-stack/blob/e295d20baba977132b47bc09f61f28e12f2dfac3/src/bacnet/datalink/mstp.c) | `5c952c6d6a78c0f6a11ff4f2193887612a37e0ffc3b8941f04b587fb5d7bebe1` |
| [`src/bacnet/datalink/crc.c`](https://github.com/bacnet-stack/bacnet-stack/blob/e295d20baba977132b47bc09f61f28e12f2dfac3/src/bacnet/datalink/crc.c) | `cf805955b8913fedaf5d65aa1db96a0c90a5cdd2635ed36202f5136b189cb19f` |
| [`src/bacnet/datalink/cobs.c`](https://github.com/bacnet-stack/bacnet-stack/blob/e295d20baba977132b47bc09f61f28e12f2dfac3/src/bacnet/datalink/cobs.c) | `e43b1c8881848ffd10ee206b9304f0e73a0a8f124bb6b93ce85a07ccf133827b` |
| [`test/bacnet/datalink/crc/src/main.c`](https://github.com/bacnet-stack/bacnet-stack/blob/e295d20baba977132b47bc09f61f28e12f2dfac3/test/bacnet/datalink/crc/src/main.c) | `57b1906ad391d8f222f7275246d800225fad386a3516a2b6d48e5011fa9f4a50` |

The upstream test records the public BACnet Annex G header example `00 10 05 00 00`, whose transmitted CRC is `8c`, and the data example `01 22 30`, whose transmitted CRC bytes are `10 bd`. Our implementation calculates these with bit-at-a-time polynomials, rather than the upstream arithmetic expression or lookup tables. The source fixture is identified by its [MIT-labeled test file](https://github.com/bacnet-stack/bacnet-stack/blob/e295d20baba977132b47bc09f61f28e12f2dfac3/test/bacnet/datalink/crc/src/main.c).

## Independent encoding check

Two small, locally authored C wrappers called upstream `MSTP_Create_Frame` with the six data-frame payloads frozen in the Python tests. They were compiled with the unchanged pinned `mstp.c`, `crc.c` and `cobs.c`; dead stripping removed unused functions. The build used the local macOS `clang`, `-O2`, `-DBACDL_MSTP`, the upstream `src` include path, and the macOS linker option `-Wl,-dead_strip`. No upstream source was modified.

The ignored local evidence directory is `local-reports/mstp-oracle/`. It contains `frame-oracle.c`, `bacpypes-frame-oracle.c`, their local executables and these output records:

| Local result | SHA-256 |
|---|---|
| `frame-results.txt`, two ReadProperty frames | `3ed5b9030316d2bcd5eb60e98945155b70a45a74286dc666799caecf0c030346` |
| `bacpypes-frame-results.txt`, four discovery/property frames | `768dd2ee217dc2c96f9e2785bc32331d0c8c8cd0085a51c4dcb3bb3f9acbd251` |

All six encoder results exactly matched the Python fixture octets. These local C executables and the external source checkout are not committed, shipped with the application or required by its tests. The comparison verifies the selected frame encodings. The complete upstream master FSM was not run as an interoperability peer, and this check is not physical or BTL certification.

## Upstream license scope

The checked file headers identify `mstp.c` and `crc.c` as `GPL-2.0-or-later WITH GCC-exception-2.0`. The checked `cobs.c`, `mstpdef.h` and CRC test file identify MIT licensing. The project's [license explanation](https://github.com/bacnet-stack/bacnet-stack/blob/e295d20baba977132b47bc09f61f28e12f2dfac3/license/readme.txt) distinguishes its core implementation from permissively licensed example files; licenses must be checked per file.

The [upstream linking exception](https://github.com/bacnet-stack/bacnet-stack/blob/e295d20baba977132b47bc09f61f28e12f2dfac3/license/GCC-exception-2.0) grants additional permission for compiled combinations. It does not erase the underlying license conditions for modified upstream files or their separate distribution. This work used the C implementation only as an external, local encoding oracle and retains its notices in that checkout. There is no bundled upstream BACnet-stack binary requiring a runtime license installation step.

This provenance record does not assert that reviewing source automatically licenses a new implementation under the source's license, nor does it establish a legal clean-room or derivative-work conclusion. If future work incorporates upstream implementation text, generated code containing it, or compiled objects into a distributed product, that addition needs its own file-level attribution, license copies and applicable source-distribution treatment. The present notice records reference use; it does not grant permission to relabel upstream code as Apache-2.0.

The implemented protocol, test scope and remaining hardware/BTCVT/native-programming gaps are described in [Direct BACnet MS/TP transport](mstp-transport.md).
