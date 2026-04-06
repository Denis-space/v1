#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHARKIVPN - ОПТИМИЗИРОВАННАЯ версия
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Белые списки - проверяем ВСЕ
• Чёрные списки - проверяем ДО 20 РАБОЧИХ (не все!)
• Как только нашли 20 - остальные НЕ ПРОВЕРЯЕМ
"""

import re, sys, os, json, time, base64, socket, ssl, urllib.request
from datetime import datetime
from collections import defaultdict
from typing import Optional
import urllib.error

# ─────────────────────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")
GITHUB_REPO = "Denis-space/v1"
GITHUB_BRANCH = "main"
GITHUB_SERVERS_FILE = "servers.txt"
GITHUB_JSON_FILE = "singbox_config.json"

CHECK_TIMEOUT = 10
CHECK_URL = "https://www.google.com/generate_204"
RTT_MAX = 2000
RTT_FAST = 1000

MAX_WORKING_BLACKLIST = 20   # Нужно всего 20 РАБОЧИХ с каждого чёрного источника

SUPPORTED = ("vless://",)

# Источники
_BASE_IGARECK = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main"
_BASE_GOIDA = "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror"

SOURCES = {
    # Белые списки - проверяем ВСЕ
    "igareck-mobile-1":   (f"{_BASE_IGARECK}/Vless-Reality-White-Lists-Rus-Mobile.txt", "whitelist"),
    "igareck-mobile-2":   (f"{_BASE_IGARECK}/Vless-Reality-White-Lists-Rus-Mobile-2.txt", "whitelist"),
    
    # Чёрные списки - ищем ДО 20 РАБОЧИХ
    "goida-1":   (f"{_BASE_GOIDA}/1.txt", "blacklist"),
    "goida-6":   (f"{_BASE_GOIDA}/6.txt", "blacklist"),
    "goida-22":  (f"{_BASE_GOIDA}/22.txt", "blacklist"),
    "goida-23":  (f"{_BASE_GOIDA}/23.txt", "blacklist"),
    "goida-24":  (f"{_BASE_GOIDA}/24.txt", "blacklist"),
    "goida-25":  (f"{_BASE_GOIDA}/25.txt", "blacklist"),
}

DEFAULT_SOURCES = list(SOURCES.keys())

CACHE_FILE = "vpn_cache.json"
CACHE_TTL = 3600
PROVIDER_NAME = "SHARKIVPN"

# ─────────────────────────────────────────────────────────────
# СТРАНЫ
# ─────────────────────────────────────────────────────────────
COUNTRIES = {
    "ru": "🇷🇺", "de": "🇩🇪", "nl": "🇳🇱", "us": "🇺🇸", "pl": "🇵🇱",
    "fi": "🇫🇮", "fr": "🇫🇷", "uk": "🇬🇧", "jp": "🇯🇵", "sg": "🇸🇬",
}

def get_country_flag(host: str, sni: str) -> str:
    text = ((host or "") + " " + (sni or "")).lower()
    for code, flag in COUNTRIES.items():
        if f".{code}" in text or f"-{code}" in text:
            return flag
    return "🌍"

def get_country_name(host: str, sni: str) -> str:
    text = ((host or "") + " " + (sni or "")).lower()
    for code, flag in COUNTRIES.items():
        if f".{code}" in text or f"-{code}" in text:
            return code.capitalize()
    return "Unknown"

# ─────────────────────────────────────────────────────────────
# ПАРСИНГ
# ─────────────────────────────────────────────────────────────
def parse_vless_config(line: str) -> Optional[dict]:
    raw = line.strip().split("#", 1)[0].strip()
    if not raw.startswith("vless://"):
        return None
    
    try:
        match = re.match(r"vless://([^@]+)@([^:/?#\s]+):(\d+)\??([^#\s]*)$", raw)
        if not match:
            return None
        
        uuid, host, port, params = match.groups()
        port = int(port)
        
        params_dict = {}
        if params:
            for p in params.split("&"):
                if "=" in p:
                    k, v = p.split("=", 1)
                    params_dict[k] = v
        
        return {
            "raw": raw,
            "uuid": uuid,
            "host": host,
            "port": port,
            "sni": params_dict.get("sni", host),
            "flow": params_dict.get("flow", ""),
            "pbk": params_dict.get("pbk", ""),
            "sid": params_dict.get("sid", ""),
            "fp": params_dict.get("fp", "chrome"),
        }
    except:
        return None

# ─────────────────────────────────────────────────────────────
# ПРОВЕРКА ОДНОГО КОНФИГА
# ─────────────────────────────────────────────────────────────
def check_config(config: dict) -> Optional[float]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CHECK_TIMEOUT)
        
        start_time = time.time()
        sock.connect((config["host"], config["port"]))
        
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        with context.wrap_socket(sock, server_hostname=config["sni"]) as ssock:
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
    except:
        pass
    return None

# ─────────────────────────────────────────────────────────────
# ЗАГРУЗКА КОНФИГОВ ИЗ ИСТОЧНИКА
# ─────────────────────────────────────────────────────────────
def fetch_configs_from_source(url: str) -> list:
    """Загружает все конфиги из источника"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            text = response.read().decode("utf-8", errors="ignore")
            lines = [l.strip() for l in text.splitlines() 
                    if l.strip().startswith("vless://")]
            return lines
    except:
        return []

# ─────────────────────────────────────────────────────────────
# ОПТИМИЗИРОВАННАЯ ПРОВЕРКА ЧЁРНОГО ИСТОЧНИКА
# ─────────────────────────────────────────────────────────────
def check_blacklist_source(name: str, url: str, cache: dict) -> list:
    """
    Проверяет чёрный источник, но останавливается когда нашёл 20 РАБОЧИХ
    Не проверяет все конфиги подряд!
    """
    print(f"\n  🔍 {name} (ищем {MAX_WORKING_BLACKLIST} рабочих)")
    
    # Загружаем конфиги
    all_configs = fetch_configs_from_source(url)
    print(f"     Загружено {len(all_configs)} конфигов")
    
    if not all_configs:
        return []
    
    working = []
    checked = 0
    
    # Проверяем по одному, пока не найдём 20
    for raw in all_configs:
        # Если уже нашли 20 - останавливаемся!
        if len(working) >= MAX_WORKING_BLACKLIST:
            print(f"     ✓ Найдено {len(working)} рабочих, остальные {len(all_configs) - checked} НЕ ПРОВЕРЯЛИ")
            break
        
        parsed = parse_vless_config(raw)
        if not parsed:
            checked += 1
            continue
        
        checked += 1
        
        # Проверяем кэш
        if raw in cache:
            rtt = cache[raw].get("rtt")
            if rtt and rtt < RTT_MAX:
                working.append((raw, "blacklist", rtt))
                print(f"     [{len(working)}/{MAX_WORKING_BLACKLIST}] {parsed['host']} ✅ {rtt:.0f}ms (кэш)")
                continue
        
        # Живая проверка
        rtt = check_config(parsed)
        if rtt:
            working.append((raw, "blacklist", rtt))
            speed = "⚡" if rtt < RTT_FAST else "🐢"
            print(f"     [{len(working)}/{MAX_WORKING_BLACKLIST}] {parsed['host']} ✅ {rtt:.0f}ms {speed}")
        else:
            print(f"     [{len(working)}/{MAX_WORKING_BLACKLIST}] {parsed['host']} ❌")
        
        # Сохраняем в кэш
        cache[raw] = {"rtt": rtt, "ts": time.time(), "stype": "blacklist"}
    
    # Сортируем по RTT
    working.sort(key=lambda x: x[2])
    
    print(f"     → ИТОГО: {len(working)} рабочих из {checked} проверенных (остановились на {MAX_WORKING_BLACKLIST})")
    return working

# ─────────────────────────────────────────────────────────────
# ПРОВЕРКА БЕЛОГО ИСТОЧНИКА (ВСЕ КОНФИГИ)
# ─────────────────────────────────────────────────────────────
def check_whitelist_source(name: str, url: str, cache: dict) -> list:
    """Проверяет ВСЕ конфиги из белого источника"""
    print(f"\n  🔍 {name} (проверяем ВСЕ)")
    
    all_configs = fetch_configs_from_source(url)
    print(f"     Загружено {len(all_configs)} конфигов")
    
    if not all_configs:
        return []
    
    working = []
    total = len(all_configs)
    
    for i, raw in enumerate(all_configs, 1):
        parsed = parse_vless_config(raw)
        if not parsed:
            continue
        
        progress = int(i / total * 30)
        bar = "█" * progress + "░" * (30 - progress)
        print(f"\r     [{bar}] {i:3d}/{total} {parsed['host'][:20]}...", end="", flush=True)
        
        if raw in cache:
            rtt = cache[raw].get("rtt")
            if rtt and rtt < RTT_MAX:
                working.append((raw, "whitelist", rtt))
                print(f"\r     [{bar}] {i:3d}/{total} {parsed['host'][:20]} ✅ {rtt:.0f}ms (кэш)")
                cache[raw] = {"rtt": rtt, "ts": time.time(), "stype": "whitelist"}
                continue
        
        rtt = check_config(parsed)
        if rtt:
            working.append((raw, "whitelist", rtt))
            speed = "⚡" if rtt < RTT_FAST else "🐢"
            print(f"\r     [{bar}] {i:3d}/{total} {parsed['host'][:20]} ✅ {rtt:.0f}ms {speed}")
        else:
            print(f"\r     [{bar}] {i:3d}/{total} {parsed['host'][:20]} ❌")
        
        cache[raw] = {"rtt": rtt, "ts": time.time(), "stype": "whitelist"}
    
    print()
    working.sort(key=lambda x: x[2])
    print(f"     → ИТОГО: {len(working)} рабочих из {total}")
    return working

# ─────────────────────────────────────────────────────────────
# ГЕНЕРАЦИЯ JSON
# ─────────────────────────────────────────────────────────────
def generate_singbox_json(alive: list) -> dict:
    whitelist_outbounds = []
    blacklist_outbounds = []
    all_outbounds = []
    
    whitelist_counter = defaultdict(int)
    blacklist_counter = defaultdict(int)
    
    for raw, stype, rtt in alive:
        parsed = parse_vless_config(raw)
        if not parsed:
            continue
        
        flag = get_country_flag(parsed["host"], parsed["sni"])
        country = get_country_name(parsed["host"], parsed["sni"])
        
        if stype == "whitelist":
            whitelist_counter[country] += 1
            tag = f"{PROVIDER_NAME} | {country} {whitelist_counter[country]} | WiFi"
            whitelist_outbounds.append(tag)
        else:
            blacklist_counter[country] += 1
            tag = f"{PROVIDER_NAME} | {country} {blacklist_counter[country]} | Обход"
            blacklist_outbounds.append(tag)
        
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
                "utls": {"enabled": True, "fingerprint": parsed["fp"]}
            }
        }
        
        if parsed["pbk"]:
            outbound["tls"]["reality"] = {
                "enabled": True,
                "public_key": parsed["pbk"],
                "short_id": parsed["sid"]
            }
        
        all_outbounds.append(outbound)
    
    return {
        "log": {"level": "warn"},
        "inbounds": [
            {"type": "tun", "tag": "tun-in", "address": ["172.19.0.1/30"], "auto_route": True},
            {"type": "socks", "tag": "socks-in", "listen": "127.0.0.1", "listen_port": 2080}
        ],
        "outbounds": [
            {"type": "urltest", "tag": "⚡ WiFi — автовыбор", "outbounds": whitelist_outbounds, "url": CHECK_URL, "interval": "180s"},
            {"type": "urltest", "tag": "⚡ Обход — автовыбор", "outbounds": blacklist_outbounds, "url": CHECK_URL, "interval": "180s"},
            *all_outbounds,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"}
        ],
        "route": {"final": "⚡ WiFi — автовыбор", "auto_detect_interface": True}
    }

# ─────────────────────────────────────────────────────────────
# ЗАГРУЗКА НА GITHUB
# ─────────────────────────────────────────────────────────────
def upload_to_github(filename: str, content: str) -> bool:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    sha = None
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            sha = json.loads(resp.read()).get("sha")
    except:
        pass
    
    data = {
        "message": f"Update {filename} - {datetime.now()}",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": GITHUB_BRANCH
    }
    if sha:
        data["sha"] = sha
    
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"   ✅ {filename} загружен")
            return True
    except Exception as e:
        print(f"   ❌ {filename}: {e}")
        return False

# ─────────────────────────────────────────────────────────────
# ОСНОВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("🚀 SHARKIVPN - ОПТИМИЗИРОВАННАЯ проверка")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)
    
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
        except:
            pass
    
    all_alive = []
    
    # Проверяем все источники
    for name, (url, stype) in SOURCES.items():
        if stype == "whitelist":
            # Белые - проверяем ВСЕ конфиги
            working = check_whitelist_source(name, url, cache)
            all_alive.extend(working)
        else:
            # Чёрные - ищем ТОЛЬКО 20 рабочих
            working = check_blacklist_source(name, url, cache)
            all_alive.extend(working)
    
    # Сохраняем кэш
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)
    
    if not all_alive:
        print("\n❌ Не найдено рабочих конфигов")
        return
    
    # Сортируем по RTT
    all_alive.sort(key=lambda x: x[2])
    
    # Считаем статистику
    whitelist_count = sum(1 for _, stype, _ in all_alive if stype == "whitelist")
    blacklist_count = sum(1 for _, stype, _ in all_alive if stype == "blacklist")
    fast = sum(1 for _, _, r in all_alive if r < RTT_FAST)
    
    print(f"\n{'─'*50}")
    print(f"📊 ИТОГОВАЯ СТАТИСТИКА:")
    print(f"   • Всего конфигов: {len(all_alive)}")
    print(f"   • Белые списки: {whitelist_count} (проверены ВСЕ)")
    print(f"   • Чёрные списки: {blacklist_count} (по {MAX_WORKING_BLACKLIST} с каждого)")
    print(f"   • Быстрые (⚡): {fast}")
    print(f"   • Медленные (🐢): {len(all_alive)-fast}")
    print(f"{'─'*50}")
    
    # Генерируем файлы
    servers_txt = "\n".join([f"{raw}#{get_country_flag(parse_vless_config(raw)['host'], parse_vless_config(raw)['sni'])} {'⚡' if rtt<RTT_FAST else '🐢'}" for raw, _, rtt in all_alive])
    singbox_json = json.dumps(generate_singbox_json(all_alive), indent=2)
    
    # Сохраняем локально
    with open(GITHUB_SERVERS_FILE, "w") as f:
        f.write(servers_txt)
    with open(GITHUB_JSON_FILE, "w") as f:
        f.write(singbox_json)
    
    # Загружаем на GitHub
    print(f"\n📤 Загрузка на GitHub...")
    upload_to_github(GITHUB_SERVERS_FILE, servers_txt)
    upload_to_github(GITHUB_JSON_FILE, singbox_json)
    
    print(f"\n✅ Готово! https://github.com/{GITHUB_REPO}")

if __name__ == "__main__":
    main()
