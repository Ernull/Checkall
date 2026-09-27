import os
import shutil
import asyncio
import json
import base64
import requests
import time
import uuid
import random
import re
from urllib.parse import urlparse, quote, unquote
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ==========================================
# تنظیمات پایه
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
PROXY_URL = os.getenv("PROXY_URL")  # اختیاری: لینک دریافت خودکار پروکسی در زمان شروع

if not BOT_TOKEN:
    raise ValueError("❌ مقدار BOT_TOKEN پیدا نشد!")

router = Router()

SESSION_BASE_DIR = "bot_sessions"
if os.path.exists(SESSION_BASE_DIR):
    shutil.rmtree(SESSION_BASE_DIR, ignore_errors=True)
os.makedirs(SESSION_BASE_DIR, exist_ok=True)

# ---------------- وضعیت‌ها و کیبورد ----------------
class BotStates(StatesGroup):
    waiting_for_sync_links = State()
    waiting_for_delete_links = State()
    waiting_for_discount_links = State()
    waiting_for_cart_report_links = State()
    waiting_for_proxies = State()

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛒 همگام‌سازی سبد خرید")],
        [KeyboardButton(text="📦 گزارش موجودی سبد خرید"), KeyboardButton(text="🔎 بررسی تخفیف‌ها")],
        [KeyboardButton(text="🗑 پاک کردن آدرس‌ها"), KeyboardButton(text="🌐 تنظیم / بروزرسانی پروکسی")]
    ],
    resize_keyboard=True
)

# ---------------- لیست پروکسی‌های پیش‌فرض ----------------
RAW_DEFAULT_PROXIES = [
    "http://Eyi7eecyfihd:pe1rm71fd72ka0k@209.50.177.175:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.6.98:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.15.99:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.47.48:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.35.213:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.160.216:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.51.133:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.180.169:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.232.240:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.52.87:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.251.136:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.191.84:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.28.133:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.37.181:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.224.92:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.255.106:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.47.128:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.38.17:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.170.180:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.172.165:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.37.53:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.169.0:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.227.194:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.53.50:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.180.78:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.188.218:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.249.209:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.33.21:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.39.129:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.191.208:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.186.116:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.167.19.176:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.58.95:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.13.165:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.32.145:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.33.227:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.45.178:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.38.33:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.47.195:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@217.181.91.121:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.44.69:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.230.228:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.53.28:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.187.186:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.235.149:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.174.138:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.37.105:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.37.240:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.40.40:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.56.236:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.242.198:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.34.203:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.171.62:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.239.126:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.169.3:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.244.93:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.53.140:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@217.181.91.129:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.44.251:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.173.23:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.46.156:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.245.137:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.8.250:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.162.29:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.243.249:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.232.50:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@193.56.28.28:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.13.253:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.242.2:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.34.129:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.29.199:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.42.143:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.29.224:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.36.239:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.4.143:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.14.79:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.1.18:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.54.229:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.42.147:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.227.153:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.55.53:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.7.244:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.182.193:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.36.52:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.225.85:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.181.217:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.62.25:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.58.236:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@216.26.244.191:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.25.234:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.39.139:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.38.200:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.21.224:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.40.150:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.191.58:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@104.207.58.48:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.180.171:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@65.111.4.154:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@209.50.189.21:3129",
    "http://eyi7eecyfihd:pe1rm71fd72ka0k@45.3.40.101:3129"
]

# ==========================================
# موتور هوشمند پردازش و نرمال‌سازی پروکسی
# ==========================================
def _score_host_port(host_candidate: str, port_candidate: str) -> int:
    """امتیازدهی برای تشخیص اینکه آیا یک جفت (host, port) واقعاً آی‌پی/دامنه و پورت است یا یوزر و پسورد"""
    try:
        if not port_candidate or not port_candidate.isdigit():
            return 0
        port_num = int(port_candidate)
        if not (1 <= port_num <= 65535):
            return 0
        if not host_candidate or any(c in host_candidate for c in (' ', '@', '/', '\\', ':')):
            return 0

        # ۱. اگر دقیقاً فرمت IPv4 باشد، بالاترین امتیاز (3)
        if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', host_candidate):
            return 3
        # ۲. اگر دامنه یا هاست دارای نقطه باشد (مثلاً proxy.site.com)، امتیاز بالا (2)
        if '.' in host_candidate and re.match(r'^[a-zA-Z0-9._-]+$', host_candidate):
            return 2
        # ۳. در غیر این صورت ممکن است نام هاست ساده یا یوزرنیم با پسورد عددی باشد (1)
        if re.match(r'^[a-zA-Z0-9._-]+$', host_candidate):
            return 1
        return 0
    except Exception:
        return 0

def normalize_proxy(raw_proxy: str) -> str | None:
    """
    تبدیل انواع فرمت‌های پروکسی به فرمت استاندارد:
    scheme://user:pass@host:port یا scheme://host:port
    بدون پرتاب هیچ‌گونه خطایی.
    """
    try:
        if not raw_proxy or not isinstance(raw_proxy, str):
            return None
        line = raw_proxy.strip().strip('"').strip("'").strip(',').strip()
        if not line or line.startswith('#'):
            return None

        # جدا کردن پروتکل (در صورت وجود)
        scheme = "http"
        rest = line
        scheme_match = re.match(r'^(https?|socks5h?|socks4a?)://(.*)$', line, re.IGNORECASE)
        if scheme_match:
            scheme = scheme_match.group(1).lower()
            rest = scheme_match.group(2)

        rest = rest.strip().rstrip('/')
        if not rest or '/' in rest or '?' in rest:
            return None

        host, port, user, password = None, None, None, None

        # حالت اول: وجود کاراکتر @ (یوزر:پسورد@هاست:پورت یا برعکس هاست:پورت@یوزر:پسورد)
        if '@' in rest:
            # بررسی از چپ و راست برای مقاومت در برابر وجود @ در پسورد
            left_a, right_a = rest.rsplit('@', 1)
            left_b, right_b = rest.split('@', 1)

            score_right = 0
            if ':' in right_a:
                r_h, r_p = right_a.rsplit(':', 1)
                score_right = _score_host_port(r_h, r_p)

            score_left = 0
            if ':' in left_b:
                l_h, l_p = left_b.rsplit(':', 1)
                score_left = _score_host_port(l_h, l_p)

            if score_right >= score_left and score_right > 0 and ':' in left_a:
                host, port = right_a.rsplit(':', 1)
                user, password = left_a.split(':', 1)
            elif score_left > score_right and score_left > 0 and ':' in right_b:
                host, port = left_b.rsplit(':', 1)
                user, password = right_b.split(':', 1)
            else:
                return None

        # حالت دوم: بدون کاراکتر @ (جدا شده با :)
        else:
            parts = rest.split(':')
            if len(parts) == 2:
                # فرمت بدون یوزر و پسورد -> host:port
                if _score_host_port(parts[0], parts[1]) > 0:
                    host, port = parts[0], parts[1]
                else:
                    return None
            elif len(parts) == 4:
                # فرمت ۴ بخشی -> host:port:user:pass یا user:pass:host:port
                score_first = _score_host_port(parts[0], parts[1])
                score_second = _score_host_port(parts[2], parts[3])

                if score_first >= score_second and score_first > 0:
                    host, port, user, password = parts[0], parts[1], parts[2], parts[3]
                elif score_second > score_first and score_second > 0:
                    user, password, host, port = parts[0], parts[1], parts[2], parts[3]
                else:
                    return None
            else:
                return None

        if not host or not port:
            return None

        if user is not None and password is not None:
            safe_user = quote(unquote(user.strip()), safe='')
            safe_pass = quote(unquote(password.strip()), safe='')
            return f"{scheme}://{safe_user}:{safe_pass}@{host.strip()}:{port.strip()}"
        else:
            return f"{scheme}://{host.strip()}:{port.strip()}"
    except Exception:
        return None

def is_proxy_source_url(text_line: str) -> bool:
    """تشخیص اینکه آیا یک رشته، لینک وب برای دانلود لیست پروکسی است یا خودِ یک پروکسی"""
    try:
        line = text_line.strip()
        if not line.lower().startswith(('http://', 'https://')):
            return False
        parsed = urlparse(line)
        # اگر مسیر (Path) یا پارامتر (Query) داشته باشد یا پورت نداشته باشد، لینک دانلود لیست پروکسی است
        if (parsed.path and parsed.path != '/') or parsed.query or not parsed.port:
            return True
        return False
    except Exception:
        return False

def parse_proxies_from_any_content(content: str) -> list[str]:
    """استخراج لیست پروکسی‌ها از متن خام یا ساختار JSON بدون خطا"""
    valid_proxies = []
    if not content:
        return valid_proxies

    # ۱. تلاش برای پارس کردن در صورتی که خروجی لینک به صورت JSON باشد
    try:
        json_data = json.loads(content)
        items = []
        if isinstance(json_data, list):
            items = json_data
        elif isinstance(json_data, dict):
            for key in ('proxies', 'data', 'result', 'list', 'items'):
                if isinstance(json_data.get(key), list):
                    items = json_data[key]
                    break

        for item in items:
            if isinstance(item, str):
                norm = normalize_proxy(item)
                if norm:
                    valid_proxies.append(norm)
            elif isinstance(item, dict):
                h = item.get('ip') or item.get('host') or item.get('server')
                p = item.get('port')
                u = item.get('username') or item.get('user')
                pw = item.get('password') or item.get('pass')
                sc = item.get('protocol') or item.get('type') or item.get('scheme') or 'http'
                if isinstance(sc, list) and sc:
                    sc = sc[0]
                if h and p:
                    raw = f"{sc}://{u}:{pw}@{h}:{p}" if (u and pw) else f"{sc}://{h}:{p}"
                    norm = normalize_proxy(raw)
                    if norm:
                        valid_proxies.append(norm)
        if valid_proxies:
            return list(dict.fromkeys(valid_proxies))
    except Exception:
        pass

    # ۲. پردازش خط به خط یا کلمه به کلمه برای متن‌های معمولی
    for token in re.split(r'[\r\n\s,;]+', content):
        token = token.strip()
        if not token:
            continue
        norm = normalize_proxy(token)
        if norm:
            valid_proxies.append(norm)

    return list(dict.fromkeys(valid_proxies))

def load_proxies_from_input(raw_text: str) -> tuple[list[str], list[str]]:
    """
    دریافت ورودی کاربر (که می‌تواند شامل لینک لیست پروکسی یا خود پروکسی‌ها باشد)
    خروجی: (لیست پروکسی‌های استخراج‌شده، لیست پیام‌های خطا/وضعیت)
    """
    extracted_proxies = []
    errors = []

    tokens = re.split(r'[\r\n\s]+', raw_text.strip())
    for token in tokens:
        if not token:
            continue
        if is_proxy_source_url(token):
            try:
                res = requests.get(token, timeout=20)
                if res.status_code == 200:
                    from_url = parse_proxies_from_any_content(res.text)
                    if from_url:
                        extracted_proxies.extend(from_url)
                    else:
                        errors.append(f"لینک باز شد اما پروکسی معتبری در آن یافت نشد: {token}")
                else:
                    errors.append(f"خطای HTTP {res.status_code} در دریافت لینک: {token}")
            except Exception as e:
                errors.append(f"خطا در اتصال به لینک {token}: {e}")
        else:
            norm = normalize_proxy(token)
            if norm:
                extracted_proxies.append(norm)

    unique_proxies = list(dict.fromkeys(extracted_proxies))
    return unique_proxies, errors

# مقداردهی اولیه لیست پروکسی‌ها
PROXY_LIST = [p for p in (normalize_proxy(x) for x in RAW_DEFAULT_PROXIES) if p]

if PROXY_URL:
    loaded_from_env, _ = load_proxies_from_input(PROXY_URL)
    if loaded_from_env:
        PROXY_LIST = loaded_from_env

def get_random_proxy():
    if not PROXY_LIST:
        return None
    selected = random.choice(PROXY_LIST)
    return {"http": selected, "https": selected}

# ==========================================
# توابع کمکی اکانت و توکن
# ==========================================
def fetch_data(url):
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

def get_tokens_from_data(data):
    access_token, refresh_token = None, None
    try:
        for cookie in data.get('cookies', []):
            if cookie.get('name') == 'tokenMS':
                access_token = cookie.get('value')
            elif cookie.get('name') == 'refresh_token':
                refresh_token = cookie.get('value')
        if not access_token or not refresh_token:
            for origin in data.get('origins', []):
                for item in origin.get('localStorage', []):
                    if item.get('name') == 'tokenMS':
                        access_token = item.get('value')
                    elif item.get('name') == 'refresh_token':
                        refresh_token = item.get('value')
    except Exception:
        pass
    return access_token, refresh_token

def update_tokens_in_data(data, old_acc, new_acc, old_ref, new_ref):
    try:
        content = json.dumps(data, ensure_ascii=False)
        if old_acc and new_acc:
            content = content.replace(old_acc, new_acc)
        if old_ref and new_ref:
            content = content.replace(old_ref, new_ref)
        return json.loads(content)
    except Exception:
        return data

def get_user_ids_from_token(token):
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        decoded_bytes = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded_bytes)

        uid = data.get('userId') or data.get('alternativeCustomerId') or data.get('sub')
        cerb_id = data.get('cerberusId')

        return int(uid) if uid else 0, cerb_id
    except Exception:
        return 0, None

async def extract_text_from_message(message: Message, bot: Bot) -> str:
    if message.text:
        return message.text
    elif message.document:
        file_info = await bot.get_file(message.document.file_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        return downloaded_file.read().decode('utf-8', errors='ignore')
    return ""

async def extract_urls_from_message(message: Message, bot: Bot):
    content = await extract_text_from_message(message, bot)
    if not content:
        return []
    return re.findall(r'(https?://\S+)', content)

# ==========================================
# کلاس ارتباط با API اُکالا
# ==========================================
class OkalaAPI:
    def __init__(self):
        self.request_logs = []
        self.base_headers = {
            'accept': 'application/json, text/plain, */*',
            'source': 'okala',
            'ui-version': '2.0',
            'origin': 'https://www.okala.com',
            'sec-ch-ua': '"Chromium";v="137", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': '?1',
            'sec-ch-ua-platform': '"Android"',
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/137.0.0.0 Mobile'
        }

    def log_request(self, method, url, status_code, response_text):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {method} {url}\nStatus: {status_code}\nResponse: {response_text}\n{'-'*50}\n"
        self.request_logs.append(log_entry)

    def make_request(self, method, url, access_token=None, **kwargs):
        headers = self.base_headers.copy()
        headers['X-Correlation-Id'] = str(uuid.uuid4())
        headers['X-User-Unique-Id'] = str(uuid.uuid4())
        headers['session-id'] = str(uuid.uuid4())

        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'

        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))

        for attempt in range(3):
            current_proxy = get_random_proxy()
            try:
                res = requests.request(
                    method, url, headers=headers, proxies=current_proxy, timeout=45, **kwargs
                )
                self.log_request(method, url, res.status_code, res.text)
                if res.status_code == 200:
                    try:
                        return 200, res.json()
                    except Exception:
                        return 200, {}
                elif res.status_code == 401:
                    return 401, {}
                else:
                    return res.status_code, res.text
            except Exception as e:
                self.log_request(method, url, "EXCEPTION", str(e))
                time.sleep(1.5)
                continue
        return 0, "Network Error"

    def refresh_token(self, refresh_token):
        url = "https://apigateway.okala.com/api/v1/accounts/tokens"
        data = {
            "grant_type": "refresh_token",
            "client_id": "customer_client_id",
            "client_secret": "u_M{'57j!%LI21#",
            "scope": "offline_access",
            "refresh_token": refresh_token
        }
        headers = {"content-type": "application/x-www-form-urlencoded"}
        status, response_data = self.make_request('POST', url, headers=headers, data=data)
        if status == 200 and isinstance(response_data, dict):
            return response_data.get('access_token'), response_data.get('refresh_token')
        return None, None

    # --- متدهای مربوط به آدرس (دقیقاً مطابق کد اول + پشتیبانی صفحه‌بندی) ---
    def get_address(self, token, uid):
        url = 'https://apigateway.okala.com/api/voyager/CustomerAddress/CustomerAddressForReact'
        return self.make_request('GET', url, token, params={'customerId': uid})

    def get_all_addresses_paged(self, token, page_size=50):
        url = f'https://apigateway.okala.com/api/v1/accounts/userprofile/getcustomeraddresseswithpaging?pageIndex=1&pageSize={page_size}'
        return self.make_request('GET', url, token)

    def add_address(self, token, uid, addr_data):
        url = 'https://apigateway.okala.com/api/voyager/C/CustomerAccount/AddAddress/'

        plaque_val = addr_data.get('plaque') or '0'
        unit_val = addr_data.get('unit') or '1'
        address_text = addr_data.get('address')
        if not address_text or not str(address_text).strip():
            address_text = 'آدرس ثبت شده از نقشه'

        payload = {
            'id': 0,
            'customerId': uid,
            'mobilePhone': '',
            'ShoppingSectorPartId': '0',
            'shoppingSectorId': '0',
            'plaque': str(plaque_val),
            'unit': str(unit_val),
            'lat': float(addr_data['lat']),
            'lng': float(addr_data['lng']),
            'title': None,
            'addressTypeId': 3,
            'oprationDuration': random.randint(10000, 20000),
            'address': address_text,
            'mapPlatform': 'ParsiMap'
        }
        if addr_data.get('cityId'):
            payload['cityId'] = addr_data['cityId']

        status, res = self.make_request('POST', url, token, json=payload)
        # اگر به دلیل نبود cityId خطا داد، یک بار هم با cityId پیش‌فرض تلاش می‌کند
        if status not in (200, 401) and 'cityId' not in payload:
            payload['cityId'] = 129
            status, res = self.make_request('POST', url, token, json=payload)
        return status, res

    def delete_address(self, token, address_id):
        url = f'https://apigateway.okala.com/api/voyager/C/CustomerAccount/DeleteAddress/{address_id}/'
        return self.make_request('DELETE', url, token)

    # --- متدهای سبد خرید ---
    def get_stores(self, token, lat, lng, uid=None):
        url = 'https://apigateway.okala.com/api/opex/v4/stores/nearby'
        return self.make_request('GET', url, token, params={'latitude': lat, 'longitude': lng})

    def get_cart(self, token, uid, store_ids):
        url = 'https://apigateway.okala.com/api/Basket/v4/ShoppingCart/GetCustomerShoppingCartItems'
        return self.make_request('GET', url, token, params={'CustomerId': uid, 'StoreIds': store_ids, 'isFromCartPage': 'false'})

    def add_to_cart(self, token, uid, store_id, product_id):
        url = 'https://apigateway.okala.com/api/Basket/v2/ShoppingCart/AddToShoppingCart'
        payload = {
            'storeId': store_id,
            'customerId': uid,
            'productId': product_id,
            'quantity': 1,
            'isSupplier': False,
            'replaceItemMethodCode': -1,
            'sectorId': '0',
            'sectorPartId': '0',
            'productStoreId': '0',
            'queryId': None
        }
        return self.make_request('POST', url, token, json=payload)

    # --- متدهای تخفیف ---
    def get_discounts(self, token, cerberus_id):
        url = f"https://apigateway.okala.com/api/discount/v1/discounts/customer/{cerberus_id}"
        return self.make_request('GET', url, token)


# ==========================================
# توابع پردازشگر (Workers)
# ==========================================

# --- 1. کپی سبد خرید (دقیقاً منطبق با منطق سالم کد اول) ---
def worker_copy_basket(target_url, api, template_data):
    time.sleep(random.uniform(0.1, 1.0))
    data = fetch_data(target_url)
    if not data:
        return target_url, "error_fetch", None, ["دریافت اطلاعات اکانت از لینک ناموفق بود."]

    acc_token, ref_token = get_tokens_from_data(data)
    if not acc_token:
        return target_url, "error_token", data, ["توکن در اطلاعات اکانت یافت نشد."]

    uid, _ = get_user_ids_from_token(acc_token)
    if not uid or uid == 0:
        return target_url, "error_uuid", data, ["شناسه کاربری (User ID) معتبر نیست."]

    status, response_data = api.add_address(acc_token, uid, template_data['address'])
    if status == 401 and ref_token:
        new_acc, new_ref = api.refresh_token(ref_token)
        if new_acc:
            data = update_tokens_in_data(data, acc_token, new_acc, ref_token, new_ref)
            acc_token = new_acc
            status, response_data = api.add_address(acc_token, uid, template_data['address'])

    if status != 200:
        return target_url, "error_address", data, [f"خطا در ثبت آدرس | HTTP Status: {status} | Response: {response_data}"]

    added_count = 0
    cart_errors = []

    for item in template_data['items']:
        for _ in range(item['quantity']):
            c_status, c_res = api.add_to_cart(acc_token, uid, template_data['store_id'], item['productId'])
            if c_status == 200:
                added_count += 1
            else:
                cart_errors.append(f"خطا در افزودن محصول {item.get('productId')} | HTTP Status: {c_status} | Response: {c_res}")
            time.sleep(random.uniform(0.3, 0.8))

    if added_count == 0 and len(template_data['items']) > 0:
        return target_url, "error_cart", data, cart_errors

    return target_url, "success", data, cart_errors

def process_all_links(session_dir, template_url, target_urls):
    api = OkalaAPI()
    template_data_json = fetch_data(template_url)
    if not template_data_json:
        return None, None, "خطا: امکان دریافت اطلاعات اکانت مرجع (اولین لینک) وجود ندارد."

    t_acc, t_ref = get_tokens_from_data(template_data_json)
    t_uid, _ = get_user_ids_from_token(t_acc)
    if not t_uid or t_uid == 0:
        return None, None, "خطا: ساختار توکن اکانت مرجع معتبر نمی‌باشد."

    status, addr_res = api.get_address(t_acc, t_uid)
    if status == 401 and t_ref:
        new_acc, new_ref = api.refresh_token(t_ref)
        if new_acc:
            template_data_json = update_tokens_in_data(template_data_json, t_acc, new_acc, t_ref, new_ref)
            t_acc, t_ref = new_acc, new_ref
            status, addr_res = api.get_address(t_acc, t_uid)

    template_addr = None
    if status == 200 and isinstance(addr_res, dict) and addr_res.get('data'):
        template_addr = addr_res['data'][0]
    else:
        # بررسی مسیر دوم آدرس در صورت خالی بودن مسیر اول
        status_paged, addr_paged = api.get_all_addresses_paged(t_acc, page_size=15)
        if status_paged == 200 and isinstance(addr_paged, dict) and addr_paged.get('data', {}).get('customerAddressResponseItems'):
            template_addr = addr_paged['data']['customerAddressResponseItems'][0]
        else:
            # پشتیبان mapInfo دقیقاً مانند کد اول
            api.request_logs.append(f"INFO: No saved address found for template account. Using mapInfo as fallback.\n{'-'*50}\n")
            lat, lng = 35.69975, 51.33551
            addr_text = "آدرس استخراج شده از نقشه"
            city_id = None
            try:
                for origin in template_data_json.get('origins', []):
                    for item in origin.get('localStorage', []):
                        if item.get('name') == 'mapInfo':
                            map_info = json.loads(item.get('value'))
                            if 'selectedCity' in map_info:
                                lat = map_info['selectedCity']['lat']
                                lng = map_info['selectedCity']['lng']
                                addr_text = map_info['selectedCity'].get('name', addr_text)
                                city_id = map_info['selectedCity'].get('id')
            except Exception as e:
                api.request_logs.append(f"ERROR parsing mapInfo: {e}\n{'-'*50}\n")

            template_addr = {
                'lat': lat,
                'lng': lng,
                'address': addr_text,
                'plaque': '0',
                'unit': '1'
            }
            if city_id:
                template_addr['cityId'] = city_id

    status, stores_res = api.get_stores(t_acc, template_addr['lat'], template_addr['lng'], t_uid)
    if status != 200 or not isinstance(stores_res, dict) or not stores_res.get('data', {}).get('stores'):
        return None, api.request_logs, f"خطا: هیچ فروشگاهی برای مختصات اکانت مرجع یافت نشد. (HTTP Status: {status})"

    store_ids = [s['storeId'] for s in stores_res['data']['stores']]
    status, cart_res = api.get_cart(t_acc, t_uid, store_ids)
    if status != 200 or not isinstance(cart_res, dict) or not cart_res.get('data', {}).get('result'):
        return None, api.request_logs, f"خطا: امکان بازیابی سبد خرید اکانت مرجع وجود ندارد. (HTTP Status: {status})"

    cart_data = cart_res['data']['result'][0]
    cart_items = cart_data.get('items', [])
    cart_store_id = cart_data.get('storeId')

    if not cart_items:
        return None, api.request_logs, "خطا: سبد خرید اکانت مرجع خالی است."

    template_data = {
        'address': {
            'lat': template_addr['lat'],
            'lng': template_addr['lng'],
            'address': template_addr.get('address', 'آدرس ثبت شده'),
            'plaque': template_addr.get('plaque', '0'),
            'unit': template_addr.get('unit', '1'),
            'cityId': template_addr.get('cityId')
        },
        'store_id': cart_store_id,
        'items': cart_items
    }

    stats = {
        "total_targets": len(target_urls),
        "success": 0,
        "error_fetch": 0,
        "error_address": 0,
        "error_cart": 0,
        "error_token": 0
    }
    all_errors = []

    updated_dir = os.path.join(session_dir, "Updated_Accounts")
    os.makedirs(updated_dir, exist_ok=True)

    with open(os.path.join(updated_dir, "template_account.json"), "w", encoding="utf-8") as f:
        json.dump(template_data_json, f, ensure_ascii=False, indent=2)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(worker_copy_basket, url, api, template_data): url for url in target_urls}
        counter = 1
        for future in as_completed(futures):
            url = futures[future]
            try:
                _, result, updated_json, c_errs = future.result()
                if result == "success":
                    stats["success"] += 1
                elif result == "error_fetch":
                    stats["error_fetch"] += 1
                elif result in ["error_token", "error_uuid"]:
                    stats["error_token"] += 1
                elif result == "error_address":
                    stats["error_address"] += 1
                elif result == "error_cart":
                    stats["error_cart"] += 1

                if c_errs:
                    all_errors.append(f"🔗 لینک اکانت:\n{url}\n" + "\n".join(c_errs) + "\n" + "-"*40)

                if updated_json:
                    file_name = url.strip('/').split('/')[-1]
                    if not file_name or len(file_name) < 5:
                        file_name = f"target_account_{counter}"
                    with open(os.path.join(updated_dir, f"{file_name}.json"), "w", encoding="utf-8") as f:
                        json.dump(updated_json, f, ensure_ascii=False, indent=2)
                counter += 1
            except Exception as e:
                stats["error_fetch"] += 1
                all_errors.append(f"🔗 لینک اکانت:\n{url}\nخطای سیستم: {str(e)}\n" + "-"*40)

    zip_path = shutil.make_archive(os.path.join(session_dir, "Updated_Accounts_Data"), 'zip', updated_dir)

    error_file_path = None
    if all_errors:
        error_file_path = os.path.join(session_dir, "Server_Errors.txt")
        with open(error_file_path, "w", encoding="utf-8") as f:
            f.write("گزارش دقیق خطاهای سرور در ثبت آدرس و افزودن سبد خرید:\n============================================================\n\n")
            f.write("\n".join(all_errors))

    return (zip_path, template_data, stats, error_file_path), api.request_logs, None


# --- 2. پاک کردن آدرس‌ها ---
def worker_delete_addresses(target_url, api):
    time.sleep(random.uniform(0.1, 1.0))
    data = fetch_data(target_url)
    if not data:
        return target_url, "error_fetch", 0

    acc_token, ref_token = get_tokens_from_data(data)
    if not acc_token:
        return target_url, "error_token", 0

    uid, _ = get_user_ids_from_token(acc_token)
    total_deleted = 0

    for attempt in range(10):
        status, addr_res = api.get_all_addresses_paged(acc_token, page_size=50)
        if status == 401 and ref_token:
            new_acc, _ = api.refresh_token(ref_token)
            if new_acc:
                acc_token = new_acc
                status, addr_res = api.get_all_addresses_paged(acc_token, page_size=50)

        addresses = []
        if status == 200 and isinstance(addr_res, dict):
            addresses = addr_res.get('data', {}).get('customerAddressResponseItems', [])

        # اگر در مسیر اول آدرسی نبود، مسیر React را هم بررسی می‌کنیم
        if not addresses and uid:
            r_status, r_res = api.get_address(acc_token, uid)
            if r_status == 200 and isinstance(r_res, dict) and isinstance(r_res.get('data'), list):
                addresses = r_res['data']
            elif status != 200 and attempt == 0:
                return target_url, "error_fetch_address", total_deleted

        if not addresses:
            break

        deleted_in_round = 0
        for addr in addresses:
            addr_id = addr.get('id')
            if addr_id:
                del_status, _ = api.delete_address(acc_token, addr_id)
                if del_status == 200:
                    total_deleted += 1
                    deleted_in_round += 1
                time.sleep(random.uniform(0.3, 0.8))

        if deleted_in_round == 0:
            break

    return target_url, "success", total_deleted

def process_delete_all_links(session_dir, target_urls):
    api = OkalaAPI()
    stats = {"total_targets": len(target_urls), "success_accounts": 0, "total_deleted_addresses": 0, "errors": 0}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(worker_delete_addresses, url, api): url for url in target_urls}
        for future in as_completed(futures):
            try:
                url, result, deleted = future.result()
                if result == "success":
                    stats["success_accounts"] += 1
                    stats["total_deleted_addresses"] += deleted
                else:
                    stats["errors"] += 1
            except Exception:
                stats["errors"] += 1
    return stats, api.request_logs


# --- 3. بررسی تخفیف‌ها ---
def worker_check_discount(target_url, api):
    time.sleep(random.uniform(0.1, 1.0))
    data = fetch_data(target_url)
    if not data:
        return target_url, 0, "error_fetch", "دریافت اطلاعات ناموفق"

    acc_token, ref_token = get_tokens_from_data(data)
    if not acc_token:
        return target_url, 0, "error_token", "توکن در اکانت یافت نشد"

    _, cerb_id = get_user_ids_from_token(acc_token)
    if not cerb_id:
        return target_url, 0, "error_uuid", "Cerberus ID پیدا نشد"

    status, res = api.get_discounts(acc_token, cerb_id)
    if status == 401 and ref_token:
        new_acc, _ = api.refresh_token(ref_token)
        if new_acc:
            acc_token = new_acc
            status, res = api.get_discounts(acc_token, cerb_id)

    if status == 200 and isinstance(res, dict):
        discounts = res.get('data', [])
        if not discounts:
            return target_url, 0, "success", None
        valid_amounts = [d.get('discountAmount', 0) for d in discounts if d.get('discountAmount')]
        max_d = max(valid_amounts) if valid_amounts else 0
        return target_url, max_d, "success", None
    elif status == 401:
        return target_url, 0, "expired", "توکن منقضی شده است"
    else:
        return target_url, 0, "error_api", f"HTTP Status: {status} - {res}"

def process_discount_links(session_dir, urls):
    api = OkalaAPI()
    stats = {"total": len(urls), "with_discount": 0, "no_discount": 0, "errors": 0}
    discounted_links = []
    all_errors = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(worker_check_discount, url, api): url for url in urls}
        for future in as_completed(futures):
            try:
                url, max_d, res, err = future.result()
                if res == "success":
                    if max_d > 0:
                        stats["with_discount"] += 1
                        discounted_links.append((url, max_d))
                    else:
                        stats["no_discount"] += 1
                else:
                    stats["errors"] += 1
                    if err:
                        all_errors.append(f"🔗 لینک:\n{url}\nخطا: {err}\n{'-'*40}")
            except Exception as e:
                stats["errors"] += 1
                all_errors.append(f"🔗 لینک:\n{url}\nخطای سیستم: {str(e)}\n{'-'*40}")

    report_file = None
    if discounted_links:
        report_file = os.path.join(session_dir, "Discounted_Links_Report.txt")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("گزارش لینک‌های دارای تخفیف:\n" + "="*40 + "\n\n")
            for url, amount in sorted(discounted_links, key=lambda x: x[1], reverse=True):
                f.write(f"🎁 تخفیف {int(amount/10000)} هزار تومانی:\n{url}\n\n")

    err_file = None
    if all_errors:
        err_file = os.path.join(session_dir, "Discount_Errors.txt")
        with open(err_file, "w", encoding="utf-8") as f:
            f.write("گزارش خطاهای بررسی تخفیف:\n============================\n\n")
            f.write("\n".join(all_errors))

    return stats, report_file, err_file, api.request_logs


# --- 4. گزارش وضعیت سبد خرید ---
def worker_check_cart_status(target_url, api):
    time.sleep(random.uniform(0.1, 1.0))
    data = fetch_data(target_url)
    if not data:
        return target_url, 0, 0, "error_fetch", "دریافت اطلاعات ناموفق"

    acc_token, ref_token = get_tokens_from_data(data)
    if not acc_token:
        return target_url, 0, 0, "error_token", "توکن یافت نشد"

    uid, _ = get_user_ids_from_token(acc_token)
    if not uid or uid == 0:
        return target_url, 0, 0, "error_uuid", "User ID نامعتبر"

    status, addr_res = api.get_address(acc_token, uid)
    if status == 401 and ref_token:
        new_acc, _ = api.refresh_token(ref_token)
        if new_acc:
            acc_token = new_acc
            status, addr_res = api.get_address(acc_token, uid)

    lat, lng = 35.69975, 51.33551
    if status == 200 and isinstance(addr_res, dict) and addr_res.get('data'):
        addr_data = addr_res['data'][0]
        lat = addr_data.get('lat', lat)
        lng = addr_data.get('lng', lng)
    else:
        status_p, addr_p = api.get_all_addresses_paged(acc_token, page_size=15)
        if status_p == 200 and isinstance(addr_p, dict) and addr_p.get('data', {}).get('customerAddressResponseItems'):
            addr_data = addr_p['data']['customerAddressResponseItems'][0]
            lat = addr_data.get('lat', lat)
            lng = addr_data.get('lng', lng)
        elif status != 200 and status_p != 200:
            return target_url, 0, 0, "error_api", f"خطا در دریافت آدرس (HTTP {status})"

    status, stores_res = api.get_stores(acc_token, lat, lng, uid)
    if status != 200 or not isinstance(stores_res, dict) or not stores_res.get('data', {}).get('stores'):
        return target_url, 0, 0, "error_api", f"خطا در دریافت فروشگاه‌ها (HTTP {status})"

    store_ids = [s['storeId'] for s in stores_res['data']['stores']]
    status, cart_res = api.get_cart(acc_token, uid, store_ids)

    if status == 200 and isinstance(cart_res, dict) and cart_res.get('data'):
        cart_data = cart_res['data'].get('result', [])
        if cart_data:
            total_items = sum(cart.get('count', 0) for cart in cart_data)
            total_price = sum(cart.get('totalPrice', 0) for cart in cart_data)
            return target_url, total_items, total_price, "success", None
        return target_url, 0, 0, "success", None

    return target_url, 0, 0, "error_api", f"خطا در دریافت سبد خرید (HTTP {status})"

def process_cart_report_links(session_dir, urls):
    api = OkalaAPI()
    stats = {"total": len(urls), "with_cart": 0, "empty_cart": 0, "errors": 0}
    cart_links = []
    all_errors = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(worker_check_cart_status, url, api): url for url in urls}
        for future in as_completed(futures):
            try:
                url, items, price, res, err = future.result()
                if res == "success":
                    if items > 0:
                        stats["with_cart"] += 1
                        cart_links.append((url, items, price))
                    else:
                        stats["empty_cart"] += 1
                else:
                    stats["errors"] += 1
                    if err:
                        all_errors.append(f"🔗 لینک:\n{url}\nخطا: {err}\n{'-'*40}")
            except Exception as e:
                stats["errors"] += 1
                all_errors.append(f"🔗 لینک:\n{url}\nخطای سیستم: {str(e)}\n{'-'*40}")

    report_file = None
    if cart_links:
        report_file = os.path.join(session_dir, "Cart_Report.txt")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("گزارش اکانت‌های دارای سبد خرید:\n" + "="*40 + "\n\n")
            for url, items, price in sorted(cart_links, key=lambda x: x[1], reverse=True):
                f.write(f"🛒 سبد خرید با {items} کالا (مبلغ {int(price/10):,} تومان):\n{url}\n\n")

    err_file = None
    if all_errors:
        err_file = os.path.join(session_dir, "Cart_Errors.txt")
        with open(err_file, "w", encoding="utf-8") as f:
            f.write("گزارش خطاهای بررسی سبد خرید:\n============================\n\n")
            f.write("\n".join(all_errors))

    return stats, report_file, err_file, api.request_logs


# ==========================================
# هندلرهای تلگرام
# ==========================================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"سیستم چندمنظوره فعال است.\n"
        f"🌐 تعداد پروکسی‌های فعال فعلی: {len(PROXY_LIST)}\n\n"
        "لطفاً از منوی زیر یک گزینه را انتخاب کنید:",
        reply_markup=main_keyboard
    )

@router.message(F.text == "🛒 همگام‌سازی سبد خرید")
async def btn_sync_cart(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_sync_links)
    await message.answer(
        "🛒 **همگام‌سازی سبد خرید**\n\n"
        "لطفاً لینک‌ها را متنی ارسال کنید یا یک فایل `.txt` شامل لینک‌ها بفرستید (لینک اول به عنوان الگو در نظر گرفته می‌شود)."
    )

@router.message(F.text == "🗑 پاک کردن آدرس‌ها")
async def btn_delete_addresses(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_delete_links)
    await message.answer("🗑 **پاک کردن آدرس‌ها**\n\nلطفاً لینک‌ها را ارسال کنید یا یک فایل `.txt` حاوی لینک‌ها آپلود کنید.")

@router.message(F.text == "🔎 بررسی تخفیف‌ها")
async def btn_check_discounts(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_discount_links)
    await message.answer(
        "🔎 **بررسی تخفیف‌ها**\n\n"
        "لطفاً لینک‌ها را ارسال کنید یا یک فایل `.txt` شامل لینک‌ها آپلود کنید.\n"
        "لینک‌های تخفیف‌دار در فایل متنی جداگانه به شما تحویل داده می‌شوند."
    )

@router.message(F.text == "📦 گزارش موجودی سبد خرید")
async def btn_check_carts(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_cart_report_links)
    await message.answer(
        "📦 **گزارش وضعیت سبد خرید**\n\n"
        "لطفاً لینک‌ها را ارسال کنید یا یک فایل `.txt` آپلود کنید.\n"
        "اکانت‌هایی که دارای سبد خرید هستند شناسایی و در فایلی جداگانه گزارش می‌شوند."
    )

@router.message(F.text == "🌐 تنظیم / بروزرسانی پروکسی")
async def btn_update_proxies(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_proxies)
    await message.answer(
        f"🌐 **تنظیم و بروزرسانی پروکسی‌ها**\n"
        f"تعداد پروکسی‌های فعال فعلی: `{len(PROXY_LIST)}`\n\n"
        "می‌توانید یکی از موارد زیر را ارسال کنید:\n"
        "1️⃣ **لینک (URL)** حاوی لیست پروکسی‌ها (متنی یا JSON)\n"
        "2️⃣ **فایل `.txt`** حاوی پروکسی‌ها یا لینک‌ها\n"
        "3️⃣ **متن مستقیم** لیست پروکسی‌ها با هر فرمتی:\n"
        "• `ip:port` یا `host:port`\n"
        "• `user:pass@host:port` یا `host:port@user:pass`\n"
        "• `host:port:user:pass` یا `user:pass:host:port`"
    )

# ----------- هندلر وضعیت بروزرسانی پروکسی -----------
@router.message(BotStates.waiting_for_proxies, F.text | F.document)
async def handle_proxies_input(message: Message, bot: Bot, state: FSMContext):
    global PROXY_LIST
    raw_content = await extract_text_from_message(message, bot)
    if not raw_content.strip():
        await message.answer("❌ ورودی خالی است. لطفاً لینک یا لیست پروکسی‌ها را ارسال کنید.")
        return

    msg = await message.answer("⏳ در حال دریافت و بررسی فرمت پروکسی‌ها...")
    new_proxies, errs = await asyncio.to_thread(load_proxies_from_input, raw_content)

    if not new_proxies:
        err_detail = "\n".join(errs[:5]) if errs else "هیچ پروکسی معتبری در ورودی پیدا نشد."
        await msg.edit_text(f"❌ بروزرسانی ناموفق بود.\n{err_detail}\n\nپروکسی‌های قبلی ({len(PROXY_LIST)} عدد) حفظ شدند.")
        await state.clear()
        return

    PROXY_LIST = new_proxies
    sample = PROXY_LIST[0]
    report = (
        f"✅ **لیست پروکسی‌ها با موفقیت بروزرسانی شد!**\n\n"
        f"🟢 تعداد پروکسی‌های معتبر بارگذاری‌شده: `{len(PROXY_LIST)}`\n"
        f"🔹 نمونه فرمت استانداردشده:\n`{sample}`"
    )
    if errs:
        report += f"\n\n⚠️ هشدارها ({len(errs)} مورد):\n" + "\n".join(errs[:3])

    await msg.edit_text(report)
    await state.clear()

# ----------- هندلر وضعیت همگام سازی -----------
@router.message(BotStates.waiting_for_sync_links, F.text | F.document)
async def handle_sync_links(message: Message, bot: Bot, state: FSMContext):
    urls = await extract_urls_from_message(message, bot)
    if len(urls) < 2:
        await message.answer("خطا: لطفاً حداقل ۲ لینک (یک الگو و حداقل یک هدف) در پیام یا فایل ارسال کنید.")
        return

    msg = await message.answer(f"در حال پردازش...\nاکانت مرجع دریافت شد. تعداد اهداف: {len(urls)-1}")
    session_dir = os.path.join(SESSION_BASE_DIR, str(uuid.uuid4()))
    os.makedirs(session_dir, exist_ok=True)

    result_data, logs, err = await asyncio.to_thread(process_all_links, session_dir, urls[0], urls[1:])

    log_file_path = os.path.join(session_dir, "debug_report.txt")
    if logs:
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(logs))

    if err:
        await msg.edit_text(err)
        if os.path.exists(log_file_path):
            await message.answer_document(document=FSInputFile(log_file_path), caption="فایل گزارش خطاها (Debug Log)")
        shutil.rmtree(session_dir, ignore_errors=True)
        await state.clear()
        return

    final_zip_path, template_data, stats, error_file_path = result_data
    total_qty = sum(item['quantity'] for item in template_data['items'])

    report = (
        "✅ گزارش عملکرد همگام‌سازی:\n\n"
        f"تعداد اقلام مرجع: {len(template_data['items'])} مدل (مجموع: {total_qty} عدد)\n\n"
        f"تعداد کل اهداف: {stats['total_targets']}\n"
        f"🟢 موفق: {stats['success']}\n"
        f"🔴 خطای دریافت از لینک: {stats['error_fetch']}\n"
        f"🔴 خطای ثبت آدرس: {stats['error_address']}\n"
        f"🔴 خطای افزودن کالا: {stats['error_cart']}\n"
        f"🔴 خطای احراز هویت / توکن: {stats['error_token']}"
    )

    await msg.delete()
    await message.answer_document(document=FSInputFile(final_zip_path), caption=report)

    if error_file_path and os.path.exists(error_file_path):
        await message.answer_document(document=FSInputFile(error_file_path), caption="⚠️ فایل گزارش دقیق خطاهای سرور (Server Errors)")

    if os.path.exists(log_file_path):
        await message.answer_document(document=FSInputFile(log_file_path), caption="گزارش کامل درخواست‌ها و پاسخ‌های سرور (Debug Log)")

    shutil.rmtree(session_dir, ignore_errors=True)
    await state.clear()

# ----------- هندلر وضعیت حذف آدرس -----------
@router.message(BotStates.waiting_for_delete_links, F.text | F.document)
async def handle_delete_links(message: Message, bot: Bot, state: FSMContext):
    urls = await extract_urls_from_message(message, bot)
    if not urls:
        await message.answer("خطا: هیچ لینکی یافت نشد.")
        return

    msg = await message.answer(f"در حال پردازش برای حذف آدرس...\nتعداد اکانت‌ها: {len(urls)}")
    session_dir = os.path.join(SESSION_BASE_DIR, str(uuid.uuid4()))
    os.makedirs(session_dir, exist_ok=True)

    stats, logs = await asyncio.to_thread(process_delete_all_links, session_dir, urls)

    await msg.delete()
    report = (
        "✅ گزارش حذف آدرس:\n\n"
        f"تعداد کل اکانت‌ها: {stats['total_targets']}\n"
        f"🟢 موفق: {stats['success_accounts']}\n"
        f"🗑 آدرس‌های حذف شده: {stats['total_deleted_addresses']}\n"
        f"🔴 خطا: {stats['errors']}"
    )
    await message.answer(report)
    shutil.rmtree(session_dir, ignore_errors=True)
    await state.clear()

# ----------- هندلر وضعیت بررسی تخفیف -----------
@router.message(BotStates.waiting_for_discount_links, F.text | F.document)
async def handle_discount_links(message: Message, bot: Bot, state: FSMContext):
    urls = await extract_urls_from_message(message, bot)
    if not urls:
        await message.answer("خطا: هیچ لینکی یافت نشد.")
        return

    msg = await message.answer(f"🔎 در حال بررسی تخفیف‌ها...\nتعداد لینک‌ها: {len(urls)}")
    session_dir = os.path.join(SESSION_BASE_DIR, str(uuid.uuid4()))
    os.makedirs(session_dir, exist_ok=True)

    stats, report_file, err_file, logs = await asyncio.to_thread(process_discount_links, session_dir, urls)

    await msg.delete()
    report = (
        "📊 گزارش بررسی تخفیف‌ها:\n\n"
        f"کل لینک‌ها: {stats['total']}\n"
        f"🎁 دارای تخفیف: {stats['with_discount']}\n"
        f"➖ بدون تخفیف/سوخته: {stats['no_discount']}\n"
        f"🔴 خطا: {stats['errors']}"
    )
    await message.answer(report)

    if report_file and os.path.exists(report_file):
        await message.answer_document(document=FSInputFile(report_file), caption="🎁 فایل لینک‌های دارای تخفیف")

    if err_file and os.path.exists(err_file):
        await message.answer_document(document=FSInputFile(err_file), caption="⚠️ فایل گزارش خطاها")

    shutil.rmtree(session_dir, ignore_errors=True)
    await state.clear()

# ----------- هندلر وضعیت گزارش سبد خرید -----------
@router.message(BotStates.waiting_for_cart_report_links, F.text | F.document)
async def handle_cart_report_links(message: Message, bot: Bot, state: FSMContext):
    urls = await extract_urls_from_message(message, bot)
    if not urls:
        await message.answer("خطا: هیچ لینکی یافت نشد.")
        return

    msg = await message.answer(f"📦 در حال بررسی سبد خریدهای اکانت‌ها...\nتعداد لینک‌ها: {len(urls)}")
    session_dir = os.path.join(SESSION_BASE_DIR, str(uuid.uuid4()))
    os.makedirs(session_dir, exist_ok=True)

    stats, report_file, err_file, logs = await asyncio.to_thread(process_cart_report_links, session_dir, urls)

    await msg.delete()
    report = (
        "📊 گزارش بررسی وضعیت سبد خرید:\n\n"
        f"کل لینک‌ها: {stats['total']}\n"
        f"🛒 دارای سبد خرید: {stats['with_cart']}\n"
        f"➖ سبد خالی/سوخته: {stats['empty_cart']}\n"
        f"🔴 خطا: {stats['errors']}"
    )
    await message.answer(report)

    if report_file and os.path.exists(report_file):
        await message.answer_document(document=FSInputFile(report_file), caption="🛒 فایل لینک‌های دارای سبد خرید")

    if err_file and os.path.exists(err_file):
        await message.answer_document(document=FSInputFile(err_file), caption="⚠️ فایل گزارش خطاها")

    shutil.rmtree(session_dir, ignore_errors=True)
    await state.clear()

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
