"""Authored privacy rules and temporary repositories; no site data."""

import base64
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "privacy_audit.py"
spec = importlib.util.spec_from_file_location("privacy_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_reports_network_and_secret_categories_without_values():
    secret = "authored-" + "private-credential"
    private = audit.rules({"networks": ["192.0.2.0/24"], "secrets": {"test": secret}})
    data = b"example\n192.0.2.12\n" + base64.b64encode(secret.encode())
    result = audit.scan_bytes(data, private)
    assert {row["kind"] for row in result} == {
        "configured-network-address",
        "known-secret:1",
    }
    rendered = json.dumps(result)
    assert secret not in rendered and "192.0.2.12" not in rendered
    assert audit.safe_location("capture-192.0.2.12.txt", private).startswith("<redacted-location-")


def test_common_credentials_detected_without_private_rules():
    token = "ghp_" + "Z" * 36
    key_header = "-----BEGIN " + "PRIVATE KEY-----"
    key = key_header + "\n" + "Z" * 64 + "\n-----END " + "PRIVATE KEY-----"
    result = audit.scan_bytes((token + "\n" + key).encode(), audit.rules({}))
    assert {row["kind"] for row in result} == {"github-token", "private-key"}
    assert not audit.scan_bytes(key_header.encode(), audit.rules({}))
    assert not audit.scan_bytes(b"127.0.0.1 and documentation examples", audit.rules({}))


def test_invalid_private_rules_do_not_echo_the_value():
    bad = "a deliberately invalid private network"
    with pytest.raises(ValueError) as error:
        audit.rules({"networks": [bad]})
    assert bad not in str(error.value)


def test_deleted_file_is_detected_in_reachable_history(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init")
    git("config", "user.name", "Authored test")
    git("config", "user.email", "test@example.invalid")
    path = tmp_path / "old.txt"
    path.write_text("An authored password: " + "test-secret-value")
    git("add", "old.txt")
    git("commit", "-m", "Authored initial fixture")
    path.unlink()
    (tmp_path / "README").write_text("Clean current content")
    git("add", "-A")
    git("commit", "-m", "Remove authored old fixture")
    private = audit.rules({"secrets": {"test": "test-secret-value"}})
    assert not audit.scan_worktree(tmp_path, private)["findings"]
    result = audit.scan_history(tmp_path, private)
    assert len(result["findings"]) == 1
    assert result["findings"][0]["location"] == "old.txt"
    assert result["findings"][0]["kind"] == "known-secret:1"


def test_private_labels_cannot_leak_and_ipv6_is_rejected():
    secret = "authored-secret-label"
    result = audit.scan_bytes(secret.encode(), audit.rules({"secrets": {secret: secret}}))
    assert secret not in json.dumps(result)
    with pytest.raises(ValueError):
        audit.rules({"networks": ["2001:db8::/32"]})


def test_binary_and_json_embedded_keys_and_dynamic_network_prefix():
    header = "-----BEGIN " + "PRIVATE KEY-----"
    footer = "-----END " + "PRIVATE KEY-----"
    key = header + "\n" + "A" * 64 + "\n" + footer
    private = audit.rules({"networks": ["192.0.2.0/24"]})
    for body in (b"binary\x00" + key.encode(), json.dumps(key).encode()):
        assert any(row["kind"] == "private-key" for row in audit.scan_bytes(body, private))
    assert audit.scan_bytes(b'f"192.0.2.{index}"', private)[0]["kind"] == "configured-network-prefix"


def test_history_includes_sensitive_paths_and_annotated_tags(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init")
    git("config", "user.name", "Authored test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "capture-192.0.2.12.txt").write_text("Clean body")
    git("add", ".")
    git("commit", "-m", "Authored fixture")
    git("tag", "-a", "example", "-m", "Authored test-secret-value")
    result = audit.scan_history(tmp_path, audit.rules({
        "networks": ["192.0.2.0/24"], "secrets": {"test": "test-secret-value"}
    }))
    assert any(row["kind"].startswith("path:") for row in result["findings"])
    assert any(row.get("object_type") == "tag" for row in result["findings"])
    assert "192.0.2.12" not in json.dumps(result)


def test_gitlinks_are_reported_separately_and_private_paths_are_redacted(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True
        ).stdout

    git("init")
    git("config", "user.name", "Authored test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "README").write_text("Authored clean fixture")
    git("add", "README")
    git("commit", "-m", "Authored fixture")
    oid = git("rev-parse", "HEAD").decode().strip()
    git("update-index", "--add", "--cacheinfo", "160000," + oid + ",vendor/example")
    name = "capture-192.0.2.12.txt"
    (tmp_path / name).write_text("Clean body with a sensitive filename")
    git("add", name)
    result = audit.scan_worktree(tmp_path, audit.rules({"networks": ["192.0.2.0/24"]}))
    assert not result["skipped"]
    assert len(result["external_gitlinks"]) == 1
    assert result["external_gitlinks"][0]["object"] == oid
    assert len(result["findings"]) == 1
    assert result["findings"][0]["kind"] == "path:configured-network-address"
    assert "192.0.2.12" not in json.dumps(result)
