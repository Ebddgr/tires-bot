# Kavir Tire Automated Purchase Bot (ربات هوشمند خرید لاستیک کویر تایر)

A production-grade, highly resilient automation bot engineered to monitor stock, bypass queue congestion via multi-session concurrency, automatically resolve 2-FA OTP verification, and finalize tire purchases on the Kavir Tire (`kavirtire.ir/esale`) portal.

---

## 🌟 Key Features

1. **Native Kavir Tire Integration**:
   - Tailored for `kavirtire.ir` e-sale endpoints (`/esale/auth/login`, `/esale/products`, `/esale/cart/add`, `/esale/checkout`).
   - Automated CSRF token parsing (`meta[name="csrf-token"]`, `_token`, and cookie session tokens).
   - Real-browser HTTP headers, keep-alive connection pooling, and exponential backoff retry adapters.

2. **Secure AES-256 Vault (`vault.py`)**:
   - Zero plaintext credentials stored in code or repository.
   - Master key derivation via PBKDF2HMAC (SHA-256, 100,000 iterations) and authenticated encryption via AES-256-GCM.
   - CLI tool for credential lifecycle management (`set`, `get`, `list`).

3. **Autonomous OTP Retrieval (`otp_service.py`)**:
   - Automatically acquires 2-FA SMS / Email verification codes without human intervention.
   - Built-in providers:
     - **Twilio**: Direct SMS API polling.
     - **Gmail IMAP**: Scans incoming unread verification emails.
     - **Kavenegar**: Direct Iranian telecom SMS API gateway.
     - **File / Webhook**: Watches an incoming SMS forwarder stream (`.otp_inbox.txt`).
     - **Mock**: For automated testing, CI, and dry runs.
   - Automatic normalization of Persian/Arabic digits (۰-۹ to 0-9) and regex extraction.

4. **Multi-Session Concurrency Manager**:
   - Spawns $N$ isolated worker sessions running in parallel threads.
   - Each worker operates its own `requests.Session` with separate cookie jars and TCP connections.
   - Thread-safe cooperative stop event immediately halts sibling workers when one session secures stock and purchases the tire.

5. **Precision Daily Scheduler**:
   - Automated daily trigger at 08:00 AM (local time) using the `schedule` library.
   - Exponential back-off retry loop when the server encounters network dropouts or rate limits (HTTP 502/503/429).

6. **Production Logging**:
   - `TimedRotatingFileHandler` rotating daily at midnight with a 7-day backup retention.
   - Output structured with ISO timestamps, worker/thread tags, and log levels.

7. **Docker Ready**:
   - `Dockerfile` (Python 3.11 slim) with `Asia/Tehran` timezone configuration and non-root security context.
   - Ready-to-run `docker-compose.yml`.

---

## 📁 Project Structure

```
├── tires_bot.py         # Main execution engine, concurrency manager & scheduler
├── vault.py             # AES-256 encrypted credential vault CLI and library
├── otp_service.py       # Pluggable OTP retrieval providers (Twilio, Gmail, Kavenegar, File, Mock)
├── tests/
│   └── test_tires_bot.py # Comprehensive unit test suite (17 tests, requests-mock)
├── requirements.txt     # Pinned Python package dependencies
├── Dockerfile           # Containerization image definition
├── docker-compose.yml   # Multi-service container orchestration
├── README.md            # Detailed documentation (English & Persian)
└── venv/                # Local Python 3.14 virtual environment
```

---

## 🚀 Quick Start Guide

### 1. Environment Setup

```bash
cd /home/ebi/freelance_engine/deliverables/tires_bot

# Activate existing virtual environment
source venv/bin/activate

# Or install dependencies in a fresh environment
pip install -r requirements.txt
```

### 2. Configure Credentials in Encrypted Vault

Use `vault.py` to securely store your credentials without exposing them in environment files:

```bash
# Set credentials securely
python vault.py set TIRES_USER "09121234567"
python vault.py set TIRES_PASS "YourSecretPassword"
python vault.py set TIRES_NATIONAL_ID "0012345678"
python vault.py set TIRES_PRODUCT_ID "185/65R14"

# Set payment card details
python vault.py set TIRES_CARD_NUMBER "6037991122334455"
python vault.py set TIRES_CARD_EXP_MONTH "12"
python vault.py set TIRES_CARD_EXP_YEAR "06"
python vault.py set TIRES_CARD_CVC "321"

# Verify configured keys
python vault.py list
```

### 3. Iranian IP & Proxy Configuration (Crucial)

> **⚠️ Geo-Restriction Notice**: Kavir Tire (`kavirtire.ir/esale`) strictly restricts access to **Iranian IP addresses**. Access attempts from overseas servers, standard non-IR cloud providers, or foreign VPNs are blocked with the message: `Access is restricted to users from IRAN`.

If you are running the bot from a server located outside Iran, you **must configure an Iranian proxy** using `TIRES_PROXY`:

```bash
# Configure Iranian proxy in the encrypted vault
python vault.py set TIRES_PROXY "http://username:password@iran-proxy.example.com:8080"

# Or configure via environment variable
export TIRES_PROXY="http://username:password@iran-proxy.example.com:8080"
```

#### Supported Proxy Formats:
- **HTTP Proxy with authentication**: `http://username:password@proxy.example.ir:8080`
- **Standard HTTP Proxy**: `http://185.200.x.x:8080`
- **SOCKS5 Proxy**: `socks5://username:password@proxy.example.ir:1080` or `socks5h://...`

#### Geo-Block Handling & Exit Codes:
- When running unattended or scheduled, if `TIRES_PROXY` is unset and a geo-block response is received, the bot logs an informative warning (`Site is geo-blocked (Iran IP required)...`) and completes the run with **exit code 0** (normal flow), preventing false alarm alerts on cron and monitoring tools.
- Unexpected fatal exceptions will exit with a non-zero exit code (`1`).

### 4. Configure OTP Retrieval

Set `TIRES_OTP_PROVIDER` in your environment or vault:

- **Mock (Default/Test)**:
  ```bash
  python vault.py set TIRES_OTP_PROVIDER "mock"
  python vault.py set TIRES_MOCK_OTP "123456"
  ```

- **SMS Forwarder (Android / Webhook)**:
  Configure an SMS forwarder app on your phone to append incoming SMS text to `.otp_inbox.txt`:
  ```bash
  python vault.py set TIRES_OTP_PROVIDER "file"
  python vault.py set TIRES_OTP_FILE "/path/to/.otp_inbox.txt"
  ```

- **Twilio**:
  ```bash
  python vault.py set TIRES_OTP_PROVIDER "twilio"
  python vault.py set TWILIO_ACCOUNT_SID "ACxxxxxxxx"
  python vault.py set TWILIO_AUTH_TOKEN "xxxxxxxx"
  python vault.py set TWILIO_PHONE_NUMBER "+1xxxxxxxx"
  ```

- **Gmail IMAP**:
  ```bash
  python vault.py set TIRES_OTP_PROVIDER "gmail"
  python vault.py set GMAIL_USER "your_email@gmail.com"
  python vault.py set GMAIL_APP_PASSWORD "xxxx xxxx xxxx xxxx"
  ```

### 5. Running the Bot

#### Mode A: Single Instant Attempt
```bash
python tires_bot.py --mode once --product-id "185/65R14"
```

#### Mode B: Concurrent Multi-Worker Mode
Spawns 5 parallel browser sessions to maximize cart acquisition speed:
```bash
python tires_bot.py --mode concurrent --workers 5 --product-id "185/65R14"
```

#### Mode C: Daily Scheduled Mode (Runs at 08:00 AM)
```bash
python tires_bot.py --mode daily --time 08:00 --workers 3
```

#### Mode D: Self-Diagnostic Test
```bash
python tires_bot.py --mode test
```

---

## 🇮🇷 راهنمای استفاده به زبان فارسی (Persian Guide)

این ربات به صورت کاملاً اختصاصی برای ثبت نام و خرید اینترنتی لاستیک دولتی از درگاه **کویر تایر** (`kavirtire.ir/esale`) طراحی شده است.

### مراحل راه‌اندازی:
1. **فعالسازی محیط مجازی**:
   ```bash
   source venv/bin/activate
   ```
2. **تنظیم پروکسی ایران (الزامی در صورت اجرا از سرورهای خارج از کشور)**:
   سایت کویر تایر دسترسی کاربران خارج از ایران را مسدود می‌کند (`Access is restricted to users from IRAN`). در صورت استقرار ربات روی سرورهای خارجی یا کلود، تنظیم پروکسی ایران الزامی است:
   ```bash
   python vault.py set TIRES_PROXY "http://username:password@iran-proxy.example.com:8080"
   # یا به صورت متغیر محیطی:
   export TIRES_PROXY="http://username:password@iran-proxy.example.com:8080"
   ```
3. **ثبت امن اطلاعات در گاوصندوق رمزنگاری شده (Vault)**:
   جهت حفظ امنیت، رمز عبور و اطلاعات کارت بانکی در کد ذخیره نمی‌شوند و با استاندارد AES-256 رمزنگاری می‌گردند:
   ```bash
   python vault.py set TIRES_USER "شماره موبایل یا نام کاربری"
   python vault.py set TIRES_PASS "رمز عبور"
   python vault.py set TIRES_NATIONAL_ID "کد ملی ۱۰ رقمی"
   python vault.py set TIRES_PRODUCT_ID "185/65R14"  # سایز یا شناسه تایر
   python vault.py set TIRES_CARD_NUMBER "شماره کارت ۱۶ رقمی"
   python vault.py set TIRES_CARD_EXP_MONTH "10"
   python vault.py set TIRES_CARD_EXP_YEAR "06"
   python vault.py set TIRES_CARD_CVC "123"
   ```
4. **تنظیم خودکار دریافت پیامک کد تایید (OTP)**:
   - ربات قابلیت دریافت پیامک کد تایید از طریق ایمیل، فورواردر فایل متنی گوشی، یا وب‌هوک را داراست و فرآیند خرید را بدون نیاز به تایپ دستی تکمیل می‌کند.
5. **اجرای چندگانه (Concurrency)**:
   برای غلبه بر ترافیک سنگین سایت در ساعت بازگشایی، ربات می‌تواند چندین نشست همزمان ارسال کند:
   ```bash
   python tires_bot.py --mode concurrent --workers 3
   ```
6. **زمان‌بندی روزانه راس ساعت ۸ صبح**:
   ```bash
   python tires_bot.py --mode daily --time 08:00
   ```

---

## 🧪 Testing & Verification

Run the full self-contained unit test suite covering mock HTTP requests, OTP extraction, AES-256 vault encryption, and geo-block handling:

```bash
PYTHONPATH=. /home/ebi/freelance_engine/deliverables/tires_bot/venv/bin/python -m unittest discover -s tests -v
```

All 20 tests pass out-of-the-box:
- Login authentication (success, failure, and geo-block handling)
- Geo-block detection without proxy (graceful False return with exit code 0)
- Config GeoBlockedError exception verification
- Product stock verification (JSON and HTML selectors)
- Out of stock detection ("ناموجود")
- Cart addition & CSRF handling
- Payment submission & OTP integration
- AES-256 Vault encryption & decryption round-trips
- Concurrent multi-session thread coordination

---

## 🐳 Docker Deployment

```bash
# Build and run with docker-compose
docker-compose up -d

# Inspect live logs
docker-compose logs -f
```
