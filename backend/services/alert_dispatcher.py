"""
alert_dispatcher.py
===================
Sends asynchronous alerts when a stock hits a Conviction Score >= 75.

Supported channels:
  1. Telegram  – requires TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars
  2. Email     – requires SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS +
                 ALERT_EMAIL_TO env vars

The dispatcher is intentionally lightweight — it reads directly from the
`conviction_matrix` Supabase table and fires outbound notifications.
It is called from the nightly scoring job in main.py.

If neither channel is configured the function logs a warning and returns
gracefully — the conviction scores are still saved to Supabase.
"""

import asyncio
import logging
import os
import smtplib
import urllib.request
import urllib.parse
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration from environment variables
# ──────────────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS     = os.environ.get("SMTP_PASS", "").strip()
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "").strip()

IS_TELEGRAM_CONFIGURED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
IS_EMAIL_CONFIGURED    = bool(SMTP_USER and SMTP_PASS and ALERT_EMAIL_TO)

CONVICTION_ALERT_THRESHOLD = int(os.environ.get("CONVICTION_ALERT_THRESHOLD", "75"))


# ──────────────────────────────────────────────────────────────────────────────
# Telegram dispatcher
# ──────────────────────────────────────────────────────────────────────────────

def _send_telegram_sync(message: str) -> bool:
    """Sends a message via Telegram Bot API (synchronous, run in executor)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error("[AlertDispatcher] Telegram send failed: %s", e)
        return False


async def send_telegram(message: str) -> bool:
    if not IS_TELEGRAM_CONFIGURED:
        return False
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_telegram_sync, message)


# ──────────────────────────────────────────────────────────────────────────────
# Email dispatcher
# ──────────────────────────────────────────────────────────────────────────────

def _send_email_sync(subject: str, body_html: str) -> bool:
    """Sends an HTML email via SMTP (synchronous, run in executor)."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = ALERT_EMAIL_TO

        part = MIMEText(body_html, "html")
        msg.attach(part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, ALERT_EMAIL_TO, msg.as_string())
        return True
    except Exception as e:
        logger.error("[AlertDispatcher] Email send failed: %s", e)
        return False


async def send_email(subject: str, body_html: str) -> bool:
    if not IS_EMAIL_CONFIGURED:
        return False
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_email_sync, subject, body_html)


# ──────────────────────────────────────────────────────────────────────────────
# Main dispatcher
# ──────────────────────────────────────────────────────────────────────────────

def _format_telegram_message(records: List[Dict[str, Any]]) -> str:
    """Formats the watchlist alert message for Telegram (Markdown)."""
    header = (
        "🔔 *Echo — Nightly Conviction Watchlist*\n"
        f"_Stocks with score ≥ {CONVICTION_ALERT_THRESHOLD}/100_\n\n"
    )
    lines = []
    for r in records:
        sym   = r.get("symbol", "?")
        score = r.get("conviction_score", 0)
        stop  = r.get("stop_loss_level")
        tags  = ", ".join(t for t in (r.get("catalyst_tags") or []) if "⚠" not in t)
        stop_str = f"₹{stop}" if stop else "N/A"

        lines.append(
            f"• *{sym}* — Score: *{score}/100*\n"
            f"  Catalyst: {tags or 'N/A'}\n"
            f"  Stop-Loss: {stop_str}"
        )
    return header + "\n\n".join(lines)


def _format_email_body(records: List[Dict[str, Any]]) -> str:
    """Formats the watchlist alert as an HTML email body."""
    rows_html = ""
    for r in records:
        sym   = r.get("symbol", "?")
        score = r.get("conviction_score", 0)
        stop  = r.get("stop_loss_level")
        tags  = ", ".join(t for t in (r.get("catalyst_tags") or []) if "⚠" not in t)
        verdict = r.get("verdict", "")
        stop_str = f"₹{stop}" if stop else "N/A"

        rows_html += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #333;font-weight:bold">{sym}</td>
          <td style="padding:8px;border-bottom:1px solid #333;color:#22c55e">{score}/100</td>
          <td style="padding:8px;border-bottom:1px solid #333">{tags or 'N/A'}</td>
          <td style="padding:8px;border-bottom:1px solid #333">{stop_str}</td>
          <td style="padding:8px;border-bottom:1px solid #333;font-size:12px">{verdict[:80]}</td>
        </tr>"""

    return f"""
    <html><body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif">
    <h2 style="color:#a78bfa">🔔 Echo — Nightly Conviction Watchlist</h2>
    <p>The following stocks crossed the <strong>{CONVICTION_ALERT_THRESHOLD}/100</strong>
       conviction threshold after tonight's data ingestion.</p>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#1e293b">
          <th style="padding:8px;text-align:left">Symbol</th>
          <th style="padding:8px;text-align:left">Score</th>
          <th style="padding:8px;text-align:left">Catalyst</th>
          <th style="padding:8px;text-align:left">Stop-Loss</th>
          <th style="padding:8px;text-align:left">Verdict</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    <p style="margin-top:24px;font-size:12px;color:#64748b">
      This is a tool for personal research only. Not financial advice.
      Always validate with your own analysis before acting.
    </p>
    </body></html>"""


async def dispatch_conviction_alerts(scored_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Filters `scored_records` for scores >= CONVICTION_ALERT_THRESHOLD and
    sends alerts via all configured channels.

    Args:
        scored_records: Output from conviction_engine.run_conviction_scoring()

    Returns:
        Dict with keys 'alerts_fired', 'telegram_sent', 'email_sent'
    """
    if not IS_TELEGRAM_CONFIGURED and not IS_EMAIL_CONFIGURED:
        logger.warning(
            "[AlertDispatcher] No alert channels configured. "
            "Set TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID or SMTP_* env vars."
        )
        return {"alerts_fired": 0, "telegram_sent": False, "email_sent": False}

    alert_records = [
        r for r in scored_records
        if r.get("conviction_score", 0) >= CONVICTION_ALERT_THRESHOLD
        # Exclude flagged traps from alerts
        and "DO NOT BUY" not in r.get("verdict", "")
    ]

    if not alert_records:
        logger.info("[AlertDispatcher] No stocks crossed %d/100 threshold tonight.", CONVICTION_ALERT_THRESHOLD)
        return {"alerts_fired": 0, "telegram_sent": False, "email_sent": False}

    logger.info("[AlertDispatcher] Firing alerts for %d high-conviction stocks.", len(alert_records))

    telegram_ok = False
    email_ok    = False

    if IS_TELEGRAM_CONFIGURED:
        msg = _format_telegram_message(alert_records)
        telegram_ok = await send_telegram(msg)
        logger.info("[AlertDispatcher] Telegram alert sent: %s", telegram_ok)

    if IS_EMAIL_CONFIGURED:
        subject = f"Echo Alert — {len(alert_records)} High-Conviction Stock(s) Tonight"
        body_html = _format_email_body(alert_records)
        email_ok = await send_email(subject, body_html)
        logger.info("[AlertDispatcher] Email alert sent: %s", email_ok)

    return {
        "alerts_fired": len(alert_records),
        "telegram_sent": telegram_ok,
        "email_sent":    email_ok,
        "symbols":       [r["symbol"] for r in alert_records],
    }
