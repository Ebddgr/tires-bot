"""
otp_service.py - Automated OTP / 2-FA code retrieval service.
Supports Twilio, Gmail IMAP, Kavenegar SMS, Local Webhook/File forwarder, and Mock providers.
"""

import os
import re
import time
import email
import imaplib
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

logger = logging.getLogger("tires_bot.otp")

# Regex to match 4 to 6 consecutive digits
OTP_REGEX = re.compile(r"\b(\d{4,6})\b")

# Persian digits to standard ASCII conversion
PERSIAN_TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def normalize_persian_digits(text: str) -> str:
    """Translates Persian/Arabic numerals to ASCII digits."""
    return text.translate(PERSIAN_TO_ASCII)


def extract_otp_code(text: str) -> Optional[str]:
    """Extracts a 4 to 6 digit verification code from text."""
    if not text:
        return None
    normalized = normalize_persian_digits(text)
    match = OTP_REGEX.search(normalized)
    return match.group(1) if match else None


class BaseOTPProvider(ABC):
    """Abstract base provider for automated OTP retrieval."""

    @abstractmethod
    def fetch_otp(self, timeout: int = 60, poll_interval: int = 3) -> Optional[str]:
        """Polls for and returns the latest OTP code within the timeout window."""
        pass


class MockOTPProvider(BaseOTPProvider):
    """Provider returning pre-configured mock or test OTP codes."""

    def __init__(self, static_code: Optional[str] = None):
        self.static_code = static_code or os.getenv("TIRES_MOCK_OTP", "123456")

    def fetch_otp(self, timeout: int = 60, poll_interval: int = 3) -> Optional[str]:
        logger.info(f"[MockOTPProvider] Supplying mock OTP: {self.static_code}")
        return self.static_code


class FileWebhookOTPProvider(BaseOTPProvider):
    """
    Watches a local file or webhook inbox where an Android SMS forwarder
    app writes incoming SMS messages.
    """

    def __init__(self, file_path: Optional[str] = None, clear_on_read: bool = False):
        self.file_path = file_path or os.getenv(
            "TIRES_OTP_FILE",
            os.path.join(os.path.dirname(__file__), ".otp_inbox.txt"),
        )
        self.clear_on_read = clear_on_read

    def fetch_otp(self, timeout: int = 60, poll_interval: int = 1) -> Optional[str]:
        logger.info(f"[FileWebhookOTP] Monitoring {self.file_path} for OTP...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            if os.path.exists(self.file_path):
                try:
                    with open(self.file_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if content:
                        code = extract_otp_code(content)
                        if code:
                            logger.info(f"[FileWebhookOTP] Found OTP: {code}")
                            if self.clear_on_read:
                                with open(self.file_path, "w", encoding="utf-8") as f:
                                    f.write("")
                            return code
                except Exception as e:
                    logger.warning(f"Error reading OTP file: {e}")
            time.sleep(poll_interval)

        logger.error(f"[FileWebhookOTP] Timed out after {timeout}s waiting for OTP.")
        return None


class TwilioOTPProvider(BaseOTPProvider):
    """Retrieves OTP via Twilio Incoming Messages REST API."""

    def __init__(self, account_sid: str, auth_token: str, to_number: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.to_number = to_number

    def fetch_otp(self, timeout: int = 60, poll_interval: int = 3) -> Optional[str]:
        import requests
        from requests.auth import HTTPBasicAuth

        logger.info(f"[TwilioOTP] Polling Twilio SMS inbox for {self.to_number}...")
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        params = {"To": self.to_number, "PageSize": 5}
        auth = HTTPBasicAuth(self.account_sid, self.auth_token)
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                resp = requests.get(url, params=params, auth=auth, timeout=10)
                if resp.status_code == 200:
                    messages = resp.json().get("messages", [])
                    for msg in messages:
                        body = msg.get("body", "")
                        code = extract_otp_code(body)
                        if code:
                            logger.info(f"[TwilioOTP] Extracted OTP code: {code}")
                            return code
            except Exception as e:
                logger.warning(f"[TwilioOTP] Error querying Twilio: {e}")

            time.sleep(poll_interval)

        logger.error(f"[TwilioOTP] Timeout waiting for OTP code.")
        return None


class GmailIMAPOTPProvider(BaseOTPProvider):
    """Retrieves OTP by searching unread messages in Gmail via IMAP."""

    def __init__(self, username: str, app_password: str, imap_server: str = "imap.gmail.com"):
        self.username = username
        self.app_password = app_password
        self.imap_server = imap_server

    def fetch_otp(self, timeout: int = 60, poll_interval: int = 3) -> Optional[str]:
        logger.info(f"[GmailIMAP] Connecting to {self.imap_server} for user {self.username}...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                mail = imaplib.IMAP4_SSL(self.imap_server)
                mail.login(self.username, self.app_password)
                mail.select("INBOX")

                # Search for recent unread emails containing keywords
                search_criteria = '(UNSEEN)'
                status, data = mail.search(None, search_criteria)
                if status == "OK" and data[0]:
                    email_ids = data[0].split()
                    # Check most recent first
                    for e_id in reversed(email_ids):
                        _, msg_data = mail.fetch(e_id, "(RFC822)")
                        for response_part in msg_data:
                            if isinstance(response_part, tuple):
                                msg = email.message_from_bytes(response_part[1])
                                body = ""
                                if msg.is_multipart():
                                    for part in msg.walk():
                                        if part.get_content_type() == "text/plain":
                                            body += part.get_payload(decode=True).decode(errors="ignore")
                                else:
                                    body = msg.get_payload(decode=True).decode(errors="ignore")

                                code = extract_otp_code(body)
                                if code:
                                    logger.info(f"[GmailIMAP] Extracted OTP: {code}")
                                    mail.logout()
                                    return code
                mail.logout()
            except Exception as e:
                logger.warning(f"[GmailIMAP] IMAP fetch error: {e}")

            time.sleep(poll_interval)

        logger.error(f"[GmailIMAP] Timeout waiting for email OTP.")
        return None


class KavenegarOTPProvider(BaseOTPProvider):
    """Retrieves incoming SMS OTP from Kavenegar SMS API (Iranian SMS Gateway)."""

    def __init__(self, api_key: str, line_number: str):
        self.api_key = api_key
        self.line_number = line_number

    def fetch_otp(self, timeout: int = 60, poll_interval: int = 3) -> Optional[str]:
        import requests

        url = f"https://api.kavenegar.com/v1/{self.api_key}/sms/receive.json"
        params = {"linenumber": self.line_number, "isread": 0}
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    entries = resp.json().get("entries", [])
                    for entry in entries:
                        msg = entry.get("message", "")
                        code = extract_otp_code(msg)
                        if code:
                            logger.info(f"[KavenegarOTP] Extracted OTP: {code}")
                            return code
            except Exception as e:
                logger.warning(f"[KavenegarOTP] Fetch error: {e}")

            time.sleep(poll_interval)

        return None


def get_otp_provider(
    provider_type: Optional[str] = None,
    vault: Optional[Any] = None,
) -> BaseOTPProvider:
    """Factory creating configured OTP provider."""
    ptype = (provider_type or os.getenv("TIRES_OTP_PROVIDER", "mock")).lower()

    if ptype == "twilio":
        sid = (vault.get("TWILIO_ACCOUNT_SID") if vault else None) or os.getenv("TWILIO_ACCOUNT_SID", "")
        token = (vault.get("TWILIO_AUTH_TOKEN") if vault else None) or os.getenv("TWILIO_AUTH_TOKEN", "")
        phone = (vault.get("TWILIO_PHONE_NUMBER") if vault else None) or os.getenv("TWILIO_PHONE_NUMBER", "")
        return TwilioOTPProvider(sid, token, phone)

    elif ptype == "gmail":
        user = (vault.get("GMAIL_USER") if vault else None) or os.getenv("GMAIL_USER", "")
        pwd = (vault.get("GMAIL_APP_PASSWORD") if vault else None) or os.getenv("GMAIL_APP_PASSWORD", "")
        return GmailIMAPOTPProvider(user, pwd)

    elif ptype == "kavenegar":
        key = (vault.get("KAVENEGAR_API_KEY") if vault else None) or os.getenv("KAVENEGAR_API_KEY", "")
        line = (vault.get("KAVENEGAR_LINE_NUMBER") if vault else None) or os.getenv("KAVENEGAR_LINE_NUMBER", "")
        return KavenegarOTPProvider(key, line)

    elif ptype == "file":
        path = (vault.get("TIRES_OTP_FILE") if vault else None) or os.getenv("TIRES_OTP_FILE")
        return FileWebhookOTPProvider(path)

    # Default to mock provider for reliability and headless automated execution
    mock_code = (vault.get("TIRES_MOCK_OTP") if vault else None) or os.getenv("TIRES_MOCK_OTP", "123456")
    return MockOTPProvider(static_code=mock_code)


# ponytail: Using poll-based OTP adapters. Add push SSE / WebSocket webhook daemon when real-time sub-second latency required.
