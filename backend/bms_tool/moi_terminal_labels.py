"""Explicit local-copy profile retaining observed ASCII or UCS-2 terminal labels."""

from .moi_effective_terminals import SCOPE as EFFECTIVE_SCOPE
from .moi_effective_terminals import EffectiveTerminalCopies
from .moi_identity import seal
from .moi_terminal_copies import OUTPUT_SCOPE, MoiTerminalCopies

PROFILE = "tagged-moi-local-terminal-copy/3"
EFFECTIVE_PROFILE = "native-effective-local-terminal-copy/2"
SCOPE = OUTPUT_SCOPE + (
    " Preserve the recorded Device Type CharacterString encoding: ASCII (0) or UCS-2 (4). "
    "Only the reviewed terminal label payload changes; no character-set conversion."
)
MERGED_SCOPE = EFFECTIVE_SCOPE + (
    " Use explicit terminal-copy profile 3, retaining observed ASCII/UCS-2 input-label "
    "encoding and recognizing unchanged local output-only terminal namespaces."
)


class EncodedTerminalCopies(MoiTerminalCopies):
    def __init__(self, source, *, output_namespace=True):
        if output_namespace is not True:
            raise ValueError("Encoded terminal copies require the separate output namespace.")
        super().__init__(source, output_namespace=True)
        self.profile, self.scope = PROFILE, SCOPE

    @staticmethod
    def label_payload(original, value):
        if not original or original[0] not in (0, 4):
            raise ValueError("The terminal label has no observed ASCII/UCS-2 encoding profile.")
        encoding = original[0]
        return bytes([encoding]) + value.encode("ascii" if encoding == 0 else "utf-16-be")

    def inspect(self):
        source = super().inspect()
        source["inputs"] = [
            {
                **item,
                "device_type_character_encoding": (
                    None
                    if item["internal"]
                    else self.payload(
                        self.editor.reader.records[item["ref"]], 31, 7, item["device_type"]
                    )[1][0]
                ),
            }
            for item in source["inputs"]
        ]
        return source

    def compile(self, **proposal):
        output, report = super().compile(**proposal)
        body = {key: value for key, value in report.items() if key != "compilation_sha256"}
        body["device_type_character_encoding"] = bytes.fromhex(body["payloads"][1]["before"])[0]
        body["device_type_encoding_preserved"] = True
        return output, {**body, "compilation_sha256": seal(body)}


class EncodedEffectiveTerminalCopies(EffectiveTerminalCopies):
    compiler_type = EncodedTerminalCopies
    profile = EFFECTIVE_PROFILE
    scope = MERGED_SCOPE
