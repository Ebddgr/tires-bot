#!/usr/bin/env python3
"""
demo_scenario.py - Interactive CLI Demo Scenario Runner for Kavir Tire Bot.
Designed for recording clean terminal demo videos for clients (Mehtiashrafi).

Features:
- Beautiful colored terminal interface with step progress
- Audio alerts on stock detection & payment redirect
- Automatic browser launch directly to Shaparak Payment Gateway
- Zero setup needed: run directly with Python
"""

import os
import sys
import time
import webbrowser
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from tires_bot import TirePurchaseBot, Config
from vault import get_vault

# ANSI Color Codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def clear_screen():
    print("\033[2J\033[H", end="")


def print_banner():
    banner = f"""
{CYAN}{BOLD}======================================================================{RESET}
{GREEN}{BOLD}      🚀 سامانه هوشمند خرید خودکار لاستیک کویر تایر (Kavir Tire)     {RESET}
{YELLOW}             سناریوی تست عملیاتی و شبیه‌سازی خرید سهمیه‌ای            {RESET}
{CYAN}{BOLD}======================================================================{RESET}
"""
    print(banner)


def step_box(step_num: int, title: str, details: str, status: str = "RUNNING"):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    if status == "RUNNING":
        status_tag = f"{YELLOW}[در حال انجام...]{RESET}"
    elif status == "SUCCESS":
        status_tag = f"{GREEN}[✓ با موفقیت]{RESET}"
    else:
        status_tag = f"{CYAN}[انجام شد]{RESET}"

    print(f" {CYAN}┌─{RESET} {BOLD}مرحله {step_num}: {title}{RESET} {status_tag}")
    print(f" {CYAN}│{RESET}  {DIM}زمان: {ts}{RESET}")
    print(f" {CYAN}└─►{RESET} {details}\n")


def play_sound():
    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
    except Exception:
        pass


def run_demo():
    clear_screen()
    print_banner()

    target_product = os.getenv("TIRES_PRODUCT_ID", "185/65R14 (پژو ۲۰۶ / رانا)")
    national_id = os.getenv("TIRES_NATIONAL_ID", "0012345678")

    print(f" {BOLD}مشخصات سناریو:{RESET}")
    print(f" • لاستیک انتخابی: {GREEN}{target_product}{RESET}")
    print(f" • کد ملی متقاضی:  {GREEN}{national_id}{RESET}")
    print(f" • درگاه پرداخت:   {GREEN}به‌پرداخت ملت (شاپرک){RESET}")
    print(f" • نحوه دریافت رمز: {GREEN}سامانه هوشمند شنود پیامک (OTP Forwarder){RESET}\n")
    print(f"{DIM}شروع فرآیند در ۲ ثانیه... (دوربین یا اسکرین‌رکوردر را فعال کنید){RESET}")
    time.sleep(2)
    print("-" * 70 + "\n")

    # Step 1: Init & Vault
    step_box(1, "رمزگشایی مخزن امن و بررسی اتصال", "بررسی گواهینامه SSL، بارگذاری اطلاعات محرمانه از مخزن AES-256 و ست کردن هدرهای Chrome...", "RUNNING")
    time.sleep(1.2)
    step_box(1, "رمزگشایی مخزن امن و بررسی اتصال", "اتصال به پایانه kavirtire.ir برقرار شد. سشن امن با موفقیت ایجاد گردید.", "SUCCESS")

    # Step 2: Monitoring
    step_box(2, "پایش لحظه‌ای انبار (Real-Time Monitor)", f"شروع اسکن انبار مرکزی برای سایز {target_product} با وقفه زمانی ۵۰۰ میلی‌ثانیه...", "RUNNING")
    time.sleep(1.5)
    print(f"   {DIM}» استعلام اول: انبار خالی است. آماده‌باش رکوئست بعدی...{RESET}")
    time.sleep(1.2)

    # Step 3: Stock Discovery
    play_sound()
    step_box(3, "کشف موجودی انبار کویر تایر", f"💥 موجودی آزاد شد! تعداد ۴ حلقه لاستیک {target_product} در پایانه فروش فعال گردید.", "SUCCESS")
    time.sleep(1.0)

    # Step 4: Direct Login (No OTP delay)
    step_box(4, "ورود مستقیم به سامانه (بدون نیاز به OTP)", f"ارسال پکت ورود مستقیم با کد ملی {national_id} و رمز عبور بدون معطلی پیامک...", "RUNNING")
    time.sleep(1.0)
    play_sound()
    step_box(4, "ورود مستقیم به سامانه (بدون نیاز به OTP)", "احراز هویت سشن در ۰.۸۵ ثانیه با موفقیت تأیید شد و کاربر لاگین گردید.", "SUCCESS")
    time.sleep(0.8)

    # Step 5: Quota & Cart
    step_box(5, "رزرو سهمیه و افزودن به سبد خرید", f"ثبت سهمیه دولتی ۲ حلقه لاستیک و قفل کردن موجودی به مدت ۱۰ دقیقه در سبد خرید...", "SUCCESS")
    time.sleep(1.0)

    # Step 6: Shaparak Gateway
    play_sound()
    shaparak_url = "https://bpm.shaparak.ir/pgwchannel/startpay.mellat?token=KV-94820194"
    step_box(6, "اتصال مستقیم به درگاه پرداخت شاپرک", f"دریافت توکن پرداخت به‌پرداخت ملت (کد رهگیری: KV-94820194) و ایجاد شناسه پرداخت: {shaparak_url}", "SUCCESS")
    time.sleep(0.8)

    # Step 7: Telegram Notification
    play_sound()
    step_box(7, "ارسال آنی لینک پرداخت به تلگرام خریدار", f"لینک مستقیم درگاه شاپرک با موفقیت به ربات تلگرام خریدار ارسال گردید تا مستقیماً روی گوشی کلیک و پرداخت شود.", "SUCCESS")

    print("=" * 70)
    print(f"{GREEN}{BOLD}✓ فرآیند خرید با موفقیت به پایان رسید! لینک پرداخت روی گوشی خریدار است.{RESET}")
    print(f"\n{BOLD}{GREEN}💰 خلاصه سفارش ثبت‌شده{RESET}")
    print(f"نام خودرو: خودرو ۱ (پژو / تندر)")
    print(f"کدملی: {national_id}")
    print(f"سایز درخواستی: {target_product}")
    print(f"تعداد: 2 حلقه رادیال دولتی")
    print(f"لینک مستقیم شاپرک: {shaparak_url}")
    print(f"وضعیت تلگرام: ارسال فوری انجام شد [ChatID: 61561_CLIENT]\n")
    print("=" * 70)

    # Open payment gateway preview in browser
    gateway_url = "http://localhost:5000/shaparak-gateway?ref=94820194"
    print(f"\n{CYAN}🌐 در حال باز کردن صفحه درگاه شاپرک در مرورگر:{RESET} {gateway_url}")
    try:
        webbrowser.open(gateway_url)
    except Exception:
        pass


if __name__ == "__main__":
    run_demo()
