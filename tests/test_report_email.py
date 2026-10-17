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


def test_default_width_is_640():
    assert "max-width:640px" in render_email(title="T", body_html="<p>x</p>")


def test_report_can_ask_for_a_wider_card():
    html = render_email(title="T", body_html="<p>x</p>", max_width=960)
    assert "max-width:960px" in html and "max-width:640px" not in html


def test_canvas_is_white_not_light_grey():
    # New Outlook dark mode turns a light-grey canvas into a mid-grey frame
    # around the card (route-daily, 2026-10-16); white maps to the same dark
    # tone as the card itself.
    html = render_email(title="T", body_html="<p>x</p>")
    assert "#f3f4f6" not in html
    assert 'body style="margin:0;padding:0;background:#ffffff;"' in html
