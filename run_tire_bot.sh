#!/usr/bin/env bash
# run_tire_bot.sh – Fast, Reliable Launcher for Kavir Tire Purchase Bot
# Deliverable for Parscoders Project 621604 (Client: Mehtiashrafi)

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# ---------- Colors & Formatting ----------
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log(){ echo -e "${GREEN}[INFO]${NC} $*"; }
warn(){ echo -e "${YELLOW}[WARN]${NC} $*"; }
err(){ echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------- 1. Detect Python & Venv ----------
PYTHON_BIN=""
if [ -f "$DIR/venv/bin/python" ]; then
  PYTHON_BIN="$DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  err "Python 3 is required but not found. Please install Python 3.10+."
  exit 1
fi

export PYTHONPATH="$DIR:$PYTHONPATH"

# ---------- 2. Check / Install Dependencies ----------
if [ ! -d "$DIR/venv" ]; then
  log "Creating local virtualenv..."
  if command -v uv >/dev/null 2>&1; then
    uv venv "$DIR/venv"
    uv pip install -r "$DIR/requirements.txt" --python "$DIR/venv/bin/python"
  else
    python3 -m venv "$DIR/venv"
    "$DIR/venv/bin/pip" install -r "$DIR/requirements.txt"
  fi
  PYTHON_BIN="$DIR/venv/bin/python"
fi

# ---------- Helper to open browser ----------
open_browser() {
  local url="$1"
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 &
  else
    log "لطفاً این آدرس را در مرورگر باز کنید: $url"
  fi
}

# ---------- 3. Handle Command Line Arguments ----------
CMD="${1:-menu}"

case "$CMD" in
  demo)
    log "اجرای سناریوی تست و ضبط ویدیو در ترمینال..."
    exec "$PYTHON_BIN" "$DIR/demo_scenario.py"
    ;;
  web|ui)
    log "راه‌اندازی سرور داشبورد گرافیکی (http://localhost:5000)..."
    open_browser "http://localhost:5000"
    exec "$PYTHON_BIN" "$DIR/ui.py" --host 0.0.0.0 --port 5000
    ;;
  test)
    log "اجرای آزمون‌های خودکار سامانه..."
    exec "$PYTHON_BIN" -m unittest discover -s "$DIR/tests"
    ;;
  live)
    log "اجرای ربات در حالت زنده..."
    exec "$PYTHON_BIN" "$DIR/tires_bot.py" --mode once
    ;;
  menu|*)
    echo -e "${CYAN}======================================================================${NC}"
    echo -e "${GREEN}      🛞 سامانه هوشمند اتوماسیون خرید لاستیک کویر تایر (نسخه تست)     ${NC}"
    echo -e "${CYAN}======================================================================${NC}"
    echo -e " لطفاً یک گزینه را انتخاب کنید:\n"
    echo -e " 1) ${YELLOW}راه‌اندازی داشبورد وب (پیشنهادی برای ضبط ویدیو)${NC} -> http://localhost:5000"
    echo -e " 2) ${GREEN}اجرای سناریوی تست در ترمینال (Terminal Demo)${NC}"
    echo -e " 3) ${CYAN}اجرای تست‌های خودکار (Self-Tests)${NC}"
    echo -e " 4) ${RED}اجرای ربات پایش زنده روی سایت کویر تایر (Live Mode)${NC}"
    echo -e " 5) خروج\n"
    
    read -p " شماره گزینه (پیش‌فرض 1): " CHOICE
    CHOICE="${CHOICE:-1}"

    case "$CHOICE" in
      1)
        log "راه‌اندازی داشبورد در مرورگر..."
        open_browser "http://localhost:5000"
        exec "$PYTHON_BIN" "$DIR/ui.py" --host 0.0.0.0 --port 5000
        ;;
      2)
        exec "$PYTHON_BIN" "$DIR/demo_scenario.py"
        ;;
      3)
        exec "$PYTHON_BIN" -m unittest discover -s "$DIR/tests"
        ;;
      4)
        exec "$PYTHON_BIN" "$DIR/tires_bot.py" --mode once
        ;;
      *)
        log "خروج."
        exit 0
        ;;
    esac
    ;;
esac
