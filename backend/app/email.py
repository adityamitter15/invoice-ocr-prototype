"""Transactional email delivery via the Resend HTTP API.

Hit the REST endpoint directly rather than import the Resend SDK: keeps the
dependency graph small and makes the request trivial to mock in tests.
"""

from __future__ import annotations

import html as html_module
import json
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"
RESEND_TIMEOUT_SECONDS = 6


def _from_address() -> str:
    return os.getenv("RESEND_FROM") or "AGW Heating <onboarding@resend.dev>"


def send_email(*, to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    """Send a transactional email. Returns True on successful delivery."""
    api_key = os.getenv("RESEND_API_KEY")
    payload = {
        "from": _from_address(),
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text

    if not api_key:
        logger.warning(
            "RESEND_API_KEY not set; email for %s would have been: %s",
            to, subject,
        )
        return False

    try:
        response = requests.post(
            RESEND_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=RESEND_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.error("Resend request failed: %s", exc)
        return False

    if response.status_code >= 400:
        logger.error("Resend returned %s: %s", response.status_code, response.text[:200])
        return False

    return True


def render_reset_email(*, username: str, reset_url: str, expires_minutes: int) -> tuple[str, str]:
    """Return an (html, text) pair for the password reset notification."""
    # Usernames currently come from controlled seeding, but escape anyway.
    safe_username = html_module.escape(username)
    safe_url = html_module.escape(reset_url, quote=True)

    text = (
        f"Hello {username},\n\n"
        "You asked to reset your AGW Heating manager password.\n\n"
        f"Open this link within {expires_minutes} minutes to choose a new one:\n"
        f"{reset_url}\n\n"
        "If you did not make this request you can ignore this email; no change "
        "has been made to your account.\n\n"
        "AGW Heating Manager Console\n"
    )

    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;color:#0f172a;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellpadding="0" cellspacing="0"
                 style="background:#ffffff;border-radius:14px;border:1px solid #e2e8f0;overflow:hidden;">
            <tr>
              <td style="padding:28px 32px;background:linear-gradient(135deg,#0f172a 0%,#1e1b4b 100%);">
                <div style="color:#fff;font-weight:700;font-size:18px;letter-spacing:0.02em;">AGW Heating</div>
                <div style="color:#cbd5e1;font-size:12px;margin-top:4px;text-transform:uppercase;letter-spacing:0.1em;">Manager Console</div>
              </td>
            </tr>
            <tr>
              <td style="padding:36px 32px 16px;">
                <h1 style="margin:0 0 12px;font-size:22px;font-weight:700;">Reset your password</h1>
                <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#334155;">
                  Hi {safe_username}, we received a request to reset the password for
                  your AGW Heating manager account. Use the button below to
                  choose a new one. The link is valid for {expires_minutes} minutes.
                </p>
                <p style="margin:28px 0;text-align:center;">
                  <a href="{safe_url}" style="display:inline-block;padding:12px 22px;border-radius:10px;background:#4f46e5;color:#ffffff;font-weight:600;font-size:14px;text-decoration:none;">Choose a new password</a>
                </p>
                <p style="margin:0 0 8px;font-size:12px;color:#64748b;">
                  If the button does not work, copy and paste this URL into your browser:
                </p>
                <p style="margin:0 0 24px;font-size:12px;color:#475569;word-break:break-all;">
                  <a href="{safe_url}" style="color:#4f46e5;">{safe_url}</a>
                </p>
                <p style="margin:0;font-size:12px;line-height:1.55;color:#64748b;">
                  Did not request this? You can safely ignore this email. No
                  change has been made to your account and the link will expire
                  on its own.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;">
                Sent automatically by the AGW Heating manager console for invoice OCR review.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return html_body, text
