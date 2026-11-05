import io
import json
import zipfile

import pytest

from scripts.privacy_audit import rules
from scripts.release_audit import audit


def test_nested_compressed_payloads_and_names_are_scanned_without_printing_values(tmp_path):
    secret = "test-only-" + "private-value"
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("module.py", secret)
    path = tmp_path / "example.whl"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("nested.zip", inner.getvalue())
        archive.writestr("assets/app.js.map", "{}")
        archive.writestr("assets/app.js", b"/Users/" + b"build-account/source/app.ts")
    result = audit([path], rules({"secrets": {"example": secret}}))
    assert result["complete"]
    assert {row["kind"] for row in result["findings"]} == {
        "known-secret:1",
        "absolute-home-directory",
        "production-source-map",
    }
    assert secret not in json.dumps(result)
    assert any("nested.zip!module.py" in row["location"] for row in result["findings"])


def test_missing_path_cannot_be_reported_clean(tmp_path):
    with pytest.raises(FileNotFoundError):
        audit([tmp_path / "missing.whl"], rules({}))


def test_internal_bundle_links_are_allowed_but_external_links_invalidate_completeness(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "real.txt").write_text("public example")
    (root / "internal.txt").symlink_to("real.txt")
    (root / "external.txt").symlink_to(tmp_path / "not-bundled")
    result = audit([root], rules({}))
    assert result["complete"] is False
    assert result["findings"] == []
    assert result["skipped"] == [{"location": "external.txt", "reason": "external-symlink"}]
