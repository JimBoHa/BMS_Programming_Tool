"""Review and save a local engineering copy built from a complete inline controller capture."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from .file_access import sync_directory
from .moi_application import MAX_SOURCE
from .moi_identity import MoiIdentity, seal, sha
from .native_inline_monitor import MODELS, sources
from .native_inline_monitor_transfer import MonitorReview
from .native_inline_sequence_62 import EdgeTimedInlineSequenceCompiler, LegacyInlineSequenceCompiler
from .native_parameter_qualification import qualify_parameter_additions
from .native_snapshot_restore import Hash, Identifier, require_restore_source

PROFILE = "native-inline-local-program-draft/1"


def offered(snapshot, image):
    identity = snapshot.get("identity") or {}
    if not snapshot.get("source_identity_matches") or identity.get("model-name") not in MODELS:
        return False
    try:
        app = MoiIdentity(image)
        roots = [r for r in app.records if r["class_id"] == 575]
        if len(roots) != 1 or app.summary()["format_versions"] != {"acs": 62, "dmcs": 62}:
            return False
        root = app.reader.scalar(roots[0], 32527)
        sources(app, app.reader.diagram(root, retained_activity_refs=True), allow_floating=True)
    except (KeyError, TypeError, ValueError):
        return False
    return True


def _bounded(path, limit):
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if not 0 < len(content) <= limit:
        raise ValueError("A native source file is empty or exceeds its size bound.")
    return content


def compile_draft(files, prototype, first_instance, purpose, layout, sampling="paired"):
    if purpose not in ("observe", "control") or layout not in ("activities", "flat"):
        raise ValueError("Unknown inline reheat draft purpose or layout.")
    compilers = {
        "paired": LegacyInlineSequenceCompiler,
        "clock-edge": EdgeTimedInlineSequenceCompiler,
    }
    if sampling not in compilers:
        raise ValueError("Unknown inline sampling method.")
    compiler = compilers[sampling](files, prototype, first_instance)
    qualification = qualify_parameter_additions(compiler.application.source, compiler.merge)
    compiler.body()
    candidate, details = compiler.export(
        shadow=purpose == "observe", grouped=layout == "activities"
    )
    review = {
        "profile": PROFILE,
        "inputs_sha256": {str(n): sha(data) for n, data in files.items()},
        "prototype_sha256": sha(prototype),
        "purpose": purpose,
        "layout": layout,
        "parameter_qualification": qualification,
        "compilation": details,
        "controller_queries": False,
        "production_transfer_qualified": False,
    }
    # Preserve the exact bytes and review digest for existing paired-clock drafts.
    if sampling == "clock-edge":
        review["sampling"] = sampling
    return candidate, review


class RetainedDraft(MonitorReview):
    prototype_capture_id: Identifier
    prototype_sha256: Hash
    purpose: Literal["observe", "control"] = "observe"
    layout: Literal["activities", "flat"] = "activities"
    sampling: Literal["paired", "clock-edge"] = "paired"


class RetainedExport(RetainedDraft):
    review_sha256: Hash


def from_captures(native, options):
    source, files = native.storage.load(options.capture_id)
    donor, library = native.storage.load(options.prototype_capture_id)
    if (
        source["target"] != native.target(options)
        or source["device"] != options.device
        or source["evidence_sha256"] != options.snapshot_sha256
        or donor["evidence_sha256"] != options.prototype_sha256
        or not source.get("source_identity_matches")
        or not donor.get("source_identity_matches")
    ):
        raise ValueError("Select the exact target and verified captures for the inline draft.")
    identity = source["identity"]
    if any(
        identity.get(key) in (None, "") or identity.get(key) != donor["identity"].get(key)
        for key in ("model-name", "firmware-revision", "vendor-identifier")
    ):
        raise ValueError("The primitive source must have the same model, firmware and vendor.")
    _, recovery = native.restore_source(
        {"restore_capture_id": source["id"], "restore_snapshot_sha256": source["evidence_sha256"]}
    )
    require_restore_source(recovery)
    candidate, compiled = compile_draft(
        files, library[3], options.first_instance, options.purpose, options.layout, options.sampling
    )
    report = {
        **compiled,
        "target": {**source["target"], "device": source["device"]},
        "identity": identity,
        "capture_id": source["id"],
        "snapshot_sha256": source["evidence_sha256"],
        "prototype_capture_id": donor["id"],
        "prototype_snapshot_sha256": donor["evidence_sha256"],
    }
    digest = seal(report)
    if isinstance(options, RetainedExport) and digest != options.review_sha256:
        raise ValueError("The source, settings or layout differ from the reviewed local draft.")
    return candidate, {**report, "review_sha256": digest}


def local_draft(options):
    paths = (options.application, options.static, options.dynamic)
    if len({path.resolve() for path in paths}) != 3 or options.prototype.resolve() in {
        options.static.resolve(),
        options.dynamic.resolve(),
    }:
        raise ValueError("Supply distinct application and saved-parameter files.")
    files = {
        n: _bounded(path, size)
        for n, path, size in zip(
            (3, 11, 12), paths, (MAX_SOURCE, 128 * 1024, 128 * 1024), strict=True
        )
    }
    prototype = _bounded(options.prototype, MAX_SOURCE)
    candidate, review = compile_draft(
        files,
        prototype,
        options.first_instance,
        options.purpose,
        options.layout,
        getattr(options, "sampling", "paired"),
    )
    fingerprint = seal(review)
    if options.output is not None:
        if options.review_sha256 != fingerprint:
            raise ValueError("Review the current files, layout and valve wiring before saving.")
        writer = NamedTemporaryFile(
            dir=options.output.parent, prefix=".inline-draft-", delete=False
        )
        try:
            with writer:
                writer.write(candidate)
                writer.flush()
                os.fsync(writer.fileno())
            os.link(writer.name, options.output)
            sync_directory(options.output.parent)
        finally:
            Path(writer.name).unlink(missing_ok=True)
    return {
        **review,
        "review_sha256": fingerprint,
        "local_copy_written": options.output is not None,
    }
