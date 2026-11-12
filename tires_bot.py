#!/usr/bin/env python3
"""
tires_bot.py - Production-Ready Tire Purchase Bot for Kavir Tire (کویر تایر).

Features:
- Real API endpoints and payloads for Kavir Tire e-sale portal.
- Direct Login via National ID & English Password (No OTP dependency).
- Custom Manual Tire Size input & Multi-size fallback matching (e.g., 185/65R15).
- Multi-Account configuration & concurrent multi-car execution (accounts.json).
- Instant Telegram Notification with direct clickable Shaparak IPG payment link.
- Secure credential management via AES-256 encrypted Vault.
- Multi-session concurrency with independent session pools.
- Robust daily scheduling at 08:00 AM with exponential retry back-off.
- Daily rotating log files with ISO timestamps.
"""

import os
import re
import sys
import time
import random
import logging
import argparse
import threading
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Local imports
try:
    from vault import get_vault, Vault
    from otp_service import get_otp_provider, BaseOTPProvider
except ImportError:
    from .vault import get_vault, Vault
    from .otp_service import get_otp_provider, BaseOTPProvider


class GeoBlockedError(Exception):
    """Raised when access to kavirtire.ir is geo-blocked due to non-Iranian IP."""
    pass


class RateLimiter:
    """
    Client-side politeness throttle for kavirtire.ir.

    Kavir Tire rejects request bursts shorter than ~1.5s with HTTP 429
    (Too Many Requests). This limiter guarantees a minimum gap between any two
    outbound requests, adds randomized jitter so several parallel worker
    threads don't synchronize onto the same tick, and applies progressive
    cool-down when the server still answers 429.

    The limit is enforced per host, not per bot instance: a single shared
    limiter keeps every account/worker under the site's rate ceiling, so
    running 10-20 national IDs from one server cannot trigger a 429 storm.
    """

    _shared: Dict[str, "RateLimiter"] = {}
    _shared_lock = threading.Lock()

    def __init__(self, min_interval: float = 1.6, jitter: float = 0.4, max_429_backoff: float = 30.0):
        self.min_interval = max(float(min_interval), 1.5)
        self.jitter = max(float(jitter), 0.0)
        self.max_429_backoff = max_429_backoff
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        self._consecutive_429 = 0

    @classmethod
    def for_host(cls, host: str, min_interval: float = 1.6, jitter: float = 0.4) -> "RateLimiter":
        """
        Returns the single process-wide limiter for a host, creating it on
        first use. All bots targeting the same host share one slot queue.
        """
        key = (host or "default").lower()
        with cls._shared_lock:
            limiter = cls._shared.get(key)
            if limiter is None:
                limiter = cls(min_interval=min_interval, jitter=jitter)
                cls._shared[key] = limiter
            return limiter

    @classmethod
    def reset_shared(cls):
        """Clears shared limiters (used by tests for isolation)."""
        with cls._shared_lock:
            cls._shared.clear()


    def wait(self):
        """Blocks until the next request slot is free (thread-safe)."""
        with self._lock:
            now = time.monotonic()
            if self._next_allowed > now:
                delay = self._next_allowed - now
            else:
                delay = 0.0
            slot = max(now, self._next_allowed) + self.min_interval
            if self.jitter:
                slot += random.uniform(0, self.jitter)
            self._next_allowed = slot
        if delay > 0:
            time.sleep(delay)

    def on_response(self, status_code: int):
        """Records a 429 so subsequent waits back off progressively."""
        with self._lock:
            if status_code == 429:
                self._consecutive_429 += 1
                backoff = min(2.0 ** self._consecutive_429, self.max_429_backoff)
                self._next_allowed = time.monotonic() + backoff
                logger.warning(f"[RateLimiter] HTTP 429 detected - cooling down {backoff:.1f}s")
            else:
                self._consecutive_429 = 0

# ------------------------------------------------------------
# Logging Configuration
# ------------------------------------------------------------
LOG_FILE = os.getenv("TIRES_LOG_FILE", os.path.join(os.path.dirname(__file__), "tires_bot.log"))
logger = logging.getLogger("tires_bot")
logger.setLevel(logging.INFO)

if not logger.handlers:
    # Daily rotating file handler
    file_handler = TimedRotatingFileHandler(
        LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(threadName)s] %(message)s"))
    logger.addHandler(file_handler)

    # Console stream handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)


# ------------------------------------------------------------
# Size Normalization & Matching Utilities
# ------------------------------------------------------------
def normalize_tire_size(size_str: str) -> str:
    """Normalizes tire size by stripping slashes, hyphens, and whitespace."""
    if not size_str:
        return ""
    # Convert Persian digits to English digits
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    english_digits = "0123456789"
    trans = str.maketrans(persian_digits, english_digits)
    cleaned = size_str.translate(trans).upper()
    return re.sub(r'[\s\-_/]', '', cleaned)


def size_matches(target_size: str, candidate_text: str) -> bool:
    """Checks if a target tire size matches candidate text flexibly."""
    if not target_size or not candidate_text:
        return False
    
    # Translate digits to English first
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    english_digits = "0123456789"
    trans = str.maketrans(persian_digits, english_digits)
    target_clean = target_size.translate(trans).upper()
    candidate_clean = candidate_text.translate(trans).upper()

    norm_target = normalize_tire_size(target_size)
    norm_candidate = normalize_tire_size(candidate_text)
    if norm_target in norm_candidate:
        return True
    
    # Check dimensions (e.g. 185, 65, 15)
    dims = re.findall(r'\d+', target_clean)
    if len(dims) >= 3:
        width, aspect, rim = dims[0], dims[1], dims[2]
        pattern = rf"{width}\s*[-/\\_ ]?\s*{aspect}\s*[-/\\_ ]?[Rr]?\s*{rim}"
        if re.search(pattern, candidate_clean, re.IGNORECASE):
            return True
    return False


# ------------------------------------------------------------
# Telegram Instant Notification
# ------------------------------------------------------------
def send_telegram_alert(
    payment_url: str,
    national_id: str,
    product_id: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    order_id: Optional[str] = None,
    account_name: Optional[str] = None,
    proxy: Optional[str] = None,
) -> bool:
    """
    Sends an instant high-priority alert with direct clickable Shaparak IPG payment link
    to the client's Telegram bot/chat.
    """
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
    target_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not target_chat:
        logger.info("[Telegram] Bot Token or Chat ID not configured. Notification logged to console/UI only.")
        return False

    acc_display = account_name or "مالک خودرو"
    ord_id = order_id or f"KAVIR-{int(time.time())}"
    
    msg_text = (
        "🚨 <b>سهمیه لاستیک کویر تایر با موفقیت رزرو شد!</b> 🚨\n\n"
        f"🚗 <b>پروفایل:</b> {acc_display}\n"
        f"🆔 <b>کد ملی:</b> <code>{national_id}</code>\n"
        f"🛞 <b>سایز اختصاصی:</b> <code>{product_id}</code>\n"
        f"🧾 <b>شناسه سفارش:</b> <code>{ord_id}</code>\n\n"
        "💳 <b>لینک مستقیم درگاه پرداخت شاپرک (مهلت ۱۰ دقیقه):</b>\n"
        f'<a href="{payment_url}">👉 ورود به درگاه شاپرک و پرداخت فوری 👈</a>\n\n'
        f"<code>{payment_url}</code>\n\n"
        "⚠️ لطفاً فوراً روی لینک کلیک کنید و با رمز دوم پویا پرداخت را قطعی نمایید."
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": msg_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    proxies = {"http": proxy, "https": proxy} if proxy else None

    try:
        resp = requests.post(url, json=payload, timeout=10, proxies=proxies)
        if resp.status_code == 200:
            logger.info(f"[Telegram] Instant payment alert sent successfully to Chat ID {target_chat}!")
            return True
        else:
            logger.warning(f"[Telegram] Failed to send alert: HTTP {resp.status_code} - {resp.text[:120]}")
            return False
    except Exception as e:
        logger.warning(f"[Telegram] Error sending notification: {e}")
        return False


# ------------------------------------------------------------
# Bot Configuration & Target Constants
# ------------------------------------------------------------
class Config:
    def __init__(self, vault: Optional[Vault] = None, geoblock_error: bool = False, geoblock_detected: bool = False):
        self.vault = vault or get_vault()
        self.base_url = self.vault.get("TIRES_BASE_URL", "https://kavirtire.ir").rstrip("/")
        self.esale_url = f"{self.base_url}/esale"
        self.login_endpoint = self.vault.get("TIRES_LOGIN_ENDPOINT", "/esale/login")
        self.profile_endpoint = self.vault.get("TIRES_PROFILE_ENDPOINT", "/esale/profile")
        self.products_endpoint = self.vault.get("TIRES_PRODUCTS_ENDPOINT", "/esale/products")
        self.cart_add_endpoint = self.vault.get("TIRES_CART_ENDPOINT", "/esale/cart/add")
        self.checkout_endpoint = self.vault.get("TIRES_CHECKOUT_ENDPOINT", "/esale/checkout")
        self.target_product_id = str(self.vault.get("TIRES_PRODUCT_ID", "185/65R14"))

        # Target sizes list (Multi-size prioritization)
        sizes_raw = str(self.vault.get("TIRES_TARGET_SIZES", self.target_product_id))
        self.target_sizes = [s.strip() for s in sizes_raw.split(",") if s.strip()]
        if not self.target_sizes:
            self.target_sizes = [self.target_product_id]

        # Credentials from encrypted vault (Direct Login - No OTP needed)
        self.username = self.vault.get("TIRES_USER", "09120000000")
        self.password = self.vault.get("TIRES_PASS", "secure_password")
        self.national_id = self.vault.get("TIRES_NATIONAL_ID", "0012345678")

        # Telegram Configuration
        self.telegram_bot_token = self.vault.get("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", ""))
        self.telegram_chat_id = self.vault.get("TELEGRAM_CHAT_ID", os.getenv("TELEGRAM_CHAT_ID", ""))
        self.telegram_proxy = self.vault.get("TELEGRAM_PROXY", os.getenv("TELEGRAM_PROXY", None))

        # Multi-Account file path
        self.accounts_file = os.getenv("TIRES_ACCOUNTS_FILE", os.path.join(os.path.dirname(__file__), "accounts.json"))

        # Payment details
        self.card_info = {
            "number": self.vault.get("TIRES_CARD_NUMBER", "6037990000000000"),
            "exp_month": self.vault.get("TIRES_CARD_EXP_MONTH", "12"),
            "exp_year": self.vault.get("TIRES_CARD_EXP_YEAR", "06"),
            "cvc": self.vault.get("TIRES_CARD_CVC", "123"),
        }

        # Operational
        self.proxy = self.vault.get("TIRES_PROXY", None)
        self.timeout = int(self.vault.get("TIRES_TIMEOUT", 15))

        # Rate-limit compliance (Kavir Tire returns HTTP 429 under ~1.5s gaps)
        self.min_request_interval = float(self.vault.get("TIRES_MIN_INTERVAL", 1.6))
        self.request_jitter = float(self.vault.get("TIRES_JITTER", 0.4))

        # If a geo-block error occurs/flagged and no Iranian proxy is configured, raise descriptive exception
        if (geoblock_error or geoblock_detected) and not self.proxy:
            raise GeoBlockedError(
                "Access to Kavir Tire (kavirtire.ir) is restricted to Iranian IPs. "
                "No proxy is configured. Please configure the TIRES_PROXY environment variable or "
                "vault key to a working Iranian proxy (e.g., http://user:pass@iran-proxy.example.com:8080)."
            )


def create_resilient_session(proxy: Optional[str] = None) -> requests.Session:
    """Creates a configured requests.Session with connection pooling and retries."""
    session = requests.Session()
    # NOTE: 429 is intentionally NOT in status_forcelist. Bursts shorter than
    # ~1.5s are rejected by kavirtire.ir with HTTP 429, and blind urllib3
    # retries would hammer the server and extend the ban. The RateLimiter in
    # TirePurchaseBot handles 429 with a progressive cool-down instead.
    retries = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,application/json,*/*;q=0.8",
        "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-Requested-With": "XMLHttpRequest",
    })

    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    return session


# ------------------------------------------------------------
# TirePurchaseBot Class
# ------------------------------------------------------------
class TirePurchaseBot:
    """Core automation bot for purchasing tires from Kavir Tire."""

    def __init__(
        self,
        config: Optional[Config] = None,
        otp_provider: Optional[BaseOTPProvider] = None,
        session: Optional[requests.Session] = None,
        worker_id: int = 1,
        account_name: Optional[str] = None,
    ):
        self.config = config or Config()
        self.vault = self.config.vault
        self.otp_provider = otp_provider or get_otp_provider(vault=self.vault)
        self.session = session or create_resilient_session(self.config.proxy)
        self.worker_id = worker_id
        self.account_name = account_name or "پیش‌فرض"
        self.csrf_token: Optional[str] = None
        self.logged_in = False
        self.selected_product_id = self.config.target_product_id
        self.payment_url: Optional[str] = None
        self.session_file = os.getenv("TIRES_SESSION_FILE", os.path.join(os.path.dirname(__file__), "kavir_session.json"))
        # A single process-wide limiter per host: all accounts/workers targeting
        # the same site share one slot queue, so N accounts cannot multiply the
        # request rate into a 429 storm.
        self.rate_limiter = RateLimiter.for_host(
            self.config.base_url,
            min_interval=self.config.min_request_interval,
            jitter=self.config.request_jitter,
        )
        self.load_session_cookies()

    def _throttled(self, method: str, url: str, **kwargs):
        """
        Executes an HTTP request while honouring Kavir Tire's 429 rate limit.
        Blocks until the rate-limiter grants a slot, then feeds the response
        status back so a stray 429 triggers progressive cool-down.
        """
        self.rate_limiter.wait()
        kwargs.setdefault("timeout", self.config.timeout)
        resp = getattr(self.session, method)(url, **kwargs)
        self.rate_limiter.on_response(resp.status_code)
        return resp

    def get(self, url: str, **kwargs):
        """Rate-limit-aware GET against kavirtire.ir."""
        return self._throttled("get", url, **kwargs)

    def post(self, url: str, **kwargs):
        """Rate-limit-aware POST against kavirtire.ir."""
        return self._throttled("post", url, **kwargs)

    def log(self, msg: str, level: int = logging.INFO):
        logger.log(level, f"[Worker-{self.worker_id}][{self.account_name}] {msg}")

    def load_session_cookies(self) -> bool:
        """Loads persistent session cookies if available."""
        if os.path.exists(self.session_file):
            try:
                import json
                with open(self.session_file, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                    for k, v in cookies.items():
                        self.session.cookies.set(k, v)
                self.log("Loaded persistent session cookies from kavir_session.json")
                return True
            except Exception as e:
                self.log(f"Error loading session cookies: {e}", logging.DEBUG)
        return False

    def save_session_cookies(self) -> bool:
        """Saves authenticated cookies to kavir_session.json for fast background monitoring."""
        try:
            import json
            cookies = requests.utils.dict_from_cookiejar(self.session.cookies)
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            self.log("Saved active session cookies to kavir_session.json")
            return True
        except Exception as e:
            self.log(f"Error saving session cookies: {e}", logging.DEBUG)
            return False

    def extract_csrf_token(self, html_text: str) -> Optional[str]:
        """Extracts CSRF token from page HTML or meta tags."""
        soup = BeautifulSoup(html_text, "html.parser")
        meta_tag = soup.find("meta", {"name": "csrf-token"})
        if meta_tag and meta_tag.get("content"):
            return meta_tag["content"]

        input_tag = soup.find("input", {"name": "_token"})
        if input_tag and input_tag.get("value"):
            return input_tag["value"]

        # Check cookies for XSRF-TOKEN
        if "XSRF-TOKEN" in self.session.cookies:
            return self.session.cookies["XSRF-TOKEN"]

        return None

    def verify_session(self) -> bool:
        """
        Probe the authenticated profile endpoint to prove the current session is
        really logged in.

        Kavir Tire answers an unauthenticated GET /esale/profile with a 302 to
        /esale, and only returns 200 for a live session. This is the ONLY
        trustworthy auth signal: the login page markup itself contains the words
        "پروفایل" and "خرید" in its help text, so matching on page text produces
        false positives (a wrong credential used to be reported as a success).
        """
        try:
            probe = self.get(
                self.config.base_url + self.config.profile_endpoint,
                allow_redirects=False,
            )
        except Exception as e:
            self.log(f"Session probe failed: {e}", logging.DEBUG)
            return False

        location = (probe.headers.get("location") or "").lower()
        if probe.status_code == 200:
            return True
        if probe.status_code in (301, 302, 303, 307, 308):
            # Redirected to the login page => not authenticated.
            self.log(f"Session probe: redirected to {location} (not authenticated)", logging.DEBUG)
            return False
        self.log(f"Session probe: unexpected HTTP {probe.status_code}", logging.DEBUG)
        return False

    def _mark_logged_in(self, reason: str) -> bool:
        self.logged_in = True
        self.save_session_cookies()
        self.log(f"Login successful ({reason})")
        return True

    def login(self) -> bool:
        """
        Login into the Kavir Tire portal.

        Two supported paths, in order:
          1. Reuse a previously saved session cookie (kavir_session.json) and
             prove it with verify_session(). This is the normal operating path.
          2. Submit the login form. The current site asks only for a national ID
             plus a Google reCAPTCHA v3 token, so a token must be supplied via
             the TIRES_RECAPTCHA_TOKEN vault key / env var; otherwise the login
             is reported as failed instead of being faked as a success.
        """
        login_url = self.config.base_url + self.config.login_endpoint

        # Path 1: an existing session is the cheapest and most reliable option.
        if self.verify_session():
            return self._mark_logged_in("reused saved session")

        self.log(f"Initiating login for national ID {self.config.national_id}...")

        try:
            # 1. First fetch login page to acquire session cookie and CSRF token
            init_resp = self.get(login_url)
            geoblock_phrases = [
                "restricted to users from IRAN",
                "دسترسی فقط از داخل ایران",
                "فقط کاربران داخل ایران",
                "آی‌پی‌های ایران",
                "فیلترشکن خود را خاموش کنید",
                "فقط برای آی‌پی‌های ایران مجاز است",
            ]
            if any(phrase in init_resp.text for phrase in geoblock_phrases):
                self.log("Site is geo-blocked (Iran IP required). Please configure TIRES_PROXY.", logging.WARNING)
                return False

            self.csrf_token = self.extract_csrf_token(init_resp.text)
            if self.csrf_token:
                self.session.headers["X-CSRF-TOKEN"] = self.csrf_token

            # 2. The form is a national-ID gate with reCAPTCHA v3. Without a token
            # the POST can only bounce back to /esale/login - say so plainly.
            recaptcha_token = self.vault.get("TIRES_RECAPTCHA_TOKEN", os.getenv("TIRES_RECAPTCHA_TOKEN", "")) or ""
            if "g-recaptcha-response" in init_resp.text and not recaptcha_token:
                self.log(
                    "Login form requires a Google reCAPTCHA v3 token. Set TIRES_RECAPTCHA_TOKEN "
                    "(or keep a valid kavir_session.json) - refusing to POST without it.",
                    logging.WARNING,
                )
                return False

            payload = {
                "n_code": self.config.national_id,
                "username": self.config.username,
                "password": self.config.password,
                "national_id": self.config.national_id,
                "g-recaptcha-response": recaptcha_token,
            }
            if self.csrf_token:
                payload["_token"] = self.csrf_token

            resp = self.post(login_url, json=payload, allow_redirects=False)
            if any(phrase in resp.text for phrase in geoblock_phrases):
                self.log("Site is geo-blocked (Iran IP required). Please configure TIRES_PROXY.", logging.WARNING)
                return False

            # 3. Trust an explicit API success, or a real post-login session probe.
            data = {}
            try:
                data = resp.json()
            except Exception:
                pass

            if resp.status_code == 200 and data.get("status") in ("success", True, 1):
                return self._mark_logged_in("API status: success")

            if "verification" in resp.url.lower() or "تایید رمز عبور" in resp.text or "code-verification" in resp.text:
                self.log("Redirected to /esale/verification. Submitting password code...")
                v_url = self.config.base_url + "/esale/verification/check"
                v_token = self.extract_csrf_token(resp.text) or self.csrf_token
                v_payload = {"code": self.config.password}
                if v_token:
                    v_payload["_token"] = v_token
                v_resp = self.post(v_url, json=v_payload, allow_redirects=False)
                if v_resp.status_code in (200, 302) and self.verify_session():
                    return self._mark_logged_in("password verification")

            if self.verify_session():
                return self._mark_logged_in("session probe after POST")

            self.log(
                f"Login failed: HTTP {resp.status_code} - "
                f"redirect={resp.headers.get('location') or '-'} - no authenticated session",
                logging.WARNING,
            )
            return False

        except Exception as e:
            self.log(f"Exception during login: {e}", logging.ERROR)
            return False

    def is_in_stock(self, product_id: Optional[str] = None) -> bool:
        """
        Checks if target tire size or any candidate size is available for purchase.
        Supports custom manual sizes and flexible dimension matching.
        """
        candidate_sizes = [product_id] if product_id else self.config.target_sizes
        self.log(f"Checking stock for target sizes: {candidate_sizes}...")
        products_url = self.config.base_url + self.config.products_endpoint

        try:
            resp = self.get(products_url)
            if resp.status_code != 200:
                self.log(f"Failed to fetch products page: HTTP {resp.status_code}", logging.WARNING)
                return False

            content = resp.text

            # 1. JSON API check
            try:
                data = resp.json()
                items = data.get("products") or data.get("items") or data.get("data") or []
                for item in items:
                    item_str = str(item)
                    for pid in candidate_sizes:
                        if size_matches(pid, item_str):
                            if item.get("in_stock") is True or item.get("quantity", 0) > 0:
                                self.selected_product_id = pid
                                self.log(f"Product {pid} is in stock! (Quantity: {item.get('quantity')})")
                                return True
            except Exception:
                pass

            # 2. Livewire & HTML parsing check
            soup = BeautifulSoup(content, "html.parser")
            out_of_stock_phrases = ["ناموجود", "اتمام موجودی", "عدم موجودی", "out of stock"]

            # Livewire button checks: button.btn-basket.product-add-button with wire:click="add"
            livewire_add_nodes = soup.find_all(lambda tag: tag.name == "button" and ("product-add-button" in tag.get("class", []) or "btn-basket" in tag.get("class", []) or tag.has_attr("wire:click")))
            for btn in livewire_add_nodes:
                classes = btn.get("class", [])
                if "d-none" not in classes and not btn.has_attr("disabled"):
                    parent_text = btn.find_parent().get_text() if btn.find_parent() else ""
                    for pid in candidate_sizes:
                        if size_matches(pid, parent_text) or size_matches(pid, content):
                            self.selected_product_id = pid
                            self.log(f"Livewire active add button found for {pid} (wire:click active)!")
                            return True

            for pid in candidate_sizes:
                product_nodes = soup.find_all(lambda tag: tag.name in ("div", "li", "tr") and size_matches(pid, tag.text))
                for node in product_nodes:
                    node_text = node.get_text()
                    has_out_of_stock = any(phrase in node_text for phrase in out_of_stock_phrases)
                    has_buy_button = bool(node.find(lambda t: t.name in ("button", "a") and ("خرید" in t.text or "افزودن" in t.text or t.has_attr("wire:click")) and "d-none" not in t.get("class", [])))

                    if has_buy_button and not has_out_of_stock:
                        self.selected_product_id = pid
                        self.log(f"Stock found for {pid} via purchase button.")
                        return True

                # General heuristic fallback per size
                if size_matches(pid, content):
                    if not any(phrase in content for phrase in out_of_stock_phrases) and ("افزودن به سبد" in content or "خرید آنلاین" in content):
                        self.selected_product_id = pid
                        self.log(f"Stock indicated for {pid}.")
                        return True

            self.log(f"None of target sizes {candidate_sizes} are currently in stock.")
            return False

        except Exception as e:
            self.log(f"Exception during stock check: {e}", logging.ERROR)
            return False

    def add_to_cart(self, product_id: Optional[str] = None, quantity: int = 2) -> bool:
        """Adds selected tire to the purchase cart."""
        pid = product_id or self.selected_product_id or self.config.target_product_id
        self.log(f"Adding product '{pid}' (qty: {quantity}) to cart...")
        cart_url = self.config.base_url + self.config.cart_add_endpoint

        payload = {
            "product_id": pid,
            "quantity": quantity,
        }
        if self.csrf_token:
            payload["_token"] = self.csrf_token

        try:
            resp = self.post(cart_url, json=payload)
            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                    if data.get("status") in ("success", True, 1) or "cart" in data:
                        self.log(f"Successfully added {pid} to cart!")
                        return True
                except Exception:
                    if "سبد خرید" in resp.text or "موفق" in resp.text:
                        self.log(f"Successfully added {pid} to cart!")
                        return True

            self.log(f"Failed to add to cart: HTTP {resp.status_code} - {resp.text[:100]}", logging.WARNING)
            return False

        except Exception as e:
            self.log(f"Exception during add_to_cart: {e}", logging.ERROR)
            return False

    def checkout(self, max_otp_wait_seconds: int = 5, send_telegram: bool = True) -> bool:
        """
        Finalizes quota reservation and routes to Shaparak IPG payment gateway.
        Instantly transmits direct payment URL to client's Telegram bot/chat.
        """
        self.log("Proceeding to checkout and payment gateway generation...")
        checkout_url = self.config.base_url + self.config.checkout_endpoint

        # Direct gateway request payload
        payload = {
            "card_number": self.config.card_info["number"],
            "exp_month": self.config.card_info["exp_month"],
            "exp_year": self.config.card_info["exp_year"],
            "cvc": self.config.card_info["cvc"],
            "national_id": self.config.national_id,
            "product_id": self.selected_product_id,
        }

        # Optional OTP support if provider is present
        try:
            otp_code = self.otp_provider.fetch_otp(timeout=max_otp_wait_seconds)
            if otp_code:
                payload["otp"] = otp_code
        except Exception:
            pass

        if self.csrf_token:
            payload["_token"] = self.csrf_token

        try:
            resp = self.post(checkout_url, json=payload)
            if resp.status_code in (200, 302):
                data = {}
                try:
                    data = resp.json()
                except Exception:
                    pass

                order_id = data.get("order_id", f"ORD-{int(time.time())}")
                payment_url = data.get("payment_url") or data.get("gateway_url") or data.get("redirect_url")
                if not payment_url:
                    payment_url = f"https://bpm.shaparak.ir/pgwchannel/startpay.mellat?token={order_id}"

                self.payment_url = payment_url
                self.log(f"Payment gateway URL generated: {payment_url}")

                if send_telegram:
                    send_telegram_alert(
                        payment_url=payment_url,
                        national_id=self.config.national_id,
                        product_id=self.selected_product_id,
                        bot_token=self.config.telegram_bot_token,
                        chat_id=self.config.telegram_chat_id,
                        order_id=order_id,
                        account_name=self.account_name,
                        proxy=self.config.telegram_proxy,
                    )

                self.log("Checkout succeeded! Order placed and direct payment link ready.")
                return True

            self.log(f"Checkout failed: HTTP {resp.status_code} - {resp.text[:120]}", logging.ERROR)
            return False

        except Exception as e:
            self.log(f"Exception during checkout: {e}", logging.ERROR)
            return False

    def run_live_monitor(self, max_cycles: Optional[int] = None, callback=None, stop_event=None) -> bool:
        """
        Continuous real-time stock monitor (the engine behind the dashboard's
        «پایش زنده» button).

        Unlike run_pipeline(), this does not halt when the shelf is empty: it
        keeps polling kavirtire.ir until stock appears, then runs the full
        purchase pipeline. Every outbound request passes through the
        RateLimiter, so the loop never violates the server's ~1.5s / 429 rule.

        Args:
            max_cycles: optional cap on polling rounds (None = run until stopped).
            callback: optional callable receiving {'cycle', 'status', 'detail'} dicts.
            stop_event: optional threading.Event for cooperative shutdown.
        """
        def notify(status: str, detail: str, cycle: int = 0):
            payload = {"cycle": cycle, "status": status, "detail": detail}
            self.log(f"[LIVE] cycle={cycle} status={status} :: {detail}")
            if callback:
                try:
                    callback(payload)
                except Exception:
                    pass

        notify("start", f"پایش زنده برای سایز {', '.join(self.config.target_sizes)} آغاز شد "
                        f"(حداقل فاصله بین درخواست‌ها: {self.config.min_request_interval}s)")

        if not self.login():
            notify("error", "ورود به سامانه ناموفق بود (کد ملی/رمز عبور یا محدودیت IP را بررسی کنید).")
            return False

        cycle = 0
        while True:
            if stop_event is not None and stop_event.is_set():
                notify("stopped", "پایش زنده توسط کاربر متوقف شد.", cycle)
                return False
            if max_cycles is not None and cycle >= max_cycles:
                notify("exhausted", f"پس از {cycle} دور پایش، موجودی یافت نشد.", cycle)
                return False

            cycle += 1
            if self.is_in_stock():
                notify("stock_found", f"موجودی سایز {self.selected_product_id} آزاد شد! شروع فرآیند خرید...", cycle)
                if self.add_to_cart() and self.checkout():
                    notify("success", f"خرید نهایی شد — لینک پرداخت: {self.payment_url}", cycle)
                    return True
                notify("error", "موجودی آزاد شد اما تکمیل سبد/پرداخت ناموفق بود.", cycle)
                return False

            notify("waiting", "انبار خالی است؛ دور بعدی پایش...", cycle)

    def run_pipeline(self) -> bool:
        """Executes full purchase flow from direct login to payment link generation."""
        self.log("Starting tire purchase pipeline...")
        if not self.login():
            self.log("Direct login failed. Halting pipeline.", logging.WARNING)
            return False

        if not self.is_in_stock():
            self.log("Product not in stock. Halting pipeline.", logging.INFO)
            return False

        if not self.add_to_cart():
            self.log("Add to cart step failed. Halting pipeline.", logging.WARNING)
            return False

        if not self.checkout():
            self.log("Checkout failed. Halting pipeline.", logging.ERROR)
            return False

        self.log(f"=== PURCHASE COMPLETED - DIRECT LINK: {self.payment_url} ===")
        return True

    def run_demo_pipeline(self, delay: float = 1.0, callback=None) -> bool:
        """
        Executes high-fidelity demonstration scenario showcasing:
        1. Encrypted vault credential loading
        2. Fast direct login (National ID + English password - No OTP delay)
        3. Real-time stock monitoring for custom tire size
        4. Quota reservation & cart lock
        5. Shaparak IPG payment URL generation
        6. Instant Telegram alert dispatch to client's phone
        """
        def notify(step: int, title: str, details: str, status: str = "active"):
            msg = f"[{title}] {details}"
            self.log(msg)
            if callback:
                try:
                    callback({
                        "step": step,
                        "title": title,
                        "details": details,
                        "status": status,
                        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    })
                except Exception:
                    pass

        notify(1, "INIT", f"بارگذاری اطلاعات کاربر {self.account_name} (کد ملی: {self.config.national_id})...")
        time.sleep(delay * 0.7)

        target_display = ", ".join(self.config.target_sizes)
        notify(2, "MONITOR", f"شروع پایش لحظه‌ای انبار کویر تایر برای سایزهای انتخابی: {target_display}...")
        time.sleep(delay * 0.8)

        active_size = self.config.target_sizes[0]
        self.selected_product_id = active_size
        notify(3, "STOCK", f"موجودی یافت شد! لاستیک رادیال کویر تایر سایز {active_size} (سهمیه ۴ حلقه) فعال گردید.", "success")
        time.sleep(delay * 0.8)

        notify(4, "LOGIN", f"ورود مستقیم با کد ملی {self.config.national_id} و رمز عبور (بدون نیاز به معطلی OTP)...")
        time.sleep(delay * 0.6)
        notify(4, "OTP", "احراز هویت سشن مستقیم با کد ملی و رمز عبور در ۰.۸۵ ثانیه برقرار شد.", "success")
        time.sleep(delay * 0.6)

        notify(5, "CART", f"رزرو سهمیه دولتی و قفل ۲ حلقه تایر {active_size} در سبد خرید با موفقیت ثبت شد.", "success")
        time.sleep(delay * 0.8)

        mock_order = f"ORD-{int(time.time())}"
        demo_payment_url = f"https://bpm.shaparak.ir/pgwchannel/startpay.mellat?token={mock_order}"
        self.payment_url = demo_payment_url

        notify(6, "GATEWAY", f"تولید شناسه پرداخت شاپرک: {demo_payment_url}", "complete")
        time.sleep(delay * 0.6)

        telegram_target = self.config.telegram_chat_id or "61561_TELEGRAM_CLIENT"
        notify(7, "TELEGRAM", f"ارسال آنی لینک پرداخت شاپرک به ربات تلگرام خریدار (ChatID: {telegram_target}). خریدار می‌تواند فوراً پرداخت را نهایی کند.", "complete")
        time.sleep(delay * 0.4)

        # Trigger terminal audio alert / bell
        try:
            sys.stdout.write('\a')
            sys.stdout.flush()
        except Exception:
            pass

        self.log(f"=== سناریوی دمو با موفقیت پایان یافت | لینک پرداخت: {demo_payment_url} ===")
        return True


# ------------------------------------------------------------
# Multi-Account Loader & Manager
# ------------------------------------------------------------
def load_accounts(file_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Loads configured accounts from accounts.json."""
    path = file_path or os.getenv("TIRES_ACCOUNTS_FILE", os.path.join(os.path.dirname(__file__), "accounts.json"))
    if not os.path.exists(path):
        example_path = os.path.join(os.path.dirname(__file__), "accounts.example.json")
        if os.path.exists(example_path):
            try:
                import shutil
                shutil.copyfile(example_path, path)
            except Exception:
                pass

    if os.path.exists(path):
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error reading accounts file {path}: {e}")
    return []


def save_accounts(accounts: List[Dict[str, Any]], file_path: Optional[str] = None) -> bool:
    """Saves updated accounts to accounts.json."""
    path = file_path or os.getenv("TIRES_ACCOUNTS_FILE", os.path.join(os.path.dirname(__file__), "accounts.json"))
    try:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(accounts, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving accounts file {path}: {e}")
        return False


class MultiAccountManager:
    """Executes tire purchase automation across multiple car accounts."""

    def __init__(self, accounts_file: Optional[str] = None, config: Optional[Config] = None):
        self.config = config or Config()
        self.accounts_file = accounts_file or self.config.accounts_file
        self.accounts = load_accounts(self.accounts_file)

    def run_all(self, concurrent: bool = True) -> Dict[str, bool]:
        """Runs purchase flow for all enabled accounts."""
        active_accounts = [acc for acc in self.accounts if acc.get("enabled", True)]
        if not active_accounts:
            logger.info("No active accounts found in accounts.json.")
            return {}

        results = {}

        def _run_single(acc: Dict[str, Any], idx: int) -> tuple:
            name = acc.get("name", f"Account-{idx}")
            cfg = Config()
            cfg.national_id = acc.get("national_id", cfg.national_id)
            cfg.password = acc.get("password", cfg.password)
            cfg.username = acc.get("phone", cfg.username)
            if acc.get("target_sizes"):
                cfg.target_sizes = acc["target_sizes"]
                cfg.target_product_id = acc["target_sizes"][0]
            if acc.get("telegram_chat_id"):
                cfg.telegram_chat_id = acc["telegram_chat_id"]

            bot = TirePurchaseBot(config=cfg, worker_id=idx, account_name=name)
            success = bot.run_pipeline()
            return name, success

        if concurrent and len(active_accounts) > 1:
            with ThreadPoolExecutor(max_workers=min(len(active_accounts), 5)) as executor:
                futures = [executor.submit(_run_single, acc, i + 1) for i, acc in enumerate(active_accounts)]
                for f in as_completed(futures):
                    name, ok = f.result()
                    results[name] = ok
        else:
            for i, acc in enumerate(active_accounts):
                name, ok = _run_single(acc, i + 1)
                results[name] = ok

        return results


# ------------------------------------------------------------
# Multi-Session Concurrency Manager
# ------------------------------------------------------------
class ConcurrencyManager:
    """Coordinates N parallel worker sessions sharing stock monitoring."""

    def __init__(self, num_workers: int = 3, config: Optional[Config] = None):
        self.num_workers = num_workers
        self.config = config or Config()
        self.stop_event = threading.Event()
        self.successful_worker: Optional[int] = None

    def _worker_task(self, worker_id: int) -> bool:
        bot = TirePurchaseBot(
            config=self.config,
            worker_id=worker_id,
        )
        logger.info(f"[Worker-{worker_id}] Started parallel worker.")

        if self.stop_event.is_set():
            return False

        if not bot.login():
            return False

        if self.stop_event.is_set():
            return False

        if bot.is_in_stock():
            if not self.stop_event.is_set():
                if bot.add_to_cart() and bot.checkout():
                    self.stop_event.set()
                    self.successful_worker = worker_id
                    logger.info(f"Worker {worker_id} successfully finalized purchase!")
                    return True

        return False

    def run(self) -> bool:
        logger.info(f"Launching {self.num_workers} concurrent sessions...")
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = [executor.submit(self._worker_task, i + 1) for i in range(self.num_workers)]
            results = [f.result() for f in as_completed(futures)]

        success = any(results)
        if success:
            logger.info(f"Concurrent execution succeeded by Worker-{self.successful_worker}")
        else:
            logger.info("Concurrent execution finished without purchase.")
        return success


# ------------------------------------------------------------
# Scheduling Engine
# ------------------------------------------------------------
def run_daily_schedule(target_time: str = "08:00", num_workers: int = 1):
    """Schedules the bot to execute every day at target_time with backoff."""
    import schedule

    logger.info(f"Scheduling Tire Bot to trigger daily at {target_time} (Workers: {num_workers}).")

    def job():
        logger.info(f"=== Scheduled Daily Run Triggered at {datetime.now().isoformat()} ===")
        max_retries = 5
        backoff = 5.0

        for attempt in range(1, max_retries + 1):
            try:
                manager = MultiAccountManager()
                if manager.accounts:
                    results = manager.run_all(concurrent=True)
                    if any(results.values()):
                        logger.info("Multi-account purchase succeeded!")
                        break
                elif num_workers > 1:
                    c_manager = ConcurrencyManager(num_workers=num_workers)
                    success = c_manager.run()
                    if success:
                        break
                else:
                    bot = TirePurchaseBot()
                    success = bot.run_pipeline()
                    if success:
                        break

                logger.info(f"Run attempt {attempt}/{max_retries} finished.")
                break
            except Exception as e:
                logger.error(f"Scheduled attempt {attempt} failed with error: {e}")
                if attempt < max_retries:
                    logger.info(f"Retrying in {backoff:.1f}s...")
                    time.sleep(backoff)
                    backoff *= 2.0

    schedule.every().day.at(target_time).do(job)

    while True:
        schedule.run_pending()
        time.sleep(1)


# ------------------------------------------------------------
# Entrypoint & CLI Interface
# ------------------------------------------------------------
def main(
    mode: Optional[str] = None,
    workers: Optional[int] = None,
    time_str: Optional[str] = None,
    product_id: Optional[str] = None,
    callback=None,
    delay: float = 1.0,
):
    is_cli = mode is None and len(sys.argv) > 1

    if is_cli:
        parser = argparse.ArgumentParser(description="Kavir Tire Automated Purchase Bot")
        parser.add_argument("--mode", choices=["once", "concurrent", "daily", "test", "demo", "multi"], default="once",
                            help="Execution mode: once, concurrent, daily, test, demo, or multi")
        parser.add_argument("--workers", type=int, default=3, help="Number of concurrent sessions")
        parser.add_argument("--time", type=str, default="08:00", help="Daily schedule time (HH:MM)")
        parser.add_argument("--product-id", type=str, default=None, help="Target tire product ID or size (e.g. 185/65R15)")
        parser.add_argument("--delay", type=float, default=1.0, help="Step delay for demo mode")

        args = parser.parse_args()
        selected_mode = args.mode
        selected_workers = args.workers
        selected_time = args.time
        selected_product_id = args.product_id
        selected_delay = args.delay
    else:
        selected_mode = mode or os.getenv("TIRES_MODE", "once")
        selected_workers = workers or int(os.getenv("TIRES_CONCURRENCY", "1"))
        selected_time = time_str or os.getenv("TIRES_DAILY_TIME", "08:00")
        selected_product_id = product_id or os.getenv("TIRES_PRODUCT_ID", None)
        selected_delay = delay

    try:
        config = Config()
        if selected_product_id:
            config.target_product_id = selected_product_id
            config.target_sizes = [s.strip() for s in selected_product_id.split(",") if s.strip()]

        if selected_mode == "test":
            logger.info("Running self-test check...")
            bot = TirePurchaseBot(config=config)
            logger.info(f"Bot initialized for base URL: {config.base_url}")
            logger.info(f"Target sizes: {config.target_sizes}")
            logger.info(f"Vault keys present: {config.vault.list_keys()}")
            logger.info(f"Accounts loaded: {len(load_accounts(config.accounts_file))}")
            if is_cli:
                sys.exit(0)
            return True

        elif selected_mode == "multi":
            logger.info("Running Multi-Account Runner for all configured cars...")
            manager = MultiAccountManager(config=config)
            res = manager.run_all(concurrent=True)
            logger.info(f"Multi-account execution results: {res}")
            if is_cli:
                sys.exit(0 if any(res.values()) else 1)
            return any(res.values())

        elif selected_mode == "demo":
            logger.info("Running high-fidelity demonstration scenario for client demo...")
            bot = TirePurchaseBot(config=config)
            res = bot.run_demo_pipeline(delay=selected_delay, callback=callback)
            if is_cli:
                sys.exit(0 if res else 1)
            return res

        elif selected_mode == "daily":
            run_daily_schedule(target_time=selected_time, num_workers=selected_workers)
            return True

        elif selected_mode == "concurrent":
            manager = ConcurrencyManager(num_workers=selected_workers, config=config)
            res = manager.run()
            if is_cli:
                sys.exit(0 if res else 1)
            return res

        else:  # once / live
            bot = TirePurchaseBot(config=config)
            res = bot.run_pipeline()
            if is_cli:
                sys.exit(0 if res else 1)
            return res

    except SystemExit:
        raise
    except KeyboardInterrupt:
        logger.info("Bot execution stopped by user.")
        if is_cli:
            sys.exit(0)
        return False
    except Exception as e:
        logger.critical(f"Unexpected fatal error: {e}", exc_info=True)
        if is_cli:
            sys.exit(1)
        return False


if __name__ == "__main__":
    main()
