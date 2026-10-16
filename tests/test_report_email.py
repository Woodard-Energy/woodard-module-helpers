import re
from datetime import UTC, datetime

from woodard_module_helpers.report_email import render_email


def test_title_is_escaped_body_is_not():
    html = render_email(title="Oil & <Gas>", body_html="<table><tr><td>1</td></tr></table>")
    assert "Oil &amp; &lt;Gas&gt;" in html
    assert "<table><tr><td>1</td></tr></table>" in html


def test_data_as_of_stamp_in_central_time():
    html = render_email(title="T", body_html="<p>x</p>",
                        data_as_of=datetime(2026, 10, 15, 11, 42, tzinfo=UTC))
    assert "Data as of Oct 15, 2026 6:42 AM CT" in html


def test_no_data_as_of_omits_stamp():
    assert "Data as of" not in render_email(title="T", body_html="<p>x</p>")


def test_email_safe_rules():
    html = render_email(title="T", body_html="<p>x</p>", footer="Sent by WIP")
    assert "<script" not in html.lower()
    assert "var(" not in html
    assert "class=" not in html  # inline styles only
    colors = re.findall(r"#[0-9a-fA-F]{6}\b", html)
    assert colors, "expected hardcoded hex colors"
    assert "Sent by WIP" in html
