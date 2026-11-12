# Installation & Usage Guide for the Tire Purchase Bot

## Prerequisites
- Linux/macOS (tested on Ubuntu 22.04, macOS 14) with **Python 3.14** or newer.
- Docker (optional, for containerised deployment).
- Access to the **Kavir Tire** website (no geo‑block or VPN required). If you are behind a geo‑restriction, configure a proxy (see *Proxy Configuration* below).
- Hermes vault set up with the following secrets (use `manage_connections` or the Hermes UI to store them):
  - `TIRES_USER` – login email/phone.
  - `TIRES_PASS` – password.
  - `TIRES_CARD_NUMBER`, `TIRES_CARD_EXP_MONTH`, `TIRES_CARD_EXP_YEAR`, `TIRES_CARD_CVC` – payment card details.
  - `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM`, `TWILIO_TO` – for OTP retrieval (optional, see *OTP Integration*).

## 1. Clone / Locate the Project
```bash
# The deliverable folder is already on the server
cd /home/ebi/freelance_engine/deliverables/tires_bot
```

## 2. Create a Python Virtual Environment (optional but recommended)
```bash
python3 -m venv venv
source venv/bin/activate
```

## 3. Install Python dependencies
```bash
pip install -r requirements.txt
```
*(If the `requirements.txt` is missing, you can generate it with `pip freeze > requirements.txt` after the above step.)*

## 4. Configure Environment Variables (or rely on the Hermes vault)
You may set the variables in a `.env` file next to the project:
```dotenv
TIRES_BASE_URL=https://kavir-tire.com
TIRES_MODE=once   # or "daily" for the 08:00 scheduler
# The rest are pulled automatically from the Hermes vault at runtime.
```
If you prefer to keep them in the vault, ensure the vault keys exist – the bot reads them with `browser_vault`.

## 5. Run the Bot (direct mode)
```bash
python -m tires_bot
```
- **once** – performs a single stock‑check and purchase attempt.
- **daily** – launches a persistent scheduler that runs every day at 08:00 am.

## 6. Run the Bot via Docker (containerised)
```bash
# Build the image
docker build -t tire-bot .
# Run the container (mount a volume for the vault key if you use one)
docker run -e TIRES_MODE=once \
    -e TIRES_BASE_URL=https://kavir-tire.com \
    --restart unless-stopped \
    tire-bot
```
### Proxy support (geo‑blocked sites)
If you encounter a `GeoBlockedError`, set the following env vars:
```dotenv
HTTP_PROXY=http://myproxy:3128
HTTPS_PROXY=http://myproxy:3128
NO_PROXY=localhost,127.0.0.1
```
The bot will raise `GeoBlockedError` and abort; the wrapper script can catch it and retry with a different proxy.

## 7. Logs & Monitoring
- Logs are written to `tires_bot.log` in the project root.
- For Docker, use `docker logs <container-id>`.
- The log includes timestamps, success/failure messages, and any OTP retrieval activity.

## 8. Running Tests
```bash
pytest -q
```
All 20 tests should pass. The test suite mocks the external HTTP calls, OTP service and vault access.

## 9. FAQ
| Issue | Solution |
|-------|----------|
| **Bot cannot login** | Verify that the credentials in the Hermes vault are correct and that the login endpoint (`LOGIN_ENDPOINT`) matches the site’s current API. |
| **OTP not received** | Ensure Twilio credentials are set and that the phone number (`TWILIO_TO`) can receive SMS. |
| **Geo‑blocked error** | Provide a working proxy (see *Proxy support*). |
| **Multiple browsers needed** | Set environment variable `TIRES_CONCURRENCY=N` (default 1). The bot will spawn N parallel sessions. |

---
*Enjoy automated tire purchases!*