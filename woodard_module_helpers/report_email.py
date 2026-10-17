"""Email-safe HTML shell for distributed reports.

Hardcoded hex colors, inline styles and table layout ON PURPOSE: Outlook
renders through Word (no var(), no flex, no classes it trusts) and an inbox
has no theme toggle. Same rules as the shell's welcome email. Do not
"modernise" this to tokens.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from jinja2 import Environment
from markupsafe import Markup

_CT = ZoneInfo("America/Chicago")

_TEMPLATE = """\
<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;">
<tr><td align="center" style="padding:16px 8px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:{{ max_width }}px;background:#ffffff;border:1px solid #e5e7eb;border-radius:6px;">
<tr><td style="padding:16px 20px;border-bottom:3px solid #0e7490;font-family:Arial,Helvetica,sans-serif;">
<div style="font-size:18px;font-weight:bold;color:#1f2937;">{{ title }}</div>
{% if stamp %}<div style="font-size:12px;color:#6b7280;padding-top:4px;">Data as of {{ stamp }}</div>{% endif %}
</td></tr>
<tr><td style="padding:16px 20px;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1f2937;">
{{ body }}
</td></tr>
{% if footer %}<tr><td style="padding:12px 20px;border-top:1px solid #e5e7eb;font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#6b7280;">{{ footer }}</td></tr>{% endif %}
</table>
</td></tr>
</table>
</body></html>
""" # noqa: E501

_env = Environment(autoescape=True)
_tmpl = _env.from_string(_TEMPLATE)


def _stamp(dt: datetime) -> str:
    local = dt.astimezone(_CT)
    hour = local.strftime("%I").lstrip("0")
    return f"{local.strftime('%b')} {local.day}, {local.year} {hour}:{local.strftime('%M %p')} CT"


def render_email(
    *, title: str, body_html: str, data_as_of: datetime | None = None, footer: str = "",
    max_width: int = 640,
) -> str:
    """Wrap a report body in the standard email shell.

    `title` and `footer` are escaped; `body_html` is trusted report markup and
    must itself follow the email-safe rules (inline styles, hex colors).
    `max_width` caps the card on wide screens; it is fluid (width 100%) below
    that, so a wider report still fits a phone.

    The canvas is white, not grey: dark-mode clients (new Outlook) recolour a
    light-grey canvas into a mid-grey frame around the card.
    """
    return _tmpl.render(
        title=title,
        body=Markup(body_html),
        stamp=_stamp(data_as_of) if data_as_of else "",
        footer=footer,
        max_width=int(max_width),
    )
