"""
test_tires_bot.py - Unit test suite for Tire Purchase Bot.
Covers login, is_in_stock, add_to_cart, checkout, vault, and OTP retrieval.
"""

import os
import unittest
import tempfile
import requests_mock

from vault import Vault
from otp_service import extract_otp_code, MockOTPProvider, FileWebhookOTPProvider
from tires_bot import TirePurchaseBot, Config, ConcurrencyManager, GeoBlockedError


class TestVault(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_file = os.path.join(self.temp_dir.name, "test_vault.enc")
        self.master_key = "test_secret_master_key_12345678"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_vault_encryption_and_decryption(self):
        v1 = Vault(vault_path=self.vault_file, master_key=self.master_key)
        v1.set("TIRES_USER", "09129998877")
        v1.set("TIRES_PASS", "SuperSecurePass!#")
        v1.set("TIRES_CARD_NUMBER", "5022291012345678")

        # Reload fresh instance
        v2 = Vault(vault_path=self.vault_file, master_key=self.master_key)
        self.assertEqual(v2.get("TIRES_USER"), "09129998877")
        self.assertEqual(v2.get("TIRES_PASS"), "SuperSecurePass!#")
        self.assertEqual(v2.get("TIRES_CARD_NUMBER"), "5022291012345678")
        self.assertIn("TIRES_USER", v2.list_keys())

    def test_vault_fallback_to_env(self):
        os.environ["TIRES_TEST_ENV_KEY"] = "from_env_var"
        v = Vault(vault_path=self.vault_file, master_key=self.master_key)
        self.assertEqual(v.get("TIRES_TEST_ENV_KEY"), "from_env_var")
        self.assertEqual(v.get("NON_EXISTENT_KEY", "default_val"), "default_val")


class TestOTPService(unittest.TestCase):
    def test_extract_otp_code_english(self):
        text = "Your verification code is 849201. Do not share."
        self.assertEqual(extract_otp_code(text), "849201")

    def test_extract_otp_code_persian_numerals(self):
        text = "کد تایید کویرتایر شما: ۴۵۶۷۸۹ می‌باشد."
        self.assertEqual(extract_otp_code(text), "456789")

    def test_mock_otp_provider(self):
        provider = MockOTPProvider(static_code="987654")
        self.assertEqual(provider.fetch_otp(), "987654")

    def test_file_webhook_otp_provider(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as f:
            f.write("کد ورود: 712390")
            temp_path = f.name

        try:
            provider = FileWebhookOTPProvider(file_path=temp_path)
            code = provider.fetch_otp(timeout=5, poll_interval=1)
            self.assertEqual(code, "712390")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TestTirePurchaseBot(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_file = os.path.join(self.temp_dir.name, "test_vault.enc")
        self.vault = Vault(vault_path=self.vault_file, master_key="test_key_12345")
        self.vault.set_batch({
            "TIRES_BASE_URL": "https://test.kavirtire.ir",
            "TIRES_USER": "09120001122",
            "TIRES_PASS": "test_pass",
            "TIRES_NATIONAL_ID": "0011223344",
            "TIRES_PRODUCT_ID": "205/55R16",
            "TIRES_CARD_NUMBER": "6037991122334455",
            "TIRES_CARD_EXP_MONTH": "10",
            "TIRES_CARD_EXP_YEAR": "05",
            "TIRES_CARD_CVC": "789",
        })

        self.config = Config(vault=self.vault)
        self.otp_provider = MockOTPProvider(static_code="555123")
        self.bot = TirePurchaseBot(config=self.config, otp_provider=self.otp_provider)

    def tearDown(self):
        self.temp_dir.cleanup()

    @requests_mock.Mocker()
    def test_login_success(self, m):
        login_url = self.config.base_url + self.config.login_endpoint
        m.get(login_url, text='<html><meta name="csrf-token" content="mock_csrf_token_xyz"></html>')
        m.post(login_url, json={"status": "success", "token": "session_tok"})

        result = self.bot.login()
        self.assertTrue(result)
        self.assertTrue(self.bot.logged_in)
        self.assertEqual(self.bot.csrf_token, "mock_csrf_token_xyz")

    @requests_mock.Mocker()
    def test_login_failure(self, m):
        login_url = self.config.base_url + self.config.login_endpoint
        m.get(login_url, text='<html><body>Login Page</body></html>')
        m.post(login_url, status_code=401, json={"error": "Invalid credentials"})

        result = self.bot.login()
        self.assertFalse(result)
        self.assertFalse(self.bot.logged_in)

    @requests_mock.Mocker()
    def test_login_geoblocked_without_proxy(self, m):
        """Verifies that when Config.proxy is unset and login response contains geo-block phrase,
        the bot logs the warning and returns False without raising exceptions."""
        login_url = self.config.base_url + self.config.login_endpoint
        m.get(login_url, text='<html><body>Access is restricted to users from IRAN. Please connect from an Iranian IP.</body></html>')

        self.assertIsNone(self.config.proxy)
        # Must return False and not raise any exception
        result = self.bot.login()
        self.assertFalse(result)
        self.assertFalse(self.bot.logged_in)

    @requests_mock.Mocker()
    def test_login_wrong_credentials_is_not_a_false_success(self, m):
        """
        Regression: the Kavir login page contains the words "پروفایل" and "خرید"
        in its own help text, so text matching used to report a successful login
        even when the site bounced the POST straight back to /esale/login.
        A 302 back to the login page must be reported as a FAILURE.
        """
        base = self.config.base_url
        m.get(base + self.config.login_endpoint, text=(
            '<html><body><form action="' + base + '/esale/login">'
            '<input type="hidden" name="g-recaptcha-response">'
            '<p>اگر قبلاً ثبت‌نام کرده‌اید با کد ملی وارد پروفایل شوید و دکمه خرید نمایش داده می‌شود.</p>'
            '</form></body></html>'
        ))
        # Unauthenticated probe of the profile endpoint -> 302 to /esale
        m.get(base + self.config.profile_endpoint, status_code=302,
              headers={"Location": base + "/esale"})
        # Login POST bounces straight back to the login page
        m.post(base + self.config.login_endpoint, status_code=302,
               headers={"Location": base + "/esale/login"})

        self.assertFalse(self.bot.login())
        self.assertFalse(self.bot.logged_in)

    @requests_mock.Mocker()
    def test_login_reuses_valid_saved_session(self, m):
        """A saved cookie that passes the profile probe authenticates without re-POSTing."""
        base = self.config.base_url
        m.get(base + self.config.profile_endpoint, status_code=200, text="<html>پروفایل من</html>")

        self.assertTrue(self.bot.login())
        self.assertTrue(self.bot.logged_in)
        # No credential POST was needed
        self.assertEqual([r for r in m.request_history if r.method == "POST"], [])

    def test_verify_session_redirect_means_unauthenticated(self):
        """verify_session must treat any redirect to the login area as logged-out."""
        self.assertFalse(self.bot.verify_session())

    @requests_mock.Mocker()
    def test_verify_session_true_on_200(self, m):
        m.get(self.config.base_url + self.config.profile_endpoint, status_code=200, text="ok")
        self.assertTrue(self.bot.verify_session())

    @requests_mock.Mocker()
    def test_login_refuses_without_recaptcha_token(self, m):
        """reCAPTCHA-gated form + no token must fail fast instead of faking success."""
        base = self.config.base_url
        m.get(base + self.config.login_endpoint, text=(
            '<html><body><form><input type="hidden" name="g-recaptcha-response"></form>'
            '<p>ورود به پروفایل</p></body></html>'
        ))
        m.get(base + self.config.profile_endpoint, status_code=302,
              headers={"Location": base + "/esale"})

        self.assertFalse(self.bot.login())
        self.assertFalse(self.bot.logged_in)

    def test_config_geoblock_error_raises_when_proxy_unset(self):
        """Verifies that Config.__init__ raises a descriptive GeoBlockedError when geoblock_error is True and proxy is None."""
        temp_vault_file = os.path.join(self.temp_dir.name, "geoblock_vault.enc")
        v = Vault(vault_path=temp_vault_file, master_key="test_key_geoblock")
        v.set("TIRES_PROXY", None)

        with self.assertRaises(GeoBlockedError) as ctx:
            Config(vault=v, geoblock_error=True)
        self.assertIn("TIRES_PROXY", str(ctx.exception))
        self.assertIn("Iranian IPs", str(ctx.exception))

    def test_config_geoblock_with_proxy_does_not_raise(self):
        """Verifies that Config.__init__ succeeds without raising when a proxy is configured."""
        temp_vault_file = os.path.join(self.temp_dir.name, "geoblock_vault2.enc")
        v = Vault(vault_path=temp_vault_file, master_key="test_key_geoblock")
        v.set("TIRES_PROXY", "http://user:pass@iran-proxy.example.com:8080")

        cfg = Config(vault=v, geoblock_error=True)
        self.assertEqual(cfg.proxy, "http://user:pass@iran-proxy.example.com:8080")

    @requests_mock.Mocker()
    def test_is_in_stock_json_available(self, m):
        products_url = self.config.base_url + self.config.products_endpoint
        m.get(products_url, json={
            "products": [
                {"name": "تایر 205/55R16 کویر", "in_stock": True, "quantity": 4}
            ]
        })
        self.assertTrue(self.bot.is_in_stock("205/55R16"))

    @requests_mock.Mocker()
    def test_is_in_stock_html_available(self, m):
        products_url = self.config.base_url + self.config.products_endpoint
        html = """
        <div class="product-item">
            <span class="title">تایر سواری 205/55R16</span>
            <button class="add-to-cart">خرید آنلاین</button>
        </div>
        """
        m.get(products_url, text=html)
        self.assertTrue(self.bot.is_in_stock("205/55R16"))

    @requests_mock.Mocker()
    def test_is_in_stock_out_of_stock(self, m):
        products_url = self.config.base_url + self.config.products_endpoint
        m.get(products_url, text='<div class="product">205/55R16 - وضعیت: ناموجود</div>')
        self.assertFalse(self.bot.is_in_stock("205/55R16"))

    @requests_mock.Mocker()
    def test_add_to_cart_success(self, m):
        cart_url = self.config.base_url + self.config.cart_add_endpoint
        m.post(cart_url, status_code=200, json={"status": "success", "cart_id": 99})

        self.assertTrue(self.bot.add_to_cart("205/55R16", quantity=2))

    @requests_mock.Mocker()
    def test_add_to_cart_failure(self, m):
        cart_url = self.config.base_url + self.config.cart_add_endpoint
        m.post(cart_url, status_code=400, json={"error": "Limit exceeded"})

        self.assertFalse(self.bot.add_to_cart("205/55R16", quantity=2))

    @requests_mock.Mocker()
    def test_checkout_success(self, m):
        checkout_url = self.config.base_url + self.config.checkout_endpoint
        m.post(checkout_url, status_code=200, json={"status": "success", "order_id": "ORD-12345"})

        self.assertTrue(self.bot.checkout())

    @requests_mock.Mocker()
    def test_checkout_failure(self, m):
        checkout_url = self.config.base_url + self.config.checkout_endpoint
        m.post(checkout_url, status_code=422, json={"error": "Payment rejected"})

        self.assertFalse(self.bot.checkout())

    @requests_mock.Mocker()
    def test_full_pipeline_success(self, m):
        login_url = self.config.base_url + self.config.login_endpoint
        products_url = self.config.base_url + self.config.products_endpoint
        cart_url = self.config.base_url + self.config.cart_add_endpoint
        checkout_url = self.config.base_url + self.config.checkout_endpoint

        m.get(login_url, text='<html><meta name="csrf-token" content="csrf_val"></html>')
        m.post(login_url, json={"status": "success"})
        m.get(products_url, json={"items": [{"title": "205/55R16", "in_stock": True, "quantity": 2}]})
        m.post(cart_url, json={"status": "success"})
        m.post(checkout_url, json={"status": "success", "order_id": "ORD-OK"})

        self.assertTrue(self.bot.run_pipeline())

    @requests_mock.Mocker()
    def test_concurrency_manager(self, m):
        login_url = self.config.base_url + self.config.login_endpoint
        products_url = self.config.base_url + self.config.products_endpoint
        cart_url = self.config.base_url + self.config.cart_add_endpoint
        checkout_url = self.config.base_url + self.config.checkout_endpoint

        m.get(login_url, text='<html><meta name="csrf-token" content="token"></html>')
        m.post(login_url, json={"status": "success"})
        m.get(products_url, json={"items": [{"title": "205/55R16", "in_stock": True, "quantity": 4}]})
        m.post(cart_url, json={"status": "success"})
        m.post(checkout_url, json={"status": "success", "order_id": "ORD-CONC"})

        manager = ConcurrencyManager(num_workers=2, config=self.config)
        success = manager.run()
        self.assertTrue(success)

    def test_run_demo_pipeline(self):
        events = []
        def on_event(ev):
            events.append(ev)

        success = self.bot.run_demo_pipeline(delay=0.01, callback=on_event)
        self.assertTrue(success)
        self.assertGreaterEqual(len(events), 6)
        titles = [e["title"] for e in events]
        self.assertIn("INIT", titles)
        self.assertIn("MONITOR", titles)
        self.assertIn("STOCK", titles)
        self.assertIn("OTP", titles)
        self.assertIn("CART", titles)
        self.assertIn("GATEWAY", titles)
        self.assertIn("TELEGRAM", titles)

    def test_normalize_and_size_matching(self):
        from tires_bot import normalize_tire_size, size_matches
        self.assertEqual(normalize_tire_size("185/65 R15"), "18565R15")
        self.assertEqual(normalize_tire_size("۱۸۵/۶۵R۱۵"), "18565R15")
        self.assertTrue(size_matches("185/65R15", "لاستیک رادیال 185/65R15 کویرتایر"))
        self.assertTrue(size_matches("185/65R15", "تایر سواری 185-65-15"))
        self.assertFalse(size_matches("185/65R15", "تایر 205/60R15"))

    @requests_mock.Mocker()
    def test_telegram_alert_dispatch(self, m):
        from tires_bot import send_telegram_alert
        tg_url = "https://api.telegram.org/bot123456:ABC-DEF/sendMessage"
        m.post(tg_url, json={"ok": True, "result": {"message_id": 999}})

        ok = send_telegram_alert(
            payment_url="https://bpm.shaparak.ir/pay/123",
            national_id="0012345678",
            product_id="185/65R15",
            bot_token="123456:ABC-DEF",
            chat_id="987654321",
            account_name="خودرو تستی"
        )
        self.assertTrue(ok)
        self.assertTrue(m.called)
        self.assertIn("185/65R15", m.last_request.text)
        self.assertIn("https://bpm.shaparak.ir/pay/123", m.last_request.text)

    def test_multi_account_loader_and_save(self):
        from tires_bot import load_accounts, save_accounts
        temp_acc_file = os.path.join(self.temp_dir.name, "test_accounts.json")
        sample_data = [
            {"name": "خودرو ۱", "national_id": "001122", "password": "pass", "target_sizes": ["185/65R15"], "enabled": True}
        ]
        self.assertTrue(save_accounts(sample_data, temp_acc_file))
        loaded = load_accounts(temp_acc_file)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["name"], "خودرو ۱")

    def test_rate_limiter_shares_one_slot_queue_per_host(self):
        """Two bots for the same host must share one limiter (no Nx request rate)."""
        from tires_bot import RateLimiter

        RateLimiter.reset_shared()
        a = RateLimiter.for_host("https://kavirtire.ir")
        b = RateLimiter.for_host("https://kavirtire.ir")
        c = RateLimiter.for_host("https://example.com")
        self.assertIs(a, b, "Same host must reuse one shared limiter")
        self.assertIsNot(a, c, "Different hosts must not share a limiter")
        RateLimiter.reset_shared()

    def test_rate_limiter_enforces_minimum_gap(self):
        """RateLimiter must never allow two requests closer than min_interval."""
        import time as _time
        from tires_bot import RateLimiter

        rl = RateLimiter(min_interval=1.5, jitter=0.0)
        start = _time.monotonic()
        rl.wait()   # first slot is immediate
        rl.wait()   # second must wait ~1.5s
        elapsed = _time.monotonic() - start
        self.assertGreaterEqual(elapsed, 1.45,
                                f"Requests were only {elapsed:.2f}s apart, expected >=1.5s")

    def test_rate_limiter_clamps_below_1_5s(self):
        """A caller asking for a sub-1.5s interval must be clamped up to 1.5s."""
        from tires_bot import RateLimiter
        rl = RateLimiter(min_interval=0.2, jitter=0.0)
        self.assertEqual(rl.min_interval, 1.5)

    def test_rate_limiter_429_triggers_progressive_backoff(self):
        """A 429 response must push the next allowed slot into the future."""
        import time as _time
        from tires_bot import RateLimiter

        rl = RateLimiter(min_interval=1.5, jitter=0.0)
        rl.on_response(429)
        self.assertGreater(rl._next_allowed, _time.monotonic(),
                           "429 did not arm a cool-down window")
        first_backoff = rl._next_allowed - _time.monotonic()
        rl.on_response(429)
        second_backoff = rl._next_allowed - _time.monotonic()
        self.assertGreater(second_backoff, first_backoff,
                           "Repeated 429 did not escalate the cool-down")
        rl.on_response(200)
        self.assertEqual(rl._consecutive_429, 0)

    def test_rate_limiter_is_thread_safe(self):
        """Concurrent workers must not collapse onto the same request slot."""
        import threading as _threading
        import time as _time
        from tires_bot import RateLimiter

        rl = RateLimiter(min_interval=1.5, jitter=0.0)
        stamps = []
        lock = _threading.Lock()

        def worker():
            rl.wait()
            with lock:
                stamps.append(_time.monotonic())

        threads = [_threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stamps.sort()
        self.assertEqual(len(stamps), 2)
        self.assertGreaterEqual(stamps[1] - stamps[0], 1.45,
                                "Two threads obtained overlapping request slots")

    @requests_mock.Mocker()
    def test_run_live_monitor_stops_at_max_cycles(self, m):
        """Live monitor must keep polling while out of stock and stop at the cap."""
        login_url = self.config.base_url + self.config.login_endpoint
        products_url = self.config.base_url + self.config.products_endpoint
        m.get(login_url, text='<html><meta name="csrf-token" content="tok"></html>')
        m.post(login_url, json={"status": "success"})
        m.get(products_url, text="<html><body>انبار خالی است</body></html>")

        self.bot.rate_limiter.min_interval = 0.0
        self.bot.rate_limiter.jitter = 0.0

        events = []
        result = self.bot.run_live_monitor(max_cycles=3, callback=events.append)

        self.assertFalse(result)
        statuses = [e["status"] for e in events]
        self.assertIn("start", statuses)
        self.assertIn("waiting", statuses)
        self.assertIn("exhausted", statuses)
        self.assertEqual(statuses.count("waiting"), 3)

    @requests_mock.Mocker()
    def test_run_live_monitor_buys_when_stock_appears(self, m):
        """Live monitor must run the purchase pipeline the moment stock appears."""
        login_url = self.config.base_url + self.config.login_endpoint
        products_url = self.config.base_url + self.config.products_endpoint
        cart_url = self.config.base_url + self.config.cart_add_endpoint
        checkout_url = self.config.base_url + self.config.checkout_endpoint

        m.get(login_url, text='<html><meta name="csrf-token" content="tok"></html>')
        m.post(login_url, json={"status": "success"})
        # Match the size the bot is actually configured to watch (from the test vault).
        size = self.config.target_sizes[0]
        m.get(products_url, text=(
            f'<html><body><div>{size} '
            '<button class="product-add-button" wire:click="add">خرید</button></div></body></html>'
        ))
        m.post(cart_url, json={"status": "success", "cart_id": 99})
        m.post(checkout_url, json={"status": "success", "payment_url": "https://bpm.shaparak.ir/pay/live999"})

        self.bot.rate_limiter.min_interval = 0.0
        self.bot.rate_limiter.jitter = 0.0

        events = []
        result = self.bot.run_live_monitor(max_cycles=5, callback=events.append)

        self.assertTrue(result)
        statuses = [e["status"] for e in events]
        self.assertIn("stock_found", statuses)
        self.assertIn("success", statuses)

    @requests_mock.Mocker()
    def test_run_live_monitor_honours_stop_event(self, m):
        """A set stop_event must end the loop before any further polling."""
        import threading as _threading
        login_url = self.config.base_url + self.config.login_endpoint
        m.get(login_url, text='<html><meta name="csrf-token" content="tok"></html>')
        m.post(login_url, json={"status": "success"})

        self.bot.rate_limiter.min_interval = 0.0
        self.bot.rate_limiter.jitter = 0.0

        stop = _threading.Event()
        stop.set()
        events = []
        result = self.bot.run_live_monitor(max_cycles=10, callback=events.append, stop_event=stop)

        self.assertFalse(result)
        self.assertIn("stopped", [e["status"] for e in events])


if __name__ == "__main__":
    unittest.main()
