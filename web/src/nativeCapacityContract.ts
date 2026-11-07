import type { NativeArchiveSource } from "./NativeRecords";
import type { ControllerContext } from "./workflow";
import {
  connectionSame as same,
  connectionSeal,
} from "./nativeConnectionContract";
import { matchingConnectionTarget as targetMatches } from "./nativeMatchingConnectionContract";

type Data = Record<string, any>;
export const capacitySourceProfile = "native-file3-size-evidence/1";
export const capacityProfile = "native-file3-capacity-evidence/1";
export const capacityBase = "/bacnet/controller/native-application/resources";
export const capacityScope =
  "Historical retained archive bytes compared with one controller-reported File3 capacity observation. This is not current-program, merged-payload, free-memory, RAM/flash/scan/resource allocation, release/runtime/CCT or physical acceptance. No backup-state, restore, write, credentials change, review or transfer is prepared.";
const hash = (v: any) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const uint = (v: any, max = 0xffffffff) =>
  Number.isSafeInteger(v) && v >= 0 && v <= max;
const closed = (v: any, keys: string[]) =>
  !!v &&
  typeof v === "object" &&
  !Array.isArray(v) &&
  Object.keys(v).length === keys.length &&
  keys.every((k) => Object.hasOwn(v, k));
const date = (v: any) =>
  typeof v === "string" && v.length <= 64 && Number.isFinite(Date.parse(v));
async function sealed(v: Data, key: string) {
  const { [key]: digest, ...body } = v;
  return hash(digest) && (await connectionSeal(body)) === digest;
}
export async function capacitySource(value: Data, source: NativeArchiveSource) {
  try {
    if (
      !closed(value, [
        "profile",
        "source_kind",
        "capture_id",
        "snapshot_sha256",
        "sha256",
        "target",
        "captured_at",
        "identity",
        "source_identity_matches",
        "source_identity_error",
        "files",
        "scope",
        "read_only",
        "controller_queries",
        "field_actions",
        "identity_verified",
        "archive_bytes",
        "expanded_bytes",
        "compression",
        "native_record_count",
        "record_classes",
        "diagram_count",
        "source_immutable",
        "saved_settings_merged",
        "current_application_verified",
        "current_identity_verified",
        "controller_write",
        "restore_payload_prepared",
        "can_apply",
        "source_report_sha256",
      ]) ||
      value.profile !== capacitySourceProfile ||
      value.scope !== capacityScope ||
      value.source_kind !== "native-backup-archive" ||
      value.capture_id !== source.capture_id ||
      value.snapshot_sha256 !== source.snapshot_sha256 ||
      value.sha256 !== source.sha256 ||
      !same(value.files, source.files) ||
      !targetMatches(value.target, source.target) ||
      !date(value.captured_at) ||
      typeof value.source_identity_matches !== "boolean" ||
      value.read_only !== true ||
      value.source_immutable !== true ||
      [
        "controller_queries",
        "field_actions",
        "identity_verified",
        "saved_settings_merged",
        "current_application_verified",
        "current_identity_verified",
        "controller_write",
        "restore_payload_prepared",
        "can_apply",
      ].some((k) => value[k] !== false) ||
      !uint(value.archive_bytes, 2 * 1024 * 1024) ||
      value.archive_bytes === 0 ||
      value.archive_bytes !== source.files["3"].bytes ||
      !uint(value.expanded_bytes, 8 * 1024 * 1024) ||
      value.expanded_bytes < 14 ||
      !["gzip", "raw"].includes(value.compression) ||
      (value.compression === "raw" &&
        value.archive_bytes !== value.expanded_bytes) ||
      !uint(value.native_record_count, 20000) ||
      value.native_record_count === 0 ||
      !uint(value.diagram_count, value.native_record_count) ||
      !Array.isArray(value.record_classes) ||
      value.record_classes.length > 1024
    )
      return false;
    let count = 0,
      previous = -1,
      diagrams = 0;
    for (const r of value.record_classes) {
      if (
        !closed(r, ["class_id", "count"]) ||
        !uint(r.class_id, 1023) ||
        r.class_id <= previous ||
        !uint(r.count, 20000) ||
        r.count === 0
      )
        return false;
      previous = r.class_id;
      count += r.count;
      if ([536, 575].includes(r.class_id)) diagrams += r.count;
    }
    return (
      count === value.native_record_count &&
      diagrams === value.diagram_count &&
      (await sealed(value, "source_report_sha256"))
    );
  } catch {
    return false;
  }
}
function readTag(data: Uint8Array, offset: number) {
  if (offset >= data.length) throw Error("Missing native tag");
  const first = data[offset++],
    number = first >> 4,
    context = !!(first & 8),
    lvt = first & 7;
  if (number === 15) throw Error("Unexpected extended property tag");
  if (context && (lvt === 6 || lvt === 7))
    return {
      number,
      context,
      kind: lvt === 6 ? "open" : "close",
      data: new Uint8Array(),
      end: offset,
    };
  let size = lvt;
  if (lvt === 5) {
    if (offset >= data.length) throw Error("Missing tag length");
    size = data[offset++];
    if (size >= 254) {
      const bytes = size === 254 ? 2 : 4;
      size = 0;
      for (let i = 0; i < bytes; i++) {
        if (offset >= data.length) throw Error("Missing extended length");
        size = size * 256 + data[offset++];
      }
    }
  }
  if (size > 4 || offset + size > data.length)
    throw Error("Unbounded native property field");
  return {
    number,
    context,
    kind: "value",
    data: data.slice(offset, offset + size),
    end: offset + size,
  };
}
const hex = (v: any, max: number) =>
  typeof v === "string" &&
  v.length > 0 &&
  v.length <= max * 2 &&
  /^(?:[a-f0-9]{2})+$/.test(v);
const bytes = (v: string) =>
  Uint8Array.from(v.match(/../g)!.map((x) => parseInt(x, 16)));
const number = (v: Uint8Array) => v.reduce((a, b) => a * 256 + b, 0);
function endpoint(value: string, dnet?: number) {
  const ip = /^(\d{1,3}(?:\.\d{1,3}){3})(?:\/\d{1,2})?(?::(\d{1,5}))?$/.exec(
    value,
  );
  if (ip && ip[1].split(".").every((v) => Number(v) <= 255))
    return (
      ip[1].split(".").map(Number).join(".") + ":" + Number(ip[2] || 47808)
    );
  const remote = /^(\d+):0x([a-f0-9]{1,2})$/i.exec(value);
  if (remote) return `${Number(remote[1])}:${parseInt(remote[2], 16)}`;
  if (dnet && /^\d+$/.test(value)) return `${dnet}:${Number(value)}`;
  return value;
}
function nativeCapacity(encoded: string) {
  const data = bytes(encoded),
    tag = readTag(data, 0);
  if (
    tag.end !== data.length ||
    tag.context ||
    tag.kind !== "value" ||
    tag.number !== 2 ||
    tag.data.length < 1
  )
    throw Error("Not one native Unsigned");
  return number(tag.data);
}
function capacityWire(w: Data, value: number, target: Data) {
  if (
    !closed(w, [
      "received_at",
      "next_hop",
      "source",
      "invoke_id",
      "service",
      "response_apdu_hex",
      "udp_payload_sha256",
      "receive_provenance",
    ]) ||
    !date(w.received_at) ||
    typeof w.next_hop !== "string" ||
    typeof w.source !== "string" ||
    endpoint(w.next_hop) !== endpoint(target.router || target.address) ||
    endpoint(w.source, target.dnet) !== endpoint(target.address, target.dnet) ||
    !uint(w.invoke_id, 255) ||
    w.service !== 12 ||
    !hash(w.udp_payload_sha256) ||
    !hex(w.response_apdu_hex, 64) ||
    !closed(w.receive_provenance, [
      "basis",
      "local_endpoint",
      "physical_ip_destination",
    ]) ||
    w.receive_provenance.basis !== "native-stack local endpoint metadata" ||
    !Array.isArray(w.receive_provenance.local_endpoint) ||
    w.receive_provenance.local_endpoint.length !== 2 ||
    typeof w.receive_provenance.local_endpoint[0] !== "string" ||
    !uint(w.receive_provenance.local_endpoint[1], 65535) ||
    w.receive_provenance.local_endpoint[1] === 0 ||
    !(
      w.receive_provenance.physical_ip_destination === null ||
      typeof w.receive_provenance.physical_ip_destination === "string"
    )
  )
    return false;
  const apdu = bytes(w.response_apdu_hex);
  if (apdu[0] !== 0x30 || apdu[1] !== w.invoke_id || apdu[2] !== 12)
    return false;
  let offset = 3;
  const take = () => {
    const t = readTag(apdu, offset);
    offset = t.end;
    return t;
  };
  const oid = take(),
    pid = take(),
    open = take(),
    capacity = take(),
    close = take();
  return (
    oid.context &&
    oid.number === 0 &&
    oid.kind === "value" &&
    oid.data.length === 4 &&
    number(oid.data) === 10 * 4194304 + 3 &&
    pid.context &&
    pid.number === 1 &&
    pid.kind === "value" &&
    pid.data.length > 0 &&
    number(pid.data) === 3380 &&
    open.context &&
    open.number === 3 &&
    open.kind === "open" &&
    close.context &&
    close.number === 3 &&
    close.kind === "close" &&
    !capacity.context &&
    capacity.number === 2 &&
    capacity.kind === "value" &&
    capacity.data.length > 0 &&
    number(capacity.data) === value &&
    offset === apdu.length
  );
}
export async function capacityObservation(
  value: Data,
  source: NativeArchiveSource,
  controller: ControllerContext,
  operationId?: string,
) {
  try {
    if (
      !closed(value, [
        "profile",
        "scope",
        "source",
        "target",
        "identity",
        "connector_config",
        "operation_id",
        "observed_at",
        "capacity",
        "comparison",
        "read_only",
        "controller_queries",
        "current_identity_verified",
        "current_application_verified",
        "controller_write",
        "field_actions",
        "backup_state_commands",
        "restore_payload_prepared",
        "can_apply",
        "observation_sha256",
      ]) ||
      value.profile !== capacityProfile ||
      value.scope !== capacityScope ||
      !(await capacitySource(value.source, source)) ||
      value.source.source_identity_matches !== true ||
      !targetMatches(value.target, controller) ||
      !targetMatches(value.target, source.target) ||
      controller.interfaceOpen !== true ||
      controller.ownedCommands !== 0 ||
      !same(value.connector_config, JSON.parse(controller.interfaceKey)) ||
      value.identity?.["vendor-identifier"] !== 5 ||
      !same(value.identity, value.source.identity) ||
      value.identity.device !== controller.device ||
      value.identity["object-name"] !== controller.name ||
      !/^[A-Za-z0-9_-]{8,80}$/.test(value.operation_id || "") ||
      (operationId !== undefined && value.operation_id !== operationId) ||
      !date(value.observed_at) ||
      ["read_only", "controller_queries", "current_identity_verified"].some(
        (k) => value[k] !== true,
      ) ||
      [
        "current_application_verified",
        "controller_write",
        "field_actions",
        "backup_state_commands",
        "restore_payload_prepared",
        "can_apply",
      ].some((k) => value[k] !== false)
    )
      return false;
    const c = value.capacity,
      p = value.comparison;
    if (
      !closed(c, [
        "object",
        "property",
        "datatype",
        "bytes",
        "encoded_hex",
        "wire",
      ]) ||
      c.object !== "file,3" ||
      c.property !== 3380 ||
      c.datatype !== "Unsigned" ||
      !uint(c.bytes) ||
      c.bytes === 0 ||
      !hex(c.encoded_hex, 8) ||
      nativeCapacity(c.encoded_hex) !== c.bytes ||
      !capacityWire(c.wire, c.bytes, value.target) ||
      !closed(p, [
        "archive_bytes",
        "capacity_bytes",
        "archive_fits",
        "headroom_for_retained_archive_bytes",
        "basis",
      ]) ||
      p.archive_bytes !== value.source.archive_bytes ||
      p.capacity_bytes !== c.bytes ||
      p.archive_fits !== p.archive_bytes <= c.bytes ||
      p.headroom_for_retained_archive_bytes !== c.bytes - p.archive_bytes ||
      p.basis !==
        "Original retained File3 bytes; saved values are not merged and the current application is not read."
    )
      return false;
    return await sealed(value, "observation_sha256");
  } catch {
    return false;
  }
}
