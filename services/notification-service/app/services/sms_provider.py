import logging
import httpx

logger = logging.getLogger(__name__)


async def send_sms_msg91(
    http_client: httpx.AsyncClient,
    auth_key: str,
    sender_id: str,
    phone: str,
    message: str,
) -> tuple[str, str]:
    """Send SMS via MSG91. Returns (provider_msg_id, status)."""
    if not auth_key:
        logger.info("[DEV] SMS suppressed (no MSG91_AUTH_KEY). To=%s msg=%s", phone, message[:60])
        return ("dev-mock-id", "SENT")

    # Normalize Indian numbers
    if not phone.startswith("+"):
        phone = f"+91{phone.lstrip('0')}"

    try:
        resp = await http_client.post(
            "https://api.msg91.com/api/v5/flow/",
            headers={"authkey": auth_key, "Content-Type": "application/json"},
            json={
                "template_id": "tms_generic",
                "short_url": "0",
                "mobiles": phone,
                "message": message,
                "sender": sender_id,
            },
            timeout=10.0,
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        msg_id = data.get("request_id", resp.text[:50])
        status = "SENT" if resp.status_code == 200 else "FAILED"
        return (msg_id, status)
    except Exception as exc:
        logger.error("MSG91 send failed: %s", exc)
        return ("", "FAILED")


async def send_whatsapp(
    http_client: httpx.AsyncClient,
    token: str,
    phone_number_id: str,
    to_phone: str,
    message: str,
) -> tuple[str, str]:
    """Send WhatsApp message via Meta Business API. Returns (msg_id, status)."""
    if not token or not phone_number_id:
        logger.info("[DEV] WhatsApp suppressed (no token). To=%s msg=%s", to_phone, message[:60])
        return ("dev-mock-wa-id", "SENT")

    if not to_phone.startswith("+"):
        to_phone = f"+91{to_phone.lstrip('0')}"

    try:
        resp = await http_client.post(
            f"https://graph.facebook.com/v18.0/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "text",
                "text": {"body": message},
            },
            timeout=10.0,
        )
        data = resp.json() if resp.status_code == 200 else {}
        msg_id = data.get("messages", [{}])[0].get("id", "")
        return (msg_id or resp.text[:50], "SENT" if resp.status_code == 200 else "FAILED")
    except Exception as exc:
        logger.error("WhatsApp send failed: %s", exc)
        return ("", "FAILED")
