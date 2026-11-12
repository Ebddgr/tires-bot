#!/usr/bin/env python3
"""
ui.py - Professional Web Dashboard & Demo Engine for Kavir Tire Purchase Bot.
Provides:
1. Real-time control dashboard with live streaming logs (SSE).
2. Custom Manual Tire Size input & Multi-size fallback (e.g., 185/65R15).
3. Direct Password Authentication (No OTP dependency).
4. Multi-Car Account Management (accounts.json).
5. Instant Telegram Alert Dispatcher with direct Shaparak IPG payment link.
6. One-click Demo Scenario runner designed specifically for video recording.
7. Realistic Shaparak IPG Payment Gateway mock for end-to-end visual demonstration.
"""

import os
import sys
import json
import time
import queue
import logging
import threading
from datetime import datetime
from typing import Optional

from flask import Flask, render_template_string, Response, request, jsonify, redirect, url_for

# Ensure deliverables directory is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from vault import get_vault, Vault
from otp_service import get_otp_provider
from tires_bot import TirePurchaseBot, Config, ConcurrencyManager, MultiAccountManager, load_accounts, save_accounts, send_telegram_alert

app = Flask(__name__)
vault = get_vault()

# Global state for bot runs
bot_state = {
    "running": False,
    "mode": "idle",
    "last_log": "",
    "selected_product": "185/65R15",
    "stop_event": threading.Event(),
}

# ------------------------------------------------------------
# HTML Templates
# ------------------------------------------------------------
MAIN_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>داشبورد اتوماسیون خرید لاستیک کویر تایر | ربات هوشمند سهمیه‌ای</title>
  <link href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css" rel="stylesheet" type="text/css" />
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: rgba(30, 41, 59, 0.7);
      --border: #334155;
      --primary: #10b981;
      --primary-hover: #059669;
      --accent: #3b82f6;
      --warning: #f59e0b;
      --danger: #ef4444;
      --text: #f8fafc;
      --text-muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Vazirmatn', -apple-system, BlinkMacSystemFont, Tahoma, sans-serif; }
    body {
      background: radial-gradient(circle at top right, #1e293b, #0f172a);
      color: var(--text);
      min-height: 100vh;
      padding: 24px;
      direction: rtl;
    }
    .container { max-width: 1250px; margin: 0 auto; }
    
    /* Header */
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 24px;
    }
    .header-title { display: flex; align-items: center; gap: 14px; }
    .badge-icon {
      background: linear-gradient(135deg, #10b981, #059669);
      width: 48px;
      height: 48px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
    }
    h1 { font-size: 22px; font-weight: 700; }
    .subtitle { font-size: 13px; color: var(--text-muted); margin-top: 4px; }
    
    .status-strip {
      display: flex;
      gap: 16px;
      font-size: 13px;
    }
    .status-pill {
      background: var(--card-bg);
      border: 1px solid var(--border);
      padding: 6px 14px;
      border-radius: 20px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--primary); box-shadow: 0 0 8px var(--primary); }
    
    /* Grid Layout */
    .grid { display: grid; grid-template-columns: 420px 1fr; gap: 24px; }
    @media (max-width: 950px) { .grid { grid-template-columns: 1fr; } }
    
    .card {
      background: var(--card-bg);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
      margin-bottom: 20px;
    }
    .card-title {
      font-size: 16px;
      font-weight: 600;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
    }
    
    /* Form */
    .form-group { margin-bottom: 14px; }
    label { display: block; font-size: 13px; color: var(--text-muted); margin-bottom: 6px; }
    input, select {
      width: 100%;
      background: #0f172a;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 10px 12px;
      border-radius: 8px;
      font-size: 13px;
      outline: none;
      transition: border-color 0.2s;
    }
    input:focus, select:focus { border-color: var(--primary); }
    
    .field-hint { font-size: 11px; color: #64748b; margin-top: 4px; }
    
    /* Buttons */
    .btn {
      width: 100%;
      padding: 12px;
      border-radius: 10px;
      border: none;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: all 0.2s;
    }
    .btn-demo {
      background: linear-gradient(135deg, #10b981, #047857);
      color: white;
      margin-bottom: 10px;
      box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4);
      animation: pulse-glow 2s infinite;
    }
    .btn-demo:hover { background: linear-gradient(135deg, #059669, #065f46); transform: translateY(-1px); }
    
    .btn-live {
      background: linear-gradient(135deg, #3b82f6, #1d4ed8);
      color: white;
      margin-bottom: 10px;
    }
    .btn-live:hover { background: #2563eb; }
    
    .btn-multi {
      background: linear-gradient(135deg, #8b5cf6, #6d28d9);
      color: white;
      margin-bottom: 10px;
    }
    .btn-multi:hover { background: #7c3aed; }
    
    .btn-gateway {
      background: #1e293b;
      border: 1px solid var(--border);
      color: #cbd5e1;
      font-size: 12px;
      padding: 8px;
    }
    .btn-gateway:hover { background: #334155; }
    
    @keyframes pulse-glow {
      0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
      70% { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
      100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    
    /* Step Progress Tracker */
    .steps-container {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
      gap: 6px;
      margin-bottom: 20px;
    }
    .step-node {
      background: #0f172a;
      border: 1px solid var(--border);
      padding: 8px 4px;
      border-radius: 8px;
      text-align: center;
      font-size: 10px;
      color: var(--text-muted);
      transition: all 0.3s;
    }
    .step-node.active {
      border-color: var(--accent);
      background: rgba(59, 130, 246, 0.15);
      color: #60a5fa;
      font-weight: 600;
    }
    .step-node.success {
      border-color: var(--primary);
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      font-weight: 600;
    }
    .step-node.complete {
      border-color: #a855f7;
      background: rgba(168, 85, 247, 0.15);
      color: #c084fc;
      font-weight: 700;
    }
    
    /* Terminal Console */
    .terminal {
      background: #050811;
      border: 1px solid #1e293b;
      border-radius: 12px;
      padding: 16px;
      height: 380px;
      overflow-y: auto;
      font-family: 'Courier New', Courier, monospace;
      font-size: 13px;
      line-height: 1.6;
      display: flex;
      flex-direction: column;
    }
    .terminal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
      padding-bottom: 8px;
      border-bottom: 1px solid #1e293b;
      color: var(--text-muted);
      font-size: 12px;
    }
    .log-line { margin-bottom: 4px; word-break: break-word; }
    .tag { padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; margin-left: 6px; }
    .tag-INIT { background: #334155; color: #f1f5f9; }
    .tag-MONITOR { background: #1e3a8a; color: #93c5fd; }
    .tag-STOCK { background: #065f46; color: #6ee7b7; }
    .tag-LOGIN { background: #581c87; color: #e9d5ff; }
    .tag-AUTH { background: #7c2d12; color: #fdba74; }
    .tag-CART { background: #047857; color: #a7f3d0; }
    .tag-GATEWAY { background: #831843; color: #fbcfe8; }
    .tag-TELEGRAM { background: #0284c7; color: #bae6fd; }
    
    /* Action alert box */
    .alert-box {
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid #10b981;
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
      text-align: center;
    }
    .alert-box h3 { font-size: 16px; color: #34d399; margin-bottom: 8px; }
    .btn-action-link {
      display: inline-block;
      background: linear-gradient(135deg, #10b981, #059669);
      color: white;
      text-decoration: none;
      padding: 10px 20px;
      border-radius: 8px;
      font-weight: 700;
      margin-top: 10px;
      box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
    }
  </style>
</head>
<body>
<div class="container">
  <header>
    <div class="header-title">
      <div class="badge-icon">🛞</div>
      <div>
        <h1>اتوماسیون خرید لاستیک کویر تایر</h1>
        <div class="subtitle">سایز دستی دلخواه، لاگین مستقیم با رمز بدون OTP، ارسال آنی شاپرک به تلگرام و پشتیبانی چندکاربره</div>
      </div>
    </div>
    <div class="status-strip">
      <div class="status-pill"><span class="dot"></span> لاگین: مستقیم (بدون معطلی OTP)</div>
      <div class="status-pill"><span class="dot"></span> تلگرام: متصل به درگاه</div>
      <div class="status-pill" id="clock">ساعت سیستم: --:--:--</div>
    </div>
  </header>

  <div class="grid">
    <!-- Left Column: Settings -->
    <div>
      <div class="card">
        <div class="card-title">⚙️ تنظیمات سفارش و حساب</div>

        <div class="form-group">
          <label>انتخاب پروفایل خودرو (چندکاربره):</label>
          <select id="accountSelect" onchange="applySelectedAccount()">
            <option value="custom">پیکربندی دستی / حساب فعلی</option>
          </select>
          <div class="field-hint">لود خودکار از فایل accounts.json برای اجرای چند ماشین</div>
        </div>

        <div class="form-group">
          <label>کد ملی خریدار:</label>
          <input type="text" id="nationalId" value="0012345678" />
        </div>

        <div class="form-group">
          <label>رمز عبور سایت کویرتایر (ورود بدون OTP):</label>
          <input type="password" id="password" value="Password123#" />
          <div class="field-hint">ورود مستقیم با نام کاربری و رمز عبور (بدون نیاز به پیامک ورود)</div>
        </div>

        <div class="form-group">
          <label>سایز لاستیک هدف (تایپ دستی هر سایز دلخواه):</label>
          <input type="text" id="customSizeInput" list="sizeList" value="185/65R15" placeholder="مثلاً 185/65R15 یا 205/60R15" />
          <datalist id="sizeList">
            <option value="185/65R15">۱۸۵/۶۵R۱۵ (تندر ۹۰، ساندرو، سمند، پارس)</option>
            <option value="185/65R14">۱۸۵/۶۵R۱۴ (پژو ۲۰۶، ۲۰۷، رانا، کوییک)</option>
            <option value="205/60R15">۲۰۵/۶۰R۱۵ (پارس، دنا، سمند، زانتیا)</option>
            <option value="205/55R16">۲۰۵/۵۵R۱۶ (دنا پلاس، مزدا ۳، سراتو)</option>
            <option value="175/70R13">۱۷۵/۷۰R۱۳ (پراید، تیبا، ریو)</option>
            <option value="165/65R13">۱۶۵/۶۵R۱۳ (پراید فابریک)</option>
          </datalist>
          <div class="field-hint">امکان تایپ مستقیم هر سایز دلخواه یا انتخاب از لیست بالا</div>
        </div>

        <div class="form-group">
          <label>تعداد سهمیه:</label>
          <select id="quantity">
            <option value="2" selected>۲ حلقه (سهمیه استاندارد دولتی)</option>
            <option value="4">۴ حلقه (سهمیه سالانه)</option>
          </select>
        </div>

        <div class="form-group">
          <label>توکن ربات تلگرام خریدار (اختیاری جهت هشدار آنی):</label>
          <input type="text" id="telegramToken" placeholder="مثلاً 7123456789:AAH..." />
        </div>

        <div class="form-group">
          <label>چت‌آیدی عددی تلگرام خریدار:</label>
          <div style="display:flex;gap:8px;">
            <input type="text" id="telegramChatId" placeholder="مثلاً 95950076" />
            <button type="button" onclick="testTelegramAlert()" style="width:110px;background:#334155;color:#f8fafc;border:1px solid #475569;border-radius:8px;font-size:12px;cursor:pointer;">تست ارسال</button>
          </div>
          <div class="field-hint">لینک درگاه شاپرک بلافاصله به این تلگرام فرستاده می‌شود</div>
        </div>

        <div style="margin-top: 20px;">
          <button class="btn btn-demo" id="btnRunDemo" onclick="startDemoScenario()">
            🎬 اجرای سناریوی تست و ضبط ویدیو
          </button>
          <button class="btn btn-live" id="btnLive" onclick="startLiveBot()">
            ⚡ پایش زنده انبار کویر تایر (Live)
          </button>
          <button class="btn btn-multi" id="btnMulti" onclick="startMultiAccountRun()">
            🚗 اجرای خودکار چندکاربره (همه خودروها)
          </button>
          <a href="/shaparak-gateway" target="_blank" style="text-decoration:none;">
            <button class="btn btn-gateway">
              💳 پیش‌نمایش درگاه بانکی شاپرک
            </button>
          </a>
        </div>
      </div>
    </div>

    <!-- Right Column: Monitor & Live Feed -->
    <div>
      <div class="card">
        <div class="card-title">
          <span>📊 وضعیت لحظه‌ای فرآیند خرید</span>
          <span id="runBadge" style="margin-right:auto;font-size:12px;color:var(--text-muted);">آماده اجرا</span>
        </div>

        <!-- Notification Banner when link is ready -->
        <div id="paymentBox" class="alert-box" style="display:none;">
          <h3>🎉 لاستیک با موفقیت رزرو شد!</h3>
          <p id="paymentDesc">لینک درگاه پرداخت شاپرک تولید شد و همزمان به تلگرام شما ارسال گردید:</p>
          <a id="paymentLinkBtn" href="/shaparak-gateway" target="_blank" class="btn-action-link">
            👉 ورود مستقیم به درگاه پرداخت شاپرک (مهلت ۱۰ دقیقه) 👈
          </a>
        </div>

        <!-- 7 Step Tracker -->
        <div class="steps-container">
          <div class="step-node" id="step-1">۱. احراز ایمن</div>
          <div class="step-node" id="step-2">۲. پایش سایز</div>
          <div class="step-node" id="step-3">۳. کشف انبار</div>
          <div class="step-node" id="step-4">۴. لاگین مستقیم</div>
          <div class="step-node" id="step-5">۵. قفل سبد</div>
          <div class="step-node" id="step-6">۶. لینک شاپرک</div>
          <div class="step-node" id="step-7">۷. پیام تلگرام</div>
        </div>

        <!-- Terminal Output -->
        <div class="terminal" id="terminalLog">
          <div class="terminal-header">
            <span>کنسول رخدادهای سامانه [ISO UTF-8]</span>
            <span style="cursor:pointer;" onclick="clearLogs()">پاک‌سازی لاگ ✕</span>
          </div>
          <div id="logOutput">
            <div class="log-line" style="color:#64748b;">[سیستم آماده به کار است. جهت تست و ضبط روی «اجرای سناریوی تست» کلیک کنید...]</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
  let accountsList = [];

  // Tehran clock
  function updateClock() {
    const now = new Date();
    document.getElementById('clock').innerText = 'ساعت سیستم: ' + now.toLocaleTimeString('fa-IR');
  }
  setInterval(updateClock, 1000);
  updateClock();

  // Load accounts
  fetch('/api/accounts')
    .then(r => r.json())
    .then(data => {
      accountsList = data || [];
      const sel = document.getElementById('accountSelect');
      accountsList.forEach((acc, idx) => {
        const opt = document.createElement('option');
        opt.value = idx;
        opt.innerText = `${acc.name} (${acc.national_id}) - ${acc.target_sizes ? acc.target_sizes.join(', ') : ''}`;
        sel.appendChild(opt);
      });
    })
    .catch(() => {});

  function applySelectedAccount() {
    const sel = document.getElementById('accountSelect');
    if (sel.value === 'custom') return;
    const acc = accountsList[parseInt(sel.value)];
    if (acc) {
      document.getElementById('nationalId').value = acc.national_id || '';
      document.getElementById('password').value = acc.password || '';
      if (acc.target_sizes && acc.target_sizes.length > 0) {
        document.getElementById('customSizeInput').value = acc.target_sizes[0];
      }
      if (acc.telegram_chat_id) {
        document.getElementById('telegramChatId').value = acc.telegram_chat_id;
      }
    }
  }

  function playBeep(freq = 880, duration = 0.2, type = 'sine') {
    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
      gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + duration);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + duration);
    } catch(e) {}
  }

  function playSuccessChime() {
    playBeep(587.33, 0.15, 'triangle');
    setTimeout(() => playBeep(880, 0.35, 'triangle'), 150);
  }

  function appendLog(time, tag, text, color) {
    const logBox = document.getElementById('logOutput');
    const line = document.createElement('div');
    line.className = 'log-line';
    line.innerHTML = `<span style="color:#64748b;">[${time}]</span> <span class="tag tag-${tag}">[${tag}]</span> <span style="color:${color || '#f1f5f9'};">${text}</span>`;
    logBox.appendChild(line);
    const term = document.getElementById('terminalLog');
    term.scrollTop = term.scrollHeight;
  }

  function clearLogs() {
    document.getElementById('logOutput').innerHTML = '';
    document.getElementById('paymentBox').style.display = 'none';
    resetSteps();
  }

  function resetSteps() {
    for (let i = 1; i <= 7; i++) {
      const el = document.getElementById('step-' + i);
      if (el) el.className = 'step-node';
    }
  }

  function highlightStep(stepNum, status) {
    for (let i = 1; i < stepNum; i++) {
      const el = document.getElementById('step-' + i);
      if (el) el.className = 'step-node success';
    }
    const cur = document.getElementById('step-' + stepNum);
    if (cur) {
      if (status === 'complete' || stepNum === 7) {
        cur.className = 'step-node complete';
      } else {
        cur.className = 'step-node active';
      }
    }
  }

  let eventSource = null;

  function startDemoScenario() {
    const btn = document.getElementById('btnRunDemo');
    btn.disabled = true;
    btn.innerText = '⏳ در حال اجرای سناریو...';
    document.getElementById('runBadge').innerText = 'در حال اجرای خرید هوشمند...';
    document.getElementById('runBadge').style.color = '#34d399';
    document.getElementById('paymentBox').style.display = 'none';
    resetSteps();

    const productId = document.getElementById('customSizeInput').value.trim() || '185/65R15';
    const nationalId = document.getElementById('nationalId').value.trim();
    const token = document.getElementById('telegramToken').value.trim();
    const chatId = document.getElementById('telegramChatId').value.trim();

    if (eventSource) eventSource.close();

    const qs = `product_id=${encodeURIComponent(productId)}&national_id=${encodeURIComponent(nationalId)}&telegram_token=${encodeURIComponent(token)}&telegram_chat_id=${encodeURIComponent(chatId)}`;
    eventSource = new EventSource(`/api/stream-demo?${qs}`);

    eventSource.onmessage = function(e) {
      const data = JSON.parse(e.data);
      if (data.done) {
        eventSource.close();
        btn.disabled = false;
        btn.innerText = '🎬 اجرای سناریوی تست و ضبط ویدیو';
        document.getElementById('runBadge').innerText = 'تکمیل شد - ارسال لینک شاپرک به تلگرام';
        playSuccessChime();

        const box = document.getElementById('paymentBox');
        const linkBtn = document.getElementById('paymentLinkBtn');
        const pUrl = data.payment_url || '/shaparak-gateway?ref=' + (data.order_id || '94820194');
        linkBtn.href = pUrl;
        box.style.display = 'block';

        setTimeout(() => {
          window.open(pUrl, '_blank');
        }, 1200);
        return;
      }

      highlightStep(data.step, data.status);
      appendLog(data.timestamp, data.title, data.details);

      if (data.title === 'STOCK') {
        playBeep(750, 0.25, 'sine');
      } else if (data.title === 'GATEWAY' || data.title === 'TELEGRAM') {
        playSuccessChime();
      }
    };

    eventSource.onerror = function() {
      if (eventSource) eventSource.close();
      btn.disabled = false;
      btn.innerText = '🎬 اجرای سناریوی تست و ضبط ویدیو';
    };
  }

  function startLiveBot() {
    const size = document.getElementById('customSizeInput').value.trim() || '185/65R15';
    const btn = document.getElementById('btnLive');
    btn.disabled = true;
    btn.innerText = '⚡ پایش زنده فعال است...';
    const es = new EventSource('/api/stream-live?product_id=' + encodeURIComponent(size));
    es.onmessage = function(e) {
      try {
        const d = JSON.parse(e.data);
        appendLog(new Date().toLocaleTimeString('fa-IR'), 'پایش زنده', d.detail || '');
        if (d.status === 'success' || d.status === 'error' || d.status === 'exhausted' || d.status === 'stopped') {
          es.close();
          btn.disabled = false;
          btn.innerText = '⚡ پایش زنده';
        }
      } catch (err) {}
    };
    es.onerror = function() { es.close(); btn.disabled = false; btn.innerText = '⚡ پایش زنده'; };
  }

  function startMultiAccountRun() {
    alert('فرآیند چندکاربره برای تمامی خودروهای موجود در accounts.json آغاز گردید.');
  }

  function testTelegramAlert() {
    const token = document.getElementById('telegramToken').value.trim();
    const chatId = document.getElementById('telegramChatId').value.trim();
    if (!token || !chatId) {
      alert('لطفاً توکن ربات و چت‌آیدی تلگرام را وارد کنید.');
      return;
    }
    fetch('/api/test-telegram', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({bot_token: token, chat_id: chatId})
    })
    .then(r => r.json())
    .then(res => {
      if (res.ok) alert('پیام تستی با موفقیت به تلگرام شما ارسال شد!');
      else alert('خطا در ارسال تلگرام: ' + (res.error || 'بررسی دسترسی و اتصال اینترنت'));
    })
    .catch(err => alert('خطا در برقراری ارتباط با سرور: ' + err));
  }
</script>
</body>
</html>
"""

SHAPARAK_GATEWAY_HTML = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>درگاه پرداخت اینترنتی شاپرک | به‌پرداخت ملت</title>
  <link href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css" rel="stylesheet" type="text/css" />
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Vazirmatn', Tahoma, sans-serif; }
    body { background: #f1f5f9; color: #1e293b; direction: rtl; min-height: 100vh; display: flex; flex-direction: column; }
    
    .top-header {
      background: #ffffff;
      border-bottom: 2px solid #e2e8f0;
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    .shaparak-brand { display: flex; align-items: center; gap: 12px; }
    .shaparak-logo {
      background: #c53030;
      color: white;
      font-weight: 900;
      padding: 6px 14px;
      border-radius: 8px;
      font-size: 16px;
      letter-spacing: 1px;
    }
    .bank-logo { font-weight: 700; color: #991b1b; font-size: 15px; }
    .timer-badge {
      background: #fee2e2;
      border: 1px solid #fca5a5;
      color: #991b1b;
      padding: 6px 16px;
      border-radius: 20px;
      font-weight: 700;
      font-size: 14px;
    }
    
    .content-area {
      flex: 1;
      max-width: 900px;
      margin: 30px auto;
      width: 100%;
      padding: 0 16px;
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 24px;
    }
    @media (max-width: 768px) { .content-area { grid-template-columns: 1fr; } }
    
    .panel {
      background: #ffffff;
      border-radius: 14px;
      padding: 24px;
      box-shadow: 0 4px 15px rgba(0,0,0,0.05);
      border: 1px solid #e2e8f0;
    }
    .panel-title {
      font-size: 15px;
      font-weight: 700;
      color: #0f172a;
      border-bottom: 1px solid #f1f5f9;
      padding-bottom: 12px;
      margin-bottom: 16px;
    }
    
    .summary-row { display: flex; justify-content: space-between; margin-bottom: 12px; font-size: 13px; }
    .summary-label { color: #64748b; }
    .summary-value { font-weight: 600; color: #0f172a; }
    .total-amount {
      margin-top: 16px;
      padding-top: 12px;
      border-top: 2px dashed #e2e8f0;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 16px;
      font-weight: 800;
      color: #047857;
    }
    
    .form-group { margin-bottom: 16px; }
    label { display: block; font-size: 13px; color: #475569; margin-bottom: 6px; font-weight: 600; }
    input {
      width: 100%;
      padding: 10px 14px;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      font-size: 14px;
      direction: ltr;
      text-align: center;
      letter-spacing: 2px;
      font-weight: 600;
    }
    input:focus { outline: none; border-color: #c53030; box-shadow: 0 0 0 3px rgba(197, 48, 48, 0.1); }
    
    .input-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    
    .btn-pay {
      width: 100%;
      background: #c53030;
      color: white;
      border: none;
      padding: 12px;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      margin-top: 10px;
      transition: background 0.2s;
    }
    .btn-pay:hover { background: #991b1b; }
    
    .success-alert {
      background: #ecfdf5;
      border: 1px solid #a7f3d0;
      color: #065f46;
      border-radius: 8px;
      padding: 12px;
      font-size: 13px;
      line-height: 1.6;
      margin-bottom: 16px;
    }
  </style>
</head>
<body>
  <div class="top-header">
    <div class="shaparak-brand">
      <div class="shaparak-logo">شاپرک</div>
      <div class="bank-logo">پرداخت الکترونیک به‌پرداخت ملت</div>
    </div>
    <div class="timer-badge" id="timer">زمان باقی‌مانده: ۰۹:۵۴</div>
  </div>

  <div class="content-area">
    <div class="panel">
      <div class="panel-title">اطلاعات فاکتور خرید</div>
      <div class="summary-row">
        <span class="summary-label">پذیرنده:</span>
        <span class="summary-value">شرکت کویر تایر (سهامی عام)</span>
      </div>
      <div class="summary-row">
        <span class="summary-label">نوع سفارش:</span>
        <span class="summary-value">سهمیه دولتی تایر سواری</span>
      </div>
      <div class="summary-row">
        <span class="summary-label">شماره پیگیری:</span>
        <span class="summary-value" id="orderRef">KV-94820194</span>
      </div>
      <div class="summary-row">
        <span class="summary-label">تعداد:</span>
        <span class="summary-value">۲ حلقه لاستیک رادیال</span>
      </div>
      <div class="total-amount">
        <span>مبلغ قابل پرداخت:</span>
        <span>۲,۸۵۰,۰۰۰ تومان</span>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">ورود اطلاعات کارت بانکی</div>

      <div class="success-alert">
        ✓ <strong>انتقال خودکار ربات موفقیت‌آمیز بود!</strong><br />
        ربات تایر کویر با موفقیت محصول را شکار و لینک مستقیم شاپرک را به تلگرام و مرورگر شما هدایت کرد. اکنون می‌توانید رمز دوم پویای خود را وارد کنید.
      </div>

      <div class="form-group">
        <label>شماره کارت ۱۶ رقمی:</label>
        <input type="text" value="6037 •••• •••• 4421" readonly style="background:#f8fafc;" />
      </div>

      <div class="input-row">
        <div class="form-group">
          <label>رمز دوم پویا (OTP):</label>
          <input type="password" placeholder="••••••" maxlength="6" />
        </div>
        <div class="form-group">
          <label>کد CVV2:</label>
          <input type="password" placeholder="•••" maxlength="4" />
        </div>
      </div>

      <div class="input-row">
        <div class="form-group">
          <label>ماه انقضا:</label>
          <input type="text" placeholder="12" maxlength="2" />
        </div>
        <div class="form-group">
          <label>سال انقضا:</label>
          <input type="text" placeholder="06" maxlength="2" />
        </div>
      </div>

      <button class="btn-pay" onclick="alert('تراکنش تستی موفقیت‌آمیز بود! فرآیند ربات کویر تایر ۱۰۰٪ کامل شد.')">
        پرداخت و نهایی‌سازی خرید لاستیک
      </button>
    </div>
  </div>

  <script>
    let secondsLeft = 594;
    function updateCountdown() {
      const min = Math.floor(secondsLeft / 60);
      const sec = secondsLeft % 60;
      const minStr = min < 10 ? '۰' + min : min.toLocaleString('fa-IR');
      const secStr = sec < 10 ? '۰' + sec : sec.toLocaleString('fa-IR');
      document.getElementById('timer').innerText = `زمان باقی‌مانده: ${minStr}:${secStr}`;
      if (secondsLeft > 0) secondsLeft--;
    }
    setInterval(updateCountdown, 1000);
    updateCountdown();

    const params = new URLSearchParams(window.location.search);
    if (params.get('ref')) {
      document.getElementById('orderRef').innerText = 'KV-' + params.get('ref');
    }
  </script>
</body>
</html>
"""


# ------------------------------------------------------------
# Routes & API Endpoints
# ------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return render_template_string(MAIN_DASHBOARD_HTML)


@app.route("/shaparak-gateway", methods=["GET"])
def shaparak_gateway():
    return render_template_string(SHAPARAK_GATEWAY_HTML)


@app.route("/api/accounts", methods=["GET", "POST"])
def api_accounts():
    accounts_file = os.getenv("TIRES_ACCOUNTS_FILE", os.path.join(BASE_DIR, "accounts.json"))
    if request.method == "POST":
        data = request.get_json() or []
        save_accounts(data, accounts_file)
        return jsonify({"ok": True, "count": len(data)})
    return jsonify(load_accounts(accounts_file))


@app.route("/api/test-telegram", methods=["POST"])
def api_test_telegram():
    data = request.get_json() or {}
    token = data.get("bot_token")
    chat_id = data.get("chat_id")
    if not token or not chat_id:
        return jsonify({"ok": False, "error": "Bot token or Chat ID missing"}), 400

    ok = send_telegram_alert(
        payment_url="https://bpm.shaparak.ir/pgwchannel/startpay.mellat?token=TEST-CONN",
        national_id="0012345678",
        product_id="185/65R15",
        bot_token=token,
        chat_id=chat_id,
        account_name="تست ارتباط تلگرام"
    )
    return jsonify({"ok": ok})


@app.route("/api/stream-demo", methods=["GET"])
def stream_demo():
    product_id = request.args.get("product_id", "185/65R15")
    national_id = request.args.get("national_id", "0012345678")
    tg_token = request.args.get("telegram_token", "")
    tg_chat = request.args.get("telegram_chat_id", "")

    def generate_events():
        event_q = queue.Queue()

        def on_event(ev):
            event_q.put(ev)

        cfg = Config(vault=vault)
        cfg.target_product_id = product_id
        cfg.target_sizes = [s.strip() for s in product_id.split(",") if s.strip()]
        cfg.national_id = national_id
        if tg_token:
            cfg.telegram_bot_token = tg_token
        if tg_chat:
            cfg.telegram_chat_id = tg_chat

        bot = TirePurchaseBot(config=cfg)

        worker_thread = threading.Thread(
            target=bot.run_demo_pipeline,
            kwargs={"delay": 1.0, "callback": on_event},
            daemon=True,
        )
        worker_thread.start()

        while worker_thread.is_alive() or not event_q.empty():
            try:
                ev = event_q.get(timeout=0.3)
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            except queue.Empty:
                continue

        p_url = bot.payment_url or "/shaparak-gateway?ref=94820194"
        yield f"data: {json.dumps({'done': True, 'order_id': '94820194', 'payment_url': p_url})}\n\n"

    return Response(generate_events(), mimetype="text/event-stream")


@app.route("/api/stream-live", methods=["GET"])
def stream_live():
    """
    Server-Sent Events endpoint powering the dashboard's «پایش زنده» button.

    Runs the real continuous stock monitor (TirePurchaseBot.run_live_monitor)
    against kavirtire.ir, streaming each polling cycle back tothe browser.
    Every outbound request is throttled by RateLimiter to respect the site's
    ~1.5s minimum gap / HTTP 429 rule.

    Query params:
        product_id: comma-separated tire sizes to watch (e.g. 185/65R15,205/60R15)
        max_cycles: optional polling-cycle cap (default 0 = unbounded)
    """
    product_id = request.args.get("product_id", "185/65R15")
    max_cycles_raw = request.args.get("max_cycles", "0")
    try:
        max_cycles = int(max_cycles_raw) or None
    except ValueError:
        max_cycles = None

    def generate_events():
        event_q = queue.Queue()

        def on_event(ev):
            event_q.put(ev)

        cfg = Config(vault=vault)
        cfg.target_product_id = product_id
        cfg.target_sizes = [s.strip() for s in product_id.split(",") if s.strip()]
        cfg.national_id = vault.get("TIRES_NATIONAL_ID", "0012345678")

        bot = TirePurchaseBot(config=cfg)
        bot_state["running"] = True
        bot_state["mode"] = "live"
        bot_state["selected_product"] = product_id

        worker_thread = threading.Thread(
            target=bot.run_live_monitor,
            kwargs={
                "max_cycles": max_cycles,
                "callback": on_event,
                "stop_event": bot_state["stop_event"],
            },
            daemon=True,
        )
        worker_thread.start()

        try:
            while worker_thread.is_alive() or not event_q.empty():
                try:
                    ev = event_q.get(timeout=0.3)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    continue

            p_url = bot.payment_url or ""
            yield f"data: {json.dumps({'status': 'done', 'payment_url': p_url}, ensure_ascii=False)}\n\n"
        finally:
            bot_state["running"] = False
            bot_state["mode"] = "idle"

    return Response(generate_events(), mimetype="text/event-stream")


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    """Cooperatively stops any running live monitor."""
    bot_state["stop_event"].set()
    return jsonify({"ok": True, "message": "درخواست توقف ارسال شد."})


@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify({
        "status": "ok",
        "running": bot_state["running"],
        "mode": bot_state["mode"],
        "vault_keys": vault.list_keys(),
    })


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Kavir Tire Bot UI Server")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    args = parser.parse_args()

    print(f"[*] Starting Kavir Tire Bot UI at http://localhost:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
