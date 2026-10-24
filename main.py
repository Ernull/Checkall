import os
import shutil
import asyncio
import json
import base64
import zipfile
import requests
import time
import uuid
import random
import re
from collections import Counter
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

# ==========================================
# موتور هوشمند پردازش و نرمال‌سازی پروکسی
# ==========================================
def _score_host_port(host_candidate: str, port_candidate: str) -> int:
    try:
        if not port_candidate or not port_candidate.isdigit():
            return 0
        port_num = int(port_candidate)
        if not (1 <= port_num <= 65535):
            return 0
        if not host_candidate or any(c in host_candidate for c in (' ', '@', '/', '\\', ':')):
            return 0
        if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', host_candidate):
            return 3
        if '.' in host_candidate and re.match(r'^[a-zA-Z0-9._-]+$', host_candidate):
            return 2
        if re.match(r'^[a-zA-Z0-9._-]+$', host_candidate):
            return 1
        return 0
    except Exception:
        return 0

def normalize_proxy(raw_proxy: str):
    try:
        if not raw_proxy or not isinstance(raw_proxy, str):
            return None
        line = raw_proxy.strip().strip('"').strip("'").strip(',').strip()
        if not line or line.startswith('#'):
            return None

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

        if '@' in rest:
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
        else:
            parts = rest.split(':')
            if len(parts) == 2:
                if _score_host_port(parts[0], parts[1]) > 0:
                    host, port = parts[0], parts[1]
                else:
                    return None
            elif len(parts) >= 4:
                score_first = _score_host_port(parts[0], parts[1])
                score_last = _score_host_port(parts[-2], parts[-1])

                if score_first >= score_last and score_first > 0:
                    host, port = parts[0], parts[1]
                    user = parts[2]
                    password = ':'.join(parts[3:])
                elif score_last > score_first and score_last > 0:
                    host, port = parts[-2], parts[-1]
                    user = parts[0]
                    password = ':'.join(parts[1:-2])
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
    try:
        line = text_line.strip()
        if not line.lower().startswith(('http://', 'https://')):
            return False
        parsed = urlparse(line)
        if (parsed.path and parsed.path != '/') or parsed.query or not parsed.port:
            return True
        return False
    except Exception:
        return False

def parse_proxies_from_any_content(content: str) -> list:
    valid_proxies = []
    if not content:
        return valid_proxies

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

    for token in re.split(r'[\r\n\s,;]+', content):
        token = token.strip()
        if not token:
            continue
        norm = normalize_proxy(token)
        if norm:
            valid_proxies.append(norm)

    return list(dict.fromkeys(valid_proxies))

def load_proxies_from_input(raw_text: str) -> tuple:
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
                        errors.append(f"پروکسی معتبری در لینک یافت نشد: {token}")
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

# لیست پروکسی‌ها از کاربر دریافت می‌شود (بدون پروکسی هاردکد شده)
PROXY_LIST = []

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
# توابع کمکی اکانت، توکن و استخراج فایل‌ها (TXT / ZIP / JSON)
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
    if not isinstance(data, dict):
        return None, None
    try:
        for cookie in (data.get('cookies') or []):
            if isinstance(cookie, dict):
                if cookie.get('name') == 'tokenMS':
                    access_token = cookie.get('value')
                elif cookie.get('name') == 'refresh_token':
                    refresh_token = cookie.get('value')
        if not access_token or not refresh_token:
            for origin in (data.get('origins') or []):
                if isinstance(origin, dict):
                    for item in (origin.get('localStorage') or []):
                        if isinstance(item, dict):
                            if item.get('name') == 'tokenMS' and not access_token:
                                access_token = item.get('value')
                            elif item.get('name') == 'refresh_token' and not refresh_token:
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
    if not token or not isinstance(token, str) or '.' not in token:
        return 0, None
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        decoded_bytes = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded_bytes)

        raw_uid = data.get('userId') or data.get('alternativeCustomerId') or data.get('sub')
        uid = 0
        if raw_uid is not None:
            try:
                uid = int(raw_uid)
            except (ValueError, TypeError):
                uid = 0

        cerb_id = (
            data.get('cerberusId')
            or data.get('CerberusId')
            or data.get('cerberus_id')
            or (raw_uid if isinstance(raw_uid, str) and '-' in raw_uid else None)
        )
        return uid, cerb_id
    except Exception:
        return 0, None

async def safe_delete_message(msg: Message):
    try:
        await msg.delete()
    except Exception:
        pass

async def extract_text_from_message(message: Message, bot: Bot) -> str:
    if message.text:
        return message.text
    elif message.document:
        file_info = await bot.get_file(message.document.file_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        return downloaded_file.read().decode('utf-8', errors='ignore')
    return ""

async def extract_urls_from_message(message: Message, bot: Bot, session_dir: str = None) -> list:
    if message.text:
        return re.findall(r'(https?://\S+)', message.text)
    elif message.document:
        fname = (message.document.file_name or "").lower()
        file_info = await bot.get_file(message.document.file_id)
        downloaded_file = await bot.download_file(file_info.file_path)
        raw_bytes = downloaded_file.read()

        if fname.endswith('.zip'):
            urls = []
            temp_dir = session_dir or SESSION_BASE_DIR
            os.makedirs(temp_dir, exist_ok=True)
            temp_zip = os.path.join(temp_dir, f"tmp_{uuid.uuid4()}.zip")
            try:
                with open(temp_zip, "wb") as f:
                    f.write(raw_bytes)
                with zipfile.ZipFile(temp_zip, 'r') as zf:
                    for info in zf.infolist():
                        if info.is_dir() or '__MACOSX' in info.filename:
                            continue
                        if info.filename.lower().endswith(('.txt', '.csv', '.log')):
                            txt = zf.read(info.filename).decode('utf-8', errors='ignore')
                            urls.extend(re.findall(r'(https?://\S+)', txt))
            except Exception:
                pass
            finally:
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
            return urls
        else:
            content = raw_bytes.decode('utf-8', errors='ignore')
            return re.findall(r'(https?://\S+)', content)
    return []

async def extract_account_targets_from_message(message: Message, bot: Bot, session_dir: str) -> list:
    targets = []
    if message.text:
        urls = re.findall(r'(https?://\S+)', message.text)
        for u in urls:
            targets.append({"type": "url", "source": u, "data": None})
        return targets

    if not message.document:
        return targets

    fname = (message.document.file_name or "").lower()
    file_info = await bot.get_file(message.document.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    raw_bytes = downloaded_file.read()

    if fname.endswith('.zip'):
        temp_zip = os.path.join(session_dir, "input_accounts.zip")
        try:
            with open(temp_zip, "wb") as f:
                f.write(raw_bytes)
            with zipfile.ZipFile(temp_zip, 'r') as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    base_name = os.path.basename(info.filename)
                    if not base_name or base_name.startswith('.') or '__MACOSX' in info.filename:
                        continue

                    raw_item = zf.read(info.filename).decode('utf-8', errors='ignore')
                    if base_name.lower().endswith('.json'):
                        try:
                            parsed_json = json.loads(raw_item)
                            if isinstance(parsed_json, dict) and ('cookies' in parsed_json or 'origins' in parsed_json):
                                targets.append({
                                    "type": "json",
                                    "source": base_name,
                                    "data": parsed_json
                                })
                            else:
                                for u in re.findall(r'(https?://\S+)', raw_item):
                                    targets.append({"type": "url", "source": u, "data": None})
                        except Exception:
                            pass
                    elif base_name.lower().endswith(('.txt', '.csv', '.log')):
                        for u in re.findall(r'(https?://\S+)', raw_item):
                            targets.append({"type": "url", "source": u, "data": None})
        except Exception:
            pass
        return targets

    elif fname.endswith('.json'):
        text_content = raw_bytes.decode('utf-8', errors='ignore')
        try:
            parsed_json = json.loads(text_content)
            if isinstance(parsed_json, dict) and ('cookies' in parsed_json or 'origins' in parsed_json):
                targets.append({
                    "type": "json",
                    "source": message.document.file_name or "account.json",
                    "data": parsed_json
                })
                return targets
        except Exception:
            pass
        for u in re.findall(r'(https?://\S+)', text_content):
            targets.append({"type": "url", "source": u, "data": None})
        return targets

    else:
        text_content = raw_bytes.decode('utf-8', errors='ignore')
        for u in re.findall(r'(https?://\S+)', text_content):
            targets.append({"type": "url", "source": u, "data": None})
        return targets

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

    # --- متدهای مربوط به آدرس ---
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

# --- 1. کپی سبد خرید ---
def worker_copy_basket(target_url, api, template_data):
    time.sleep(random.uniform(0.1, 1.0))
    data = fetch_data(target_url)
    if not data:
        return target_url, "error_fetch", None, ["دریافت اطلاعات اکانت از لینک ناموفق بود."]

    acc_token, ref_token = get_tokens_from_data(data)
    if not acc_token and ref_token:
        new_acc, new_ref = api.refresh_token(ref_token)
        if new_acc:
            data = update_tokens_in_data(data, acc_token, new_acc, ref_token, new_ref)
            acc_token = new_acc
            ref_token = new_ref or ref_token

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
            uid, _ = get_user_ids_from_token(acc_token)
            status, response_data = api.add_address(acc_token, uid, template_data['address'])

    if status != 200:
        return target_url, "error_address", data, [f"خطا در ثبت آدرس | HTTP Status: {status} | Response: {response_data}"]

    added_count = 0
    cart_errors = []

    for item in template_data['items']:
        qty = int(item.get('quantity') or 1)
        for _ in range(qty):
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
    if not t_acc and t_ref:
        new_acc, new_ref = api.refresh_token(t_ref)
        if new_acc:
            template_data_json = update_tokens_in_data(template_data_json, t_acc, new_acc, t_ref, new_ref)
            t_acc, t_ref = new_acc, new_ref or t_ref

    t_uid, _ = get_user_ids_from_token(t_acc)
    if not t_uid or t_uid == 0:
        return None, None, "خطا: ساختار توکن اکانت مرجع معتبر نمی‌باشد."

    status, addr_res = api.get_address(t_acc, t_uid)
    if status == 401 and t_ref:
        new_acc, new_ref = api.refresh_token(t_ref)
        if new_acc:
            template_data_json = update_tokens_in_data(template_data_json, t_acc, new_acc, t_ref, new_ref)
            t_acc, t_ref = new_acc, new_ref or t_ref
            t_uid, _ = get_user_ids_from_token(t_acc)
            status, addr_res = api.get_address(t_acc, t_uid)

    template_addr = None
    if status == 200 and isinstance(addr_res, dict) and isinstance(addr_res.get('data'), list) and len(addr_res['data']) > 0:
        template_addr = addr_res['data'][0]
    else:
        status_paged, addr_paged = api.get_all_addresses_paged(t_acc, page_size=15)
        paged_items = (addr_paged.get('data') or {}).get('customerAddressResponseItems') if isinstance(addr_paged, dict) else None
        if status_paged == 200 and isinstance(paged_items, list) and len(paged_items) > 0:
            template_addr = paged_items[0]
        else:
            api.request_logs.append(f"INFO: No saved address found for template account. Using mapInfo as fallback.\n{'-'*50}\n")
            lat, lng = 35.69975, 51.33551
            addr_text = "آدرس استخراج شده از نقشه"
            city_id = None
            try:
                for origin in (template_data_json.get('origins') or []):
                    if isinstance(origin, dict):
                        for item in (origin.get('localStorage') or []):
                            if isinstance(item, dict) and item.get('name') == 'mapInfo':
                                map_info = json.loads(item.get('value') or '{}')
                                if isinstance(map_info, dict) and isinstance(map_info.get('selectedCity'), dict):
                                    lat = map_info['selectedCity'].get('lat', lat)
                                    lng = map_info['selectedCity'].get('lng', lng)
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
    stores_list = (stores_res.get('data') or {}).get('stores') if isinstance(stores_res, dict) else None
    if status != 200 or not isinstance(stores_list, list) or len(stores_list) == 0:
        return None, api.request_logs, f"خطا: هیچ فروشگاهی برای مختصات اکانت مرجع یافت نشد. (HTTP Status: {status})"

    store_ids = [s['storeId'] for s in stores_list if isinstance(s, dict) and 'storeId' in s]
    status, cart_res = api.get_cart(t_acc, t_uid, store_ids)
    cart_results = (cart_res.get('data') or {}).get('result') if isinstance(cart_res, dict) else None
    if status != 200 or not isinstance(cart_results, list) or len(cart_results) == 0:
        return None, api.request_logs, f"خطا: امکان بازیابی سبد خرید اکانت مرجع وجود ندارد. (HTTP Status: {status})"

    cart_data = cart_results[0]
    cart_items = cart_data.get('items') or []
    cart_store_id = cart_data.get('storeId')

    if not cart_items:
        return None, api.request_logs, "خطا: سبد خرید اکانت مرجع خالی است."

    template_data = {
        'address': {
            'lat': template_addr['lat'],
            'lng': template_addr['lng'],
            'address': template_addr.get('address') or 'آدرس ثبت شده',
            'plaque': template_addr.get('plaque') or '0',
            'unit': template_addr.get('unit') or '1',
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
                    if file_name.lower().endswith('.json'):
                        file_name = file_name[:-5]
                    dest_file = os.path.join(updated_dir, f"{file_name}.json")
                    if os.path.exists(dest_file):
                        dest_file = os.path.join(updated_dir, f"{file_name}_{counter}.json")
                    with open(dest_file, "w", encoding="utf-8") as f:
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
def worker_delete_addresses(target_item, api):
    time.sleep(random.uniform(0.1, 1.0))
    source_name = target_item["source"]
    data = target_item["data"] if target_item["type"] == "json" else fetch_data(source_name)
    if not data:
        return source_name, "error_fetch", 0

    acc_token, ref_token = get_tokens_from_data(data)
    if not acc_token and ref_token:
        new_acc, _ = api.refresh_token(ref_token)
        if new_acc:
            acc_token = new_acc

    if not acc_token:
        return source_name, "error_token", 0

    uid, _ = get_user_ids_from_token(acc_token)
    total_deleted = 0

    for attempt in range(10):
        status, addr_res = api.get_all_addresses_paged(acc_token, page_size=50)
        if status == 401 and ref_token:
            new_acc, _ = api.refresh_token(ref_token)
            if new_acc:
                acc_token = new_acc
                uid, _ = get_user_ids_from_token(acc_token)
                status, addr_res = api.get_all_addresses_paged(acc_token, page_size=50)

        addresses = []
        if status == 200 and isinstance(addr_res, dict):
            addresses = (addr_res.get('data') or {}).get('customerAddressResponseItems') or []

        if not addresses and uid:
            r_status, r_res = api.get_address(acc_token, uid)
            if r_status == 200 and isinstance(r_res, dict) and isinstance(r_res.get('data'), list):
                addresses = r_res['data']
            elif status != 200 and attempt == 0:
                return source_name, "error_fetch_address", total_deleted

        if not addresses:
            break

        deleted_in_round = 0
        for addr in addresses:
            addr_id = addr.get('id') if isinstance(addr, dict) else None
            if addr_id:
                del_status, _ = api.delete_address(acc_token, addr_id)
                if del_status == 200:
                    total_deleted += 1
                    deleted_in_round += 1
                time.sleep(random.uniform(0.3, 0.8))

        if deleted_in_round == 0:
            break

    return source_name, "success", total_deleted

def process_delete_all_links(session_dir, target_items):
    api = OkalaAPI()
    stats = {"total_targets": len(target_items), "success_accounts": 0, "total_deleted_addresses": 0, "errors": 0}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(worker_delete_addresses, item, api): item for item in target_items}
        for future in as_completed(futures):
            try:
                _, result, deleted = future.result()
                if result == "success":
                    stats["success_accounts"] += 1
                    stats["total_deleted_addresses"] += deleted
                else:
                    stats["errors"] += 1
            except Exception:
                stats["errors"] += 1
    return stats, api.request_logs


# --- 3. بررسی تخفیف‌ها (به همراه گزارش زنده و استخراج تمامی کدها) ---
def worker_check_discount(target_item, api):
    time.sleep(random.uniform(0.1, 1.0))
    source_name = target_item["source"]
    is_json_file = (target_item["type"] == "json")

    data = target_item["data"] if is_json_file else fetch_data(source_name)
    if not data:
        return source_name, [], "error_fetch", "دریافت اطلاعات ناموفق", None, is_json_file

    acc_token, ref_token = get_tokens_from_data(data)
    if not acc_token and ref_token:
        new_acc, new_ref = api.refresh_token(ref_token)
        if new_acc:
            data = update_tokens_in_data(data, acc_token, new_acc, ref_token, new_ref)
            acc_token = new_acc
            ref_token = new_ref or ref_token

    if not acc_token:
        return source_name, [], "error_token", "توکن در اکانت یافت نشد", data, is_json_file

    _, cerb_id = get_user_ids_from_token(acc_token)
    if not cerb_id and ref_token:
        new_acc, new_ref = api.refresh_token(ref_token)
        if new_acc:
            data = update_tokens_in_data(data, acc_token, new_acc, ref_token, new_ref)
            acc_token = new_acc
            ref_token = new_ref or ref_token
            _, cerb_id = get_user_ids_from_token(acc_token)

    if not cerb_id:
        return source_name, [], "error_uuid", "Cerberus ID در توکن پیدا نشد", data, is_json_file

    status, res = api.get_discounts(acc_token, cerb_id)
    if status == 401 and ref_token:
        new_acc, new_ref = api.refresh_token(ref_token)
        if new_acc:
            data = update_tokens_in_data(data, acc_token, new_acc, ref_token, new_ref)
            acc_token = new_acc
            _, new_cerb = get_user_ids_from_token(acc_token)
            cerb_id = new_cerb or cerb_id
            status, res = api.get_discounts(acc_token, cerb_id)

    if status == 200 and isinstance(res, dict):
        discounts = res.get('data') or []
        if not isinstance(discounts, list) or not discounts:
            return source_name, [], "success", None, data, is_json_file

        valid_discounts = []
        for d in discounts:
            if not isinstance(d, dict):
                continue
            if d.get('isUsed') is True or d.get('isActive') is False:
                continue
            amt = d.get('discountAmount') or 0
            pct = d.get('discountPercentage') or 0
            if (isinstance(amt, (int, float)) and amt > 0) or (isinstance(pct, (int, float)) and pct > 0):
                valid_discounts.append({
                    'code': d.get('code') or 'بدون کد',
                    'amount': amt if isinstance(amt, (int, float)) else 0,
                    'percentage': pct if isinstance(pct, (int, float)) else 0,
                    'min_Order': d.get('minimumFactoreAmount') or 0,
                    'expiration': d.get('expirationDate') or '-',
                    'name': d.get('name') or d.get('discountName') or ''
                })

        valid_discounts.sort(key=lambda x: (x['amount'], x['percentage']), reverse=True)
        return source_name, valid_discounts, "success", None, data, is_json_file
    elif status == 401:
        return source_name, [], "expired", "توکن منقضی شده است", data, is_json_file
    else:
        return source_name, [], "error_api", f"HTTP Status: {status} - {res}", data, is_json_file

def format_live_discount_progress(stats: dict) -> str:
    total = stats.get("total", 0)
    processed = stats.get("processed", 0)
    pct = int((processed / total) * 100) if total > 0 else 0
    filled = int(pct / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)

    breakdown_text = ""
    if stats.get("breakdown"):
        lines = [f"▫️ تخفیف {label}: {cnt} عدد" for label, cnt in stats["breakdown"].items()]
        breakdown_text = "\n📋 تفکیک کدهای یافت‌شده تا این لحظه:\n" + "\n".join(lines) + "\n"

    return (
        f"🔎 گزارش زنده بررسی تخفیف‌ها...\n\n"
        f"{bar} {pct}% ({processed} از {total})\n\n"
        f"🎁 اکانت دارای تخفیف: {stats['with_discount']}\n"
        f"🎟 کل کدهای تخفیف یافت‌شده: {stats['total_codes']}\n"
        f"➖ بدون تخفیف / سوخته: {stats['no_discount']}\n"
        f"🔴 خطا: {stats['errors']}\n"
        f"{breakdown_text}"
    )

def process_discount_links(session_dir, target_items, progress_callback=None):
    api = OkalaAPI()
    stats = {
        "total": len(target_items),
        "processed": 0,
        "with_discount": 0,
        "total_codes": 0,
        "no_discount": 0,
        "errors": 0,
        "breakdown": {}
    }
    discounted_items = []
    all_errors = []
    amount_counter = Counter()

    discounted_json_dir = os.path.join(session_dir, "Discounted_Accounts")
    has_discounted_json = False

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(worker_check_discount, item, api): item for item in target_items}
        file_idx = 1
        for future in as_completed(futures):
            try:
                source_name, valid_discounts, res, err, updated_data, is_json_file = future.result()
                if res == "success":
                    if valid_discounts:
                        stats["with_discount"] += 1
                        stats["total_codes"] += len(valid_discounts)
                        discounted_items.append((source_name, valid_discounts))

                        for d_info in valid_discounts:
                            amt = d_info.get("amount", 0)
                            pct = d_info.get("percentage", 0)
                            if amt > 0:
                                amount_k = int(amt / 10000)
                                amount_counter[f"{amount_k} هزار تومانی"] += 1
                            elif pct > 0:
                                amount_counter[f"{int(pct)} درصدی"] += 1

                        if is_json_file and updated_data:
                            os.makedirs(discounted_json_dir, exist_ok=True)
                            has_discounted_json = True
                            safe_name = os.path.basename(source_name)
                            if not safe_name.lower().endswith('.json'):
                                safe_name += '.json'
                            dest_path = os.path.join(discounted_json_dir, safe_name)
                            if os.path.exists(dest_path):
                                dest_path = os.path.join(discounted_json_dir, f"{file_idx}_{safe_name}")
                            with open(dest_path, "w", encoding="utf-8") as jf:
                                json.dump(updated_data, jf, ensure_ascii=False, indent=2)
                            file_idx += 1
                    else:
                        stats["no_discount"] += 1
                else:
                    stats["errors"] += 1
                    if err:
                        all_errors.append(f"🔗 اکانت:\n{source_name}\nخطا: {err}\n{'-'*40}")
            except Exception as e:
                stats["errors"] += 1
                all_errors.append(f"🔗 اکانت:\nخطای سیستم: {str(e)}\n{'-'*40}")

            stats["processed"] += 1
            stats["breakdown"] = dict(amount_counter.most_common())
            if progress_callback:
                try:
                    progress_callback(stats.copy())
                except Exception:
                    pass

    report_file = None
    if discounted_items:
        report_file = os.path.join(session_dir, "Discounted_Links_Report.txt")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("گزارش اکانت‌های دارای تخفیف (تمامی کدهای فعال هر اکانت):\n" + "="*55 + "\n\n")
            for source_name, d_list in sorted(
                discounted_items,
                key=lambda x: (max(d['amount'] for d in x[1]), len(x[1])),
                reverse=True
            ):
                f.write(f"🔗 اکانت ({len(d_list)} کد تخفیف):\n{source_name}\n")
                for idx, d_info in enumerate(d_list, 1):
                    amt = d_info['amount']
                    pct = d_info['percentage']
                    code_str = d_info['code']
                    min_ord = d_info['min_Order']
                    exp_date = str(d_info['expiration']).replace('T', ' ')

                    if amt > 0:
                        val_text = f"{int(amt/10000)} هزار تومانی ({int(amt/10):,} تومان)"
                    else:
                        val_text = f"{int(pct)}% تخفیف"

                    min_text = f" | حداقل خرید: {int(min_ord/10):,} تومان" if min_ord > 0 else ""
                    f.write(f"   {idx}. 🎁 {val_text} | کد: {code_str}{min_text} | انقضا: {exp_date}\n")
                f.write("-" * 50 + "\n\n")

    discounted_zip_file = None
    if has_discounted_json:
        discounted_zip_file = shutil.make_archive(
            os.path.join(session_dir, "Discounted_Accounts"), 'zip', discounted_json_dir
        )

    err_file = None
    if all_errors:
        err_file = os.path.join(session_dir, "Discount_Errors.txt")
        with open(err_file, "w", encoding="utf-8") as f:
            f.write("گزارش خطاهای بررسی تخفیف:\n============================\n\n")
            f.write("\n".join(all_errors))

    stats["breakdown"] = dict(amount_counter.most_common())
    return stats, report_file, discounted_zip_file, err_file, api.request_logs


# --- 4. گزارش وضعیت سبد خرید ---
def worker_check_cart_status(target_item, api):
    time.sleep(random.uniform(0.1, 1.0))
    source_name = target_item["source"]
    data = target_item["data"] if target_item["type"] == "json" else fetch_data(source_name)
    if not data:
        return source_name, 0, 0, "error_fetch", "دریافت اطلاعات ناموفق"

    acc_token, ref_token = get_tokens_from_data(data)
    if not acc_token and ref_token:
        new_acc, _ = api.refresh_token(ref_token)
        if new_acc:
            acc_token = new_acc

    if not acc_token:
        return source_name, 0, 0, "error_token", "توکن یافت نشد"

    uid, _ = get_user_ids_from_token(acc_token)
    if not uid or uid == 0:
        return source_name, 0, 0, "error_uuid", "User ID نامعتبر"

    status, addr_res = api.get_address(acc_token, uid)
    if status == 401 and ref_token:
        new_acc, _ = api.refresh_token(ref_token)
        if new_acc:
            acc_token = new_acc
            uid, _ = get_user_ids_from_token(acc_token)
            status, addr_res = api.get_address(acc_token, uid)

    lat, lng = 35.69975, 51.33551
    if status == 200 and isinstance(addr_res, dict) and isinstance(addr_res.get('data'), list) and len(addr_res['data']) > 0:
        addr_data = addr_res['data'][0]
        lat = addr_data.get('lat', lat)
        lng = addr_data.get('lng', lng)
    else:
        status_p, addr_p = api.get_all_addresses_paged(acc_token, page_size=15)
        paged_list = (addr_p.get('data') or {}).get('customerAddressResponseItems') if isinstance(addr_p, dict) else None
        if status_p == 200 and isinstance(paged_list, list) and len(paged_list) > 0:
            addr_data = paged_list[0]
            lat = addr_data.get('lat', lat)
            lng = addr_data.get('lng', lng)
        elif status != 200 and status_p != 200:
            return source_name, 0, 0, "error_api", f"خطا در دریافت آدرس (HTTP {status})"
        else:
            try:
                for origin in (data.get('origins') or []):
                    if isinstance(origin, dict):
                        for item in (origin.get('localStorage') or []):
                            if isinstance(item, dict) and item.get('name') == 'mapInfo':
                                map_info = json.loads(item.get('value') or '{}')
                                if isinstance(map_info, dict) and isinstance(map_info.get('selectedCity'), dict):
                                    lat = map_info['selectedCity'].get('lat', lat)
                                    lng = map_info['selectedCity'].get('lng', lng)
            except Exception:
                pass

    status, stores_res = api.get_stores(acc_token, lat, lng, uid)
    stores_list = (stores_res.get('data') or {}).get('stores') if isinstance(stores_res, dict) else None
    if status != 200 or not isinstance(stores_list, list) or len(stores_list) == 0:
        return source_name, 0, 0, "error_api", f"خطا در دریافت فروشگاه‌ها (HTTP {status})"

    store_ids = [s['storeId'] for s in stores_list if isinstance(s, dict) and 'storeId' in s]
    status, cart_res = api.get_cart(acc_token, uid, store_ids)

    if status == 200 and isinstance(cart_res, dict):
        cart_data = (cart_res.get('data') or {}).get('result') or []
        if isinstance(cart_data, list) and len(cart_data) > 0:
            total_items = sum(cart.get('count', 0) for cart in cart_data if isinstance(cart, dict))
            total_price = sum(cart.get('totalPrice', 0) for cart in cart_data if isinstance(cart, dict))
            return source_name, total_items, total_price, "success", None
        return source_name, 0, 0, "success", None

    return source_name, 0, 0, "error_api", f"خطا در دریافت سبد خرید (HTTP {status})"

def process_cart_report_links(session_dir, target_items):
    api = OkalaAPI()
    stats = {"total": len(target_items), "with_cart": 0, "empty_cart": 0, "errors": 0}
    cart_links = []
    all_errors = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(worker_check_cart_status, item, api): item for item in target_items}
        for future in as_completed(futures):
            try:
                source_name, items, price, res, err = future.result()
                if res == "success":
                    if items > 0:
                        stats["with_cart"] += 1
                        cart_links.append((source_name, items, price))
                    else:
                        stats["empty_cart"] += 1
                else:
                    stats["errors"] += 1
                    if err:
                        all_errors.append(f"🔗 اکانت:\n{source_name}\nخطا: {err}\n{'-'*40}")
            except Exception as e:
                stats["errors"] += 1
                all_errors.append(f"🔗 اکانت:\nخطای سیستم: {str(e)}\n{'-'*40}")

    report_file = None
    if cart_links:
        report_file = os.path.join(session_dir, "Cart_Report.txt")
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("گزارش اکانت‌های دارای سبد خرید:\n" + "="*40 + "\n\n")
            for source_name, items, price in sorted(cart_links, key=lambda x: x[1], reverse=True):
                f.write(f"🛒 سبد خرید با {items} کالا (مبلغ {int(price/10):,} تومان):\n{source_name}\n\n")

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
async def ensure_proxies_set(message: Message, state: FSMContext) -> bool:
    if not PROXY_LIST:
        await state.set_state(BotStates.waiting_for_proxies)
        await message.answer(
            "⚠️ هنوز هیچ پروکسی‌ای در ربات ثبت نشده است!\n\n"
            "لطفاً ابتدا لیست پروکسی‌های خود را (به صورت متن، لینک یا فایل .txt) ارسال کنید تا ثبت شوند:"
        )
        return False
    return True

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    proxy_status = (
        f"🟢 تعداد پروکسی‌های فعال: {len(PROXY_LIST)}"
        if PROXY_LIST
        else "🔴 هیچ پروکسی‌ای ثبت نشده است (لطفاً از دکمه تنظیم پروکسی استفاده کنید)"
    )
    await message.answer(
        f"سیستم چندمنظوره فعال است.\n"
        f"🌐 وضعیت پروکسی: {proxy_status}\n\n"
        "لطفاً از منوی زیر یک گزینه را انتخاب کنید:",
        reply_markup=main_keyboard
    )

@router.message(F.text == "🛒 همگام‌سازی سبد خرید")
async def btn_sync_cart(message: Message, state: FSMContext):
    if not await ensure_proxies_set(message, state):
        return
    await state.set_state(BotStates.waiting_for_sync_links)
    await message.answer(
        "🛒 همگام‌سازی سبد خرید\n\n"
        "لطفاً لینک‌ها را متنی ارسال کنید یا یک فایل .txt شامل لینک‌ها بفرستید (لینک اول به عنوان الگو در نظر گرفته می‌شود)."
    )

@router.message(F.text == "🗑 پاک کردن آدرس‌ها")
async def btn_delete_addresses(message: Message, state: FSMContext):
    if not await ensure_proxies_set(message, state):
        return
    await state.set_state(BotStates.waiting_for_delete_links)
    await message.answer(
        "🗑 پاک کردن آدرس‌ها\n\n"
        "لطفاً لینک‌ها را ارسال کنید یا یک فایل .txt / .zip حاوی اکانت‌ها آپلود کنید."
    )

@router.message(F.text == "🔎 بررسی تخفیف‌ها")
async def btn_check_discounts(message: Message, state: FSMContext):
    if not await ensure_proxies_set(message, state):
        return
    await state.set_state(BotStates.waiting_for_discount_links)
    await message.answer(
        "🔎 بررسی تخفیف‌ها (به همراه گزارش زنده)\n\n"
        "می‌توانید یکی از موارد زیر را ارسال کنید:\n"
        "• فایل .zip (حاوی فایل‌های .json اکانت‌ها یا فایل .txt لینک‌ها)\n"
        "• فایل .txt یا .json\n"
        "• لیست لینک‌ها به صورت پیام متنی\n\n"
        "تمامی کدهای تخفیف فعال در هر اکانت استخراج و به صورت زنده گزارش می‌شوند."
    )

@router.message(F.text == "📦 گزارش موجودی سبد خرید")
async def btn_check_carts(message: Message, state: FSMContext):
    if not await ensure_proxies_set(message, state):
        return
    await state.set_state(BotStates.waiting_for_cart_report_links)
    await message.answer(
        "📦 گزارش وضعیت سبد خرید\n\n"
        "لطفاً لینک‌ها را ارسال کنید یا یک فایل .txt / .zip آپلود کنید.\n"
        "اکانت‌هایی که دارای سبد خرید هستند شناسایی و در فایلی جداگانه گزارش می‌شوند."
    )

@router.message(F.text == "🌐 تنظیم / بروزرسانی پروکسی")
async def btn_update_proxies(message: Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_proxies)
    await message.answer(
        f"🌐 تنظیم و بروزرسانی پروکسی‌ها\n"
        f"تعداد پروکسی‌های فعال فعلی: {len(PROXY_LIST)}\n\n"
        "می‌توانید یکی از موارد زیر را ارسال کنید:\n"
        "1️⃣ لینک (URL) حاوی لیست پروکسی‌ها (متنی یا JSON)\n"
        "2️⃣ فایل .txt حاوی پروکسی‌ها یا لینک‌ها\n"
        "3️⃣ متن مستقیم لیست پروکسی‌ها با هر فرمتی:\n"
        "• ip:port یا host:port\n"
        "• user:pass@host:port یا host:port@user:pass\n"
        "• host:port:user:pass یا user:pass:host:port"
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
        f"✅ لیست پروکسی‌ها با موفقیت بروزرسانی شد!\n\n"
        f"🟢 تعداد پروکسی‌های معتبر بارگذاری‌شده: {len(PROXY_LIST)}\n"
        f"🔹 نمونه فرمت استانداردشده:\n{sample}"
    )
    if errs:
        report += f"\n\n⚠️ هشدارها ({len(errs)} مورد):\n" + "\n".join(errs[:3])

    await msg.edit_text(report)
    await state.clear()

# ----------- هندلر وضعیت همگام سازی -----------
@router.message(BotStates.waiting_for_sync_links, F.text | F.document)
async def handle_sync_links(message: Message, bot: Bot, state: FSMContext):
    session_dir = os.path.join(SESSION_BASE_DIR, str(uuid.uuid4()))
    os.makedirs(session_dir, exist_ok=True)

    urls = await extract_urls_from_message(message, bot, session_dir)
    if len(urls) < 2:
        shutil.rmtree(session_dir, ignore_errors=True)
        await message.answer("خطا: لطفاً حداقل ۲ لینک (یک الگو و حداقل یک هدف) در پیام یا فایل ارسال کنید.")
        return

    msg = await message.answer(f"در حال پردازش...\nاکانت مرجع دریافت شد. تعداد اهداف: {len(urls)-1}")

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
    total_qty = sum(int(item.get('quantity') or 1) for item in template_data['items'])

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

    await safe_delete_message(msg)
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
    session_dir = os.path.join(SESSION_BASE_DIR, str(uuid.uuid4()))
    os.makedirs(session_dir, exist_ok=True)

    target_items = await extract_account_targets_from_message(message, bot, session_dir)
    if not target_items:
        shutil.rmtree(session_dir, ignore_errors=True)
        await message.answer("خطا: هیچ لینک یا فایل اکانت معتبری یافت نشد.")
        return

    msg = await message.answer(f"در حال پردازش برای حذف آدرس...\nتعداد اکانت‌ها: {len(target_items)}")
    stats, logs = await asyncio.to_thread(process_delete_all_links, session_dir, target_items)

    await safe_delete_message(msg)
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

# ----------- هندلر وضعیت بررسی تخفیف با گزارش زنده (لینک / TXT / ZIP) -----------
@router.message(BotStates.waiting_for_discount_links, F.text | F.document)
async def handle_discount_links(message: Message, bot: Bot, state: FSMContext):
    session_dir = os.path.join(SESSION_BASE_DIR, str(uuid.uuid4()))
    os.makedirs(session_dir, exist_ok=True)

    target_items = await extract_account_targets_from_message(message, bot, session_dir)
    if not target_items:
        shutil.rmtree(session_dir, ignore_errors=True)
        await message.answer("خطا: هیچ لینک یا فایل اکانت معتبری در ورودی (متن / TXT / ZIP) یافت نشد.")
        return

    initial_stats = {
        "total": len(target_items),
        "processed": 0,
        "with_discount": 0,
        "total_codes": 0,
        "no_discount": 0,
        "errors": 0,
        "breakdown": {}
    }
    msg = await message.answer(format_live_discount_progress(initial_stats))

    loop = asyncio.get_running_loop()
    last_edit_time = [0.0]
    last_text = [""]
    is_editing = [False]

    async def _safe_edit_progress(new_text: str):
        if is_editing[0] or new_text == last_text[0]:
            return
        is_editing[0] = True
        try:
            await msg.edit_text(new_text)
            last_text[0] = new_text
        except Exception:
            pass
        finally:
            is_editing[0] = False

    def progress_callback(current_stats: dict):
        now = time.monotonic()
        is_finished = current_stats["processed"] >= current_stats["total"]
        # بروزرسانی پیام هر 2.5 ثانیه یا در پایان کار (برای جلوگیری از Flood Limit تلگرام)
        if not is_finished and (now - last_edit_time[0] < 2.5):
            return
        last_edit_time[0] = now
        live_text = format_live_discount_progress(current_stats)
        asyncio.run_coroutine_threadsafe(_safe_edit_progress(live_text), loop)

    stats, report_file, discounted_zip_file, err_file, logs = await asyncio.to_thread(
        process_discount_links, session_dir, target_items, progress_callback
    )

    breakdown_text = ""
    if stats.get("breakdown"):
        lines = [f"▫️ تخفیف {label}: {cnt} عدد" for label, cnt in stats["breakdown"].items()]
        breakdown_text = "\n📋 تفکیک کل کدهای تخفیف:\n" + "\n".join(lines) + "\n"

    final_report = (
        "✅ گزارش نهایی بررسی تخفیف‌ها:\n\n"
        f"🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 100% ({stats['total']} از {stats['total']})\n\n"
        f"کل اکانت‌های بررسی‌شده: {stats['total']}\n"
        f"🎁 اکانت‌های دارای تخفیف: {stats['with_discount']}\n"
        f"🎟 مجموع کل کدهای تخفیف یافت‌شده: {stats.get('total_codes', 0)}\n"
        f"➖ بدون تخفیف/سوخته: {stats['no_discount']}\n"
        f"🔴 خطا: {stats['errors']}\n"
        f"{breakdown_text}"
    )

    try:
        await msg.edit_text(final_report)
    except Exception:
        await safe_delete_message(msg)
        await message.answer(final_report)

    if report_file and os.path.exists(report_file):
        await message.answer_document(
            document=FSInputFile(report_file),
            caption="🎁 فایل گزارش اکانت‌های دارای تخفیف (شامل تمامی کدهای هر اکانت)"
        )

    if discounted_zip_file and os.path.exists(discounted_zip_file):
        await message.answer_document(
            document=FSInputFile(discounted_zip_file),
            caption="📦 فایل ZIP اکانت‌های JSON دارای تخفیف (جداشده و آماده استفاده)"
        )

    if err_file and os.path.exists(err_file):
        await message.answer_document(document=FSInputFile(err_file), caption="⚠️ فایل گزارش خطاها")

    shutil.rmtree(session_dir, ignore_errors=True)
    await state.clear()

# ----------- هندلر وضعیت گزارش سبد خرید -----------
@router.message(BotStates.waiting_for_cart_report_links, F.text | F.document)
async def handle_cart_report_links(message: Message, bot: Bot, state: FSMContext):
    session_dir = os.path.join(SESSION_BASE_DIR, str(uuid.uuid4()))
    os.makedirs(session_dir, exist_ok=True)

    target_items = await extract_account_targets_from_message(message, bot, session_dir)
    if not target_items:
        shutil.rmtree(session_dir, ignore_errors=True)
        await message.answer("خطا: هیچ لینک یا فایل اکانت معتبری یافت نشد.")
        return

    msg = await message.answer(f"📦 در حال بررسی سبد خریدهای اکانت‌ها...\nتعداد اکانت‌ها: {len(target_items)}")

    stats, report_file, err_file, logs = await asyncio.to_thread(
        process_cart_report_links, session_dir, target_items
    )

    await safe_delete_message(msg)
    report = (
        "📊 گزارش بررسی وضعیت سبد خرید:\n\n"
        f"کل اکانت‌ها: {stats['total']}\n"
        f"🛒 دارای سبد خرید: {stats['with_cart']}\n"
        f"➖ سبد خالی/سوخته: {stats['empty_cart']}\n"
        f"🔴 خطا: {stats['errors']}"
    )
    await message.answer(report)

    if report_file and os.path.exists(report_file):
        await message.answer_document(
            document=FSInputFile(report_file),
            caption="🛒 فایل اکانت‌های دارای سبد خرید"
        )

    if err_file and os.path.exists(err_file):
        await message.answer_document(
            document=FSInputFile(err_file),
            caption="⚠️ فایل گزارش خطاها"
        )

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
