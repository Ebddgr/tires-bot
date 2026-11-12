#!/usr/bin/env bash
# record_demo.sh – One-click launcher for recording Kavir Tire Bot demo video
# Opens Web Dashboard directly at http://localhost:5000

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
exec "$DIR/run_tire_bot.sh" web
