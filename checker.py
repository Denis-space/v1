#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VPN конфиг-чекер v5.0 - Для Happ (SHARKIVPN)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Проверка VLESS конфигов через google.com
• Генерация JSON для sing-box/Happ с автовыбором
• Авто-загрузка на GitHub: Denis-space/v1
• Обновление каждый час
"""

import re, sys, os, json, time, base64, socket, ssl, urllib.request
from datetime import datetime
from collections import defaultdict
from typing import Optional
import urllib.error

# ─────────────────────────────────────────────────────────────
# НАСТРОЙКИ GITHUB
# ─────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")
GITHUB_REPO = "Denis-space/v1"
GITHUB_BRANCH = "main"
GITHUB_SERVERS_FILE = "servers.txt"      # Список URL конфигов
GITHUB_JSON_FILE = "singbox_config.json" # JSON для Happ

# ─────────────────────────────────────────────────────────────
# НАСТРОЙКИ ПРОВЕРКИ
# ─────────────────────────────────────────────────────────────
CHECK_TIMEOUT = 10
CHECK_URL = "https://www.google.com/generate_204"
RTT_MAX = 2000      # Максимальный пинг (отбрасываем >2000мс)
RTT_FAST = 1000     # <1000мс → ⚡, ≥1000мс → 🐢

# Только VLESS конфиги
SUPPORTED = ("vless://",)

# Источники (только VLESS)
_BASE_IGARECK = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main"
_BASE_GOIDA = "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror"

SOURCES = {
    # Белые списки (igareck) - для WiFi группы
    "igareck-mobile-1":   (f"{_BASE_IGARECK}/Vless-Reality-White-Lists-Rus-Mobile.txt", "whitelist"),
    "igareck-mobile-2":   (f"{_BASE_IGARECK}/Vless-Reality-White-Lists-Rus-Mobile-2.txt", "whitelist"),
    
    # Чёрные списки (goida) - для Обход группы
    "goida-1":   (f"{_BASE_GOIDA}/1.txt", "blacklist"),
    "goida-6":   (f"{_BASE_GOIDA}/6.txt", "blacklist"),
    "goida-22":  (f"{_BASE_GOIDA}/22.txt", "blacklist"),
    "goida-23":  (f"{_BASE_GOIDA}/23.txt", "blacklist"),
    "goida-24":  (f"{_BASE_GOIDA}/24.txt", "blacklist"),
    "goida-25":  (f"{_BASE_GOIDA}/25.txt", "blacklist"),
}

DEFAULT_SOURCES = ["igareck-mobile-1", "igareck-mobile-2", "goida-1", "goida-6", "goida-25"]

# Кэш
CACHE_FILE = "vpn_cache.json"
CACHE_TTL = 3600  # 1 час

# Провайдер для отображения в Happ
PROVIDER_NAME = "SHARKIVPN"

# ─────────────────────────────────────────────────────────────
# СТРАНЫ (флаги и названия)
# ─────────────────────────────────────────────────────────────
COUNTRIES = {
    "ru": {"flag": "🇷🇺", "name": "Россия"},
    "de": {"flag": "🇩🇪", "name": "Германия"},
    "nl": {"flag": "🇳🇱", "name": "Нидерланды"},
    "us": {"flag": "🇺🇸", "name": "США"},
    "pl": {"flag": "🇵🇱", "name": "Польша"},
    "fi": {"flag": "🇫🇮", "name": "Финляндия"},
    "fr": {"flag": "🇫🇷", "name": "Франция"},
    "uk": {"flag": "🇬🇧", "name": "Великобритания"},
    "jp": {"flag": "🇯🇵", "name": "Япония"},
    "sg": {"flag": "🇸🇬", "name": "Сингапур"},
    "ca": {"flag": "🇨🇦", "name": "Канада"},
    "au": {"flag": "🇦🇺", "name": "Австралия"},
    "br": {"flag": "🇧🇷", "name": "Бразилия"},
    "it": {"flag": "🇮🇹", "name": "Италия"},
    "es": {"flag": "🇪🇸", "name": "Испания"},
    "tr": {"flag": "🇹🇷", "name": "Турция"},
    "ch": {"flag": "🇨🇭", "name": "Швейцария"},
    "se": {"flag": "🇸🇪", "name": "Швеция"},
    "no": {"flag": "🇳🇴", "name": "Норвегия"},
    "dk": {"flag": "🇩🇰", "name": "Дания"},
    "kz": {"flag": "🇰🇿", "name": "Казахстан"},
}

def get_country_info(host: str, sni: str) -> tuple:
    """Определяет страну по хосту/SNI"""
    text = ((host or "") + " " + (sni or "")).lower()
    
    for code, info in COUNTRIES.items():
        if f".{code}" in text or f"-{code}" in text or text.startswith(f"{code}."):
            return info["flag"], info["name"]
    
    return "🌍", "Unknown"

# ─────────────────────────────────────────────────────────────
# ПАРСИНГ VLESS КОНФИГА
# ─────────────────────────────────────────────────────────────
def parse_vless_config(line: str) -> Optional[dict]:
    """Парсит VLESS URL конфига"""
    raw = line.strip().split("#", 1)[0].strip()
    
    if not raw.startswith("vless://"):
        return None
    
    try:
        # Формат: vless://uuid@host:port?params
        match = re.match(r"vless://([^@]+)@([^:/?#\s]+):(\d+)\??([^#\s]*)$", raw)
        if not match:
            return None
        
        uuid, host, port, params = match.groups()
        port = int(port)
        
        # Парсим параметры
        params_dict = {}
        if params:
            for p in params.split("&"):
                if "=" in p:
                    k, v = p.split("=", 1)
                    params_dict[k] = v
        
        # Извлекаем важные параметры
        sni = params_dict.get("sni", host)
        flow = params_dict.get("flow", "")
        pbk = params_dict.get("pbk", "")  # public key для reality
        sid = params_dict.get("sid", "")  # short id для reality
        fp = params_dict.get("fp", "chrome")  # fingerprint
        
        return {
            "raw": raw,
            "uuid": uuid,
            "host": host,
            "port": port,
            "sni": sni,
            "flow": flow,
            "pbk": pbk,
            "sid": sid,
            "fp": fp,
            "params": params_dict
        }
        
    except Exception as e:
        return None

# ─────────────────────────────────────────────────────────────
# ПРОВЕРКА КОНФИГА
# ─────────────────────────────────────────────────────────────
def check_config(config: dict) -> Optional[float]:
    """Проверяет конфиг через HTTPS запрос к google.com"""
    host = config["host"]
    port = config["port"]
    sni = config["sni"]
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CHECK_TIMEOUT)
        
        start_time = time.time()
        sock.connect((host, port))
        
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        with context.wrap_socket(sock, server_hostname=sni) as ssock:
            request = (
                f"GET /generate_204 HTTP/1.1\r\n"
                f"Host: www.google.com\r\n"
                f"User-Agent: Mozilla/5.0\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode()
            
            ssock.send(request)
            response = ssock.recv(1024)
            
            if response and (b"204" in response or b"200" in response):
                rtt = (time.time() - start_time) * 1000
                return rtt if rtt < RTT_MAX else None
                
    except Exception:
        pass
    
    return None

# ─────────────────────────────────────────────────────────────
# ЗАГРУЗКА КОНФИГОВ
# ─────────────────────────────────────────────────────────────
def fetch_configs(sources: list) -> list:
    """Загружает VLESS конфиги из источников"""
    configs = []
    
    for name in sources:
        if name not in SOURCES:
            continue
        
        url, stype = SOURCES[name]
        print(f"  📥 {name} ({stype})...")
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                text = response.read().decode("utf-8", errors="ignore")
                lines = [l.strip() for l in text.splitlines() 
                        if l.strip().startswith("vless://")]
                
                for line in lines:
                    configs.append((line, stype))
                
                print(f"    ✓ {len(lines)} VLESS конфигов")
        except Exception as e:
            print(f"    ✗ Ошибка: {e}")
    
    return configs

# ─────────────────────────────────────────────────────────────
# КЭШ
# ─────────────────────────────────────────────────────────────
def load_cache() -> dict:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                now = time.time()
                return {k: v for k, v in data.items() 
                       if now - v.get("ts", 0) < CACHE_TTL}
    except:
        pass
    return {}

def save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except:
        pass

# ─────────────────────────────────────────────────────────────
# ОСНОВНАЯ ПРОВЕРКА
# ─────────────────────────────────────────────────────────────
def check_all_configs(configs: list, use_cache: bool = True) -> list:
    """Проверяет все конфиги и возвращает рабочие с RTT"""
    # Дедупликация
    unique = {}
    for line, stype in configs:
        raw = line.split("#", 1)[0].strip()
        if raw not in unique:
            unique[raw] = stype
    
    print(f"\n📊 Уникальных VLESS конфигов: {len(unique)}")
    
    cache = load_cache() if use_cache else {}
    alive = []
    to_check = []
    
    for raw, stype in unique.items():
        if raw in cache:
            rtt = cache[raw].get("rtt")
            if rtt and rtt < RTT_MAX:
                alive.append((raw, stype, rtt))
        else:
            to_check.append((raw, stype))
    
    print(f"📦 Из кэша: {len(alive)} живых")
    print(f"🔄 Нужно проверить: {len(to_check)}")
    print(f"⏱️  Таймаут: {CHECK_TIMEOUT}с\n")
    
    if not to_check:
        return alive
    
    # Проверяем
    results = []
    total = len(to_check)
    
    for i, (raw, stype) in enumerate(to_check, 1):
        parsed = parse_vless_config(raw)
        if not parsed:
            continue
        
        # Прогресс
        progress = int(i / total * 40)
        bar = "█" * progress + "░" * (40 - progress)
        host_short = parsed['host'][:25]
        print(f"\r[{bar}] {i:3d}/{total} {host_short:<25} ...", end="", flush=True)
        
        rtt = check_config(parsed)
        
        if rtt:
            results.append((raw, stype, rtt))
            speed = "⚡" if rtt < RTT_FAST else "🐢"
            print(f"\r[{bar}] {i:3d}/{total} {host_short:<25} ✅ {rtt:.0f}ms {speed}")
        else:
            print(f"\r[{bar}] {i:3d}/{total} {host_short:<25} ❌")
        
        cache[raw] = {"rtt": rtt, "ts": time.time(), "stype": stype}
    
    print()
    save_cache(cache)
    
    all_alive = alive + results
    all_alive.sort(key=lambda x: x[2])
    
    return all_alive

# ─────────────────────────────────────────────────────────────
# ГЕНЕРАЦИЯ SING-BOX JSON ДЛЯ HAPP
# ─────────────────────────────────────────────────────────────
def generate_singbox_json(alive: list) -> dict:
    """Генерирует JSON конфиг для sing-box/Happ с автовыбором"""
    
    # Счётчики для нумерации серверов по странам и типам
    whitelist_counters = defaultdict(int)
    blacklist_counters = defaultdict(int)
    
    whitelist_outbounds = []
    blacklist_outbounds = []
    all_outbounds = []
    
    for raw, stype, rtt in alive:
        parsed = parse_vless_config(raw)
        if not parsed:
            continue
        
        # Определяем страну
        flag, country = get_country_info(parsed["host"], parsed["sni"])
        
        # Создаём тег (название сервера в Happ)
        if stype == "whitelist":
            whitelist_counters[country] += 1
            num = whitelist_counters[country]
            tag = f"{PROVIDER_NAME} | {country} {num} | WiFi"
        else:
            blacklist_counters[country] += 1
            num = blacklist_counters[country]
            tag = f"{PROVIDER_NAME} | {country} {num} | Обход"
        
        # Создаём outbound для sing-box
        outbound = {
            "type": "vless",
            "tag": tag,
            "server": parsed["host"],
            "server_port": parsed["port"],
            "uuid": parsed["uuid"],
            "flow": parsed["flow"],
            "tls": {
                "enabled": True,
                "server_name": parsed["sni"],
                "utls": {
                    "enabled": True,
                    "fingerprint": parsed["fp"]
                }
            }
        }
        
        # Добавляем reality если есть public key
        if parsed["pbk"]:
            outbound["tls"]["reality"] = {
                "enabled": True,
                "public_key": parsed["pbk"],
                "short_id": parsed["sid"] if parsed["sid"] else ""
            }
        
        all_outbounds.append(outbound)
        
        if stype == "whitelist":
            whitelist_outbounds.append(tag)
        else:
            blacklist_outbounds.append(tag)
    
    # Создаём urltest группы
    urltest_wifi = {
        "type": "urltest",
        "tag": "⚡ WiFi — автовыбор",
        "outbounds": whitelist_outbounds if whitelist_outbounds else ["direct"],
        "url": CHECK_URL,
        "interval": "180s",
        "tolerance": 50
    }
    
    urltest_bypass = {
        "type": "urltest",
        "tag": "⚡ Обход — автовыбор",
        "outbounds": blacklist_outbounds if blacklist_outbounds else ["direct"],
        "url": CHECK_URL,
        "interval": "180s",
        "tolerance": 50
    }
    
    # Полный конфиг
    config = {
        "log": {
            "level": "warn",
            "timestamp": True
        },
        "dns": {
            "servers": [
                {
                    "tag": "dns-remote",
                    "address": "tls://1.1.1.1",
                    "detour": "⚡ WiFi — автовыбор"
                },
                {
                    "tag": "dns-local",
                    "address": "local",
                    "detour": "direct"
                }
            ],
            "rules": [
                {"outbound": "any", "server": "dns-local"}
            ],
            "final": "dns-remote"
        },
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"],
                "auto_route": True,
                "strict_route": True,
                "sniff": True
            },
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "listen_port": 2080,
                "sniff": True
            },
            {
                "type": "http",
                "tag": "http-in",
                "listen": "127.0.0.1",
                "listen_port": 2081,
                "sniff": True
            }
        ],
        "outbounds": [
            urltest_wifi,
            urltest_bypass,
            *all_outbounds,
            {
                "type": "direct",
                "tag": "direct"
            },
            {
                "type": "block",
                "tag": "block"
            },
            {
                "type": "dns",
                "tag": "dns-out"
            }
        ],
        "route": {
            "rules": [
                {"protocol": "dns", "outbound": "dns-out"},
                {"ip_is_private": True, "outbound": "direct"}
            ],
            "final": "⚡ WiFi — автовыбор",
            "auto_detect_interface": True
        }
    }
    
    return config

# ─────────────────────────────────────────────────────────────
# ФОРМАТИРОВАНИЕ SERVERS.TXT
# ─────────────────────────────────────────────────────────────
def format_servers_txt(alive: list) -> str:
    """Форматирует список URL конфигов"""
    lines = []
    for raw, stype, rtt in alive:
        parsed = parse_vless_config(raw)
        if parsed:
            flag, country = get_country_info(parsed["host"], parsed["sni"])
            speed = "⚡" if rtt < RTT_FAST else "🐢"
            tag = "обход ЧС" if stype == "blacklist" else "обход БС"
            lines.append(f"{raw}#{flag} {speed} {tag}")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────
# ЗАГРУЗКА НА GITHUB
# ─────────────────────────────────────────────────────────────
def upload_to_github(filename: str, content: str, is_json: bool = False) -> bool:
    """Загружает файл на GitHub"""
    print(f"\n📤 Загрузка {filename}...")
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "VPN-Checker"
    }
    
    # Получаем SHA если файл существует
    sha = None
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"   ⚠️ Ошибка: {e.code}")
            return False
    
    # Подготавливаем данные
    content_b64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    data = {
        "message": f"Update {filename} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "content": content_b64,
        "branch": GITHUB_BRANCH
    }
    if sha:
        data["sha"] = sha
    
    # Отправляем
    json_data = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=json_data, headers=headers, method="PUT")
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"   ✅ {filename} загружен")
            return True
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def print_stats(alive: list):
    """Выводит статистику"""
    if not alive:
        return
    
    groups = defaultdict(list)
    for raw, stype, rtt in alive:
        parsed = parse_vless_config(raw)
        if parsed:
            flag, country = get_country_info(parsed["host"], parsed["sni"])
            groups[country].append(rtt)
    
    print(f"\n{'─'*65}")
    print(f"{'Страна':<15} {'Кол-во':>6} {'Мин':>7} {'Средн':>7} {'Макс':>7} {'⚡/🐢'}")
    print(f"{'─'*65}")
    
    for country in sorted(groups.keys(), key=lambda x: sum(groups[x])/len(groups[x])):
        rtts = groups[country]
        fast = sum(1 for r in rtts if r < RTT_FAST)
        slow = len(rtts) - fast
        flag, _ = get_country_info(country, "")
        print(f"{flag} {country:<12} {len(rtts):>6} {min(rtts):>7.0f} {sum(rtts)/len(rtts):>7.0f} {max(rtts):>7.0f}  ⚡{fast}/🐢{slow}")
    
    all_rtts = [r for _, _, r in alive]
    fast_total = sum(1 for r in all_rtts if r < RTT_FAST)
    print(f"{'─'*65}")
    print(f"{'ИТОГО':<21} {len(all_rtts):>6} {min(all_rtts):>7.0f} {sum(all_rtts)/len(all_rtts):>7.0f} {max(all_rtts):>7.0f}  ⚡{fast_total}/🐢{len(all_rtts)-fast_total}")
    print(f"{'─'*65}")

# ─────────────────────────────────────────────────────────────
# ОСНОВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("🚀 SHARKIVPN - VPN конфиг-чекер для Happ")
    print(f"📁 GitHub: {GITHUB_REPO}")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)
    
    # Загружаем конфиги
    print("\n📥 Загрузка VLESS конфигов:")
    configs = fetch_configs(DEFAULT_SOURCES)
    
    if not configs:
        print("❌ Не удалось загрузить конфиги")
        return
    
    # Проверяем
    alive = check_all_configs(configs, use_cache=True)
    
    if not alive:
        print("❌ Не найдено рабочих конфигов")
        return
    
    # Статистика
    print_stats(alive)
    
    # Генерируем файлы
    servers_content = format_servers_txt(alive)
    singbox_json = generate_singbox_json(alive)
    json_content = json.dumps(singbox_json, ensure_ascii=False, indent=2)
    
    # Сохраняем локально
    with open(GITHUB_SERVERS_FILE, "w", encoding="utf-8") as f:
        f.write(servers_content)
    
    with open(GITHUB_JSON_FILE, "w", encoding="utf-8") as f:
        f.write(json_content)
    
    print(f"\n💾 Локально сохранено:")
    print(f"   • {GITHUB_SERVERS_FILE} ({len(alive)} конфигов)")
    print(f"   • {GITHUB_JSON_FILE} (JSON для Happ)")
    
    # Загружаем на GitHub
    upload_to_github(GITHUB_SERVERS_FILE, servers_content)
    upload_to_github(GITHUB_JSON_FILE, json_content)
    
    # Итог
    fast = sum(1 for _, _, r in alive if r < RTT_FAST)
    print(f"\n✅ Готово! Найдено {len(alive)} рабочих конфигов (⚡{fast} быстрых / 🐢{len(alive)-fast} медленных)")
    print(f"\n🔗 Ссылки:")
    print(f"   • https://github.com/{GITHUB_REPO}/blob/{GITHUB_BRANCH}/{GITHUB_SERVERS_FILE}")
    print(f"   • https://github.com/{GITHUB_REPO}/blob/{GITHUB_BRANCH}/{GITHUB_JSON_FILE}")

if __name__ == "__main__":
    main()
