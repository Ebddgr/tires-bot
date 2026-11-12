#!/usr/bin/env python3
"""
import_session.py - Import a logged-in Kavir Tire browser session into the bot.

Why this exists
---------------
kavirtire.ir/esale/login is now protected by Google reCAPTCHA v3 and asks for the
national ID only. A headless bot cannot solve reCAPTCHA, so the supported way to
authenticate is to log in once in a real browser and hand the resulting session
cookie to the bot through kavir_session.json.

Usage
-----
1. Log in at https://kavirtire.ir/esale/login in Chrome/Firefox and confirm you
   reach your profile page.
2. Grab the two cookies `kavirtire_session` and `XSRF-TOKEN`
   (DevTools > Application > Cookies, or any cookie-export extension) and write
   them into cookies.txt, one `name=value` pair per line:

       kavirtire_session=eyJpdiI6...
       XSRF-TOKEN=eyJpdiI6...

   (Alternatively pass a JSON object on stdin: {"kavirtire_session": "...", ...})
3. Run:

       python import_session.py cookies.txt

   The script writes kavir_session.json and immediately proves it with a real
   request to /esale/profile. It prints "SESSION VALID" only if the site
   actually answered 200 - a rejected cookie is never reported as success.
"""

import json
import os
import sys

from tires_bot import Config, TirePurchaseBot


def parse_cookies_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read().strip()

    if not raw:
        raise ValueError("cookie file is empty")

    # JSON object form
    if raw.startswith("{"):
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items() if v}

    cookies = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"line is not a name=value pair: {line[:40]}")
        name, value = line.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    source = argv[1]
    try:
        cookies = parse_cookies_file(source)
    except Exception as exc:
        print(f"ERROR: could not read cookies from {source}: {exc}")
        return 2

    if not cookies:
        print("ERROR: no cookies parsed")
        return 2

    if "kavirtire_session" not in cookies:
        print("WARNING: 'kavirtire_session' cookie not found - login will most likely fail.")

    session_file = os.getenv(
        "TIRES_SESSION_FILE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "kavir_session.json"),
    )

    config = Config()
    bot = TirePurchaseBot(config=config)

    # Apply the supplied cookies, then validate before persisting.
    for name, value in cookies.items():
        bot.session.cookies.set(name, value)

    if not bot.verify_session():
        print(
            "SESSION INVALID: kavirtire.ir answered the profile probe with a redirect.\n"
            "The cookie is expired or was copied incompletely. Log in again in the browser\n"
            "and copy the fresh kavirtire_session value."
        )
        return 1

    with open(session_file, "w", encoding="utf-8") as fh:
        json.dump(cookies, fh, indent=2)

    print(f"SESSION VALID - verified against {config.base_url}{config.profile_endpoint}")
    print(f"Saved {len(cookies)} cookie(s) to {session_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
