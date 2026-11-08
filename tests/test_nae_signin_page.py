"""Credential-page contexts are escaped once; field values never enter JavaScript."""

import pytest
from bms_tool.nae_signin_page import native_signin_page


def context(**changes):
    return (
        dict(
            name="Example NAE",
            origin="engine.example",
            device="Device 123",
            model="Example NAE",
            firmware="example",
            certificate_sha256="a" * 64,
        )
        | changes
    )


def test_context_is_escaped_once_and_cannot_add_script_or_replace_another_field():
    html = native_signin_page(**context(name='</h1><script>fail("&")</script>__ENGINE_ORIGIN__'))
    assert (
        "&lt;/h1&gt;&lt;script&gt;fail(&quot;&amp;&quot;)&lt;/script&gt;__ENGINE_ORIGIN__" in html
    )
    assert html.count("<script>") == 1
    assert "</h1><script>fail" not in html
    assert "<strong>engine.example</strong>" in html


@pytest.mark.parametrize("value", [None, 123, "x" * 513])
def test_context_rejects_nontext_and_unbounded_fields(value):
    with pytest.raises(ValueError, match="Invalid native sign-in context"):
        native_signin_page(**context(origin=value))
