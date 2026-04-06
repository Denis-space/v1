#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SHARKIVPN - ТОЛЬКО igareck (белые и чёрные списки)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Все источники из igareck (у него есть и белые и чёрные)
• Белые списки - все рабочие конфиги
• Чёрные списки - по 20 лучших с каждого источника
• Генерация JSON для Happ с автовыбором
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
GITHUB_SERVERS_FILE = "servers.txt"
GITHUB_JSON_FILE = "singbox_config.json"

# ─────────────────────────────────────────────────────────────
# НАСТРОЙКИ ПРОВЕРКИ
# ─────────────────────────────────────────────────────────────
CHECK_TIMEOUT = 10
CHECK_URL = "https://www.google.com/generate_204"
RTT_MAX = 2000      # Максимальный пинг
RTT_FAST = 1000     # <1000мс → ⚡

MAX_PER_BLACKLIST = 20   # По 20 лучших конфигов с КАЖДОГО чёрного источника

# Только VLESS конфиги
SUPPORTED = ("vless://",)

# ─── ТОЛЬКО IGARECK (у него всё есть) ───
_BASE_IGARECK = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main"

SOURCES = {
    # ── БЕЛЫЕ СПИСКИ (igareck) - берём ВСЕ рабочие ──
    "igareck-mobile-1":   (f"{_BASE_IGARECK}/Vless-Reality-White-Lists-Rus-Mobile.txt", "whitelist", "all"),
    "igareck-mobile-2":   (f"{_BASE_IGARECK}/Vless-Reality-White-Lists-Rus-Mobile-2.txt", "whitelist", "all"),
    "igareck-cidr-all":   (f"{_BASE_IGARECK}/WHITE-CIDR-RU-all.txt", "whitelist", "all"),
    "igareck-cidr-check": (f"{_BASE_IGARECK}/WHITE-CIDR-RU-checked.txt", "whitelist", "all"),
    "igareck-sni-all":    (f"{_BASE_IGARECK}/WHITE-SNI-RU-all.txt", "whitelist", "all"),
    
    # ── ЧЁРНЫЕ СПИСКИ (тоже из igareck) - берём по 20 ЛУЧШИХ с КАЖДОГО ──
    # Это обходные списки (черные) из того же репозитория
    "igareck-black-1":    (f"{_BASE_IGARECK}/Vless-Reality-Black-Lists-Rus-Mobile.txt", "blacklist", 20),
    "igareck-black-2":    (f"{_BASE_IGARECK}/Vless-Reality-Black-Lists-Rus-Mobile-2.txt", "blacklist", 20),
    "igareck-black-cidr": (f"{_BASE_IGARECK}/BLACK-CIDR-RU.txt", "blacklist", 20),
}

# Все источники
DEFAULT_SOURCES = list(SOURCES.keys())

# Кэш
CACHE_FILE = "vpn_cache.json"
CACHE_TTL = 3600

# Провайдер
PROVIDER_NAME = "SHARKIVPN"

# ─────────────────────────────────────────────────────────────
# СТРАНЫ
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
    "tr": {"flag": "🇹🇷", "name": "Турция"},
    "ch": {"flag": "🇨🇭", "name": "Швейцария"},
}

def get_country_info(host: str, sni: str) -> tuple:
    text = ((host or "") + " " + (sni or "")).lower()
    for code, info in COUNTRIES.items():
        if f".{code}" in text or f"-{code}" in text or text.startswith(f"{code}."):
            return info["flag"], info["name"]
    return "🌍", "Unknown"

# ─────────────────────────────────────────────────────────────
# ПАРСИНГ VLESS
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
            "params": params_dict
        }
    except:
        return None

# ─────────────────────────────────────────────────────────────
# ПРОВЕРКА КОНФИГА
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
    """Загружает все VLESS конфиги из источника"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            text = response.read().decode("utf-8", errors="ignore")
            lines = [l.strip() for l in text.splitlines() 
                    if l.strip().startswith("vless://")]
            return lines
    except Exception as e:
        print(f"     ✗ Ошибка загрузки: {e}")
        return []

# ─────────────────────────────────────────────────────────────
# ПРОВЕРКА БЕЛОГО ИСТОЧНИКА (ВСЕ КОНФИГИ)
# ─────────────────────────────────────────────────────────────
def check_whitelist_source(name: str, url: str, cache: dict) -> list:
    """Проверяет ВСЕ конфиги из белого источника"""
    print(f"\n  📍 {name} (БЕЛЫЙ список - проверяем ВСЕ)")
    
    all_configs = fetch_configs_from_source(url)
    print(f"     Загружено: {len(all_configs)} VLESS конфигов")
    
    if not all_configs:
        return []
    
    working = []
    total = len(all_configs)
    
    for i, raw in enumerate(all_configs, 1):
        parsed = parse_vless_config(raw)
        if not parsed:
            continue
        
        # Прогресс
        progress = int(i / total * 40)
        bar = "█" * progress + "░" * (40 - progress)
        host_short = parsed['host'][:25]
        print(f"\r     [{bar}] {i:3d}/{total} {host_short:<25} ...", end="", flush=True)
        
        # Проверяем кэш
        if raw in cache:
            rtt = cache[raw].get("rtt")
            if rtt and rtt < RTT_MAX:
                working.append((raw, "whitelist", rtt))
                print(f"\r     [{bar}] {i:3d}/{total} {host_short:<25} ✅ {rtt:.0f}ms (кэш)")
                continue
        
        # Живая проверка
        rtt = check_config(parsed)
        if rtt:
            working.append((raw, "whitelist", rtt))
            speed = "⚡" if rtt < RTT_FAST else "🐢"
            print(f"\r     [{bar}] {i:3d}/{total} {host_short:<25} ✅ {rtt:.0f}ms {speed}")
        else:
            print(f"\r     [{bar}] {i:3d}/{total} {host_short:<25} ❌")
        
        # Сохраняем в кэш
        cache[raw] = {"rtt": rtt, "ts": time.time(), "stype": "whitelist"}
    
    print()
    working.sort(key=lambda x: x[2])
    print(f"     → ИТОГО: {len(working)} рабочих из {total} проверенных")
    return working

# ─────────────────────────────────────────────────────────────
# ПРОВЕРКА ЧЁРНОГО ИСТОЧНИКА (ТОЛЬКО 20 ЛУЧШИХ)
# ─────────────────────────────────────────────────────────────
def check_blacklist_source(name: str, url: str, cache: dict) -> list:
    """Проверяет чёрный источник, находит 20 лучших (не проверяет все)"""
    print(f"\n  📍 {name} (ЧЁРНЫЙ список - ищем {MAX_PER_BLACKLIST} лучших)")
    
    all_configs = fetch_configs_from_source(url)
    print(f"     Загружено: {len(all_configs)} VLESS конфигов")
    
    if not all_configs:
        return []
    
    working = []
    checked = 0
    
    # Проверяем пока не найдём 20 рабочих
    for raw in all_configs:
        if len(working) >= MAX_PER_BLACKLIST:
            print(f"     ✓ Найдено {len(working)} рабочих, остальные {len(all_configs) - checked} НЕ ПРОВЕРЯЛИ")
            break
        
        parsed = parse_vless_config(raw)
        if not parsed:
            checked += 1
            continue
        
        checked += 1
        host_short = parsed['host'][:25]
        print(f"     [{len(working)+1:2d}/{MAX_PER_BLACKLIST}] {host_short:<25} ...", end=" ", flush=True)
        
        # Проверяем кэш
        if raw in cache:
            rtt = cache[raw].get("rtt")
            if rtt and rtt < RTT_MAX:
                working.append((raw, "blacklist", rtt))
                print(f"✅ {rtt:.0f}ms (кэш)")
                continue
        
        # Живая проверка
        rtt = check_config(parsed)
        if rtt:
            working.append((raw, "blacklist", rtt))
            speed = "⚡" if rtt < RTT_FAST else "🐢"
            print(f"✅ {rtt:.0f}ms {speed}")
        else:
            print(f"❌")
        
        # Сохраняем в кэш
        cache[raw] = {"rtt": rtt, "ts": time.time(), "stype": "blacklist"}
    
    working.sort(key=lambda x: x[2])
    print(f"     → ИТОГО: {len(working)} рабочих из {checked} проверенных")
    return working

# ─────────────────────────────────────────────────────────────
# ГЕНЕРАЦИЯ SING-BOX JSON
# ─────────────────────────────────────────────────────────────
def generate_singbox_json(alive: list) -> dict:
    whitelist_counters = defaultdict(int)
    blacklist_counters = defaultdict(int)
    
    whitelist_outbounds = []
    blacklist_outbounds = []
    all_outbounds = []
    
    for raw, stype, rtt in alive:
        parsed = parse_vless_config(raw)
        if not parsed:
            continue
        
        flag, country = get_country_info(parsed["host"], parsed["sni"])
        
        if stype == "whitelist":
            whitelist_counters[country] += 1
            num = whitelist_counters[country]
            tag = f"{PROVIDER_NAME} | {country} {num} | WiFi"
            whitelist_outbounds.append(tag)
        else:
            blacklist_counters[country] += 1
            num = blacklist_counters[country]
            tag = f"{PROVIDER_NAME} | {country} {num} | Обход"
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
                "utls": {
                    "enabled": True,
                    "fingerprint": parsed["fp"]
                }
            }
        }
        
        if parsed["pbk"]:
            outbound["tls"]["reality"] = {
                "enabled": True,
                "public_key": parsed["pbk"],
                "short_id": parsed["sid"] if parsed["sid"] else ""
            }
        
        all_outbounds.append(outbound)
    
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
    
    return {
        "log": {"level": "warn", "timestamp": True},
        "dns": {
            "servers": [
                {"tag": "dns-remote", "address": "tls://1.1.1.1", "detour": "⚡ WiFi — автовыбор"},
                {"tag": "dns-local", "address": "local", "detour": "direct"}
            ],
            "rules": [{"outbound": "any", "server": "dns-local"}],
            "final": "dns-remote"
        },
        "inbounds": [
            {"type": "tun", "tag": "tun-in", "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"], "auto_route": True, "strict_route": True, "sniff": True},
            {"type": "socks", "tag": "socks-in", "listen": "127.0.0.1", "listen_port": 2080, "sniff": True},
            {"type": "http", "tag": "http-in", "listen": "127.0.0.1", "listen_port": 2081, "sniff": True}
        ],
        "outbounds": [urltest_wifi, urltest_bypass, *all_outbounds,
                     {"type": "direct", "tag": "direct"},
                     {"type": "block", "tag": "block"},
                     {"type": "dns", "tag": "dns-out"}],
        "route": {
            "rules": [
                {"protocol": "dns", "outbound": "dns-out"},
                {"ip_is_private": True, "outbound": "direct"}
            ],
            "final": "⚡ WiFi — автовыбор",
            "auto_detect_interface": True
        }
    }

# ─────────────────────────────────────────────────────────────
# ФОРМАТИРОВАНИЕ SERVERS.TXT
# ─────────────────────────────────────────────────────────────
def format_servers_txt(alive: list) -> str:
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
def upload_to_github(filename: str, content: str) -> bool:
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

# ─────────────────────────────────────────────────────────────
# СТАТИСТИКА
# ─────────────────────────────────────────────────────────────
def print_stats(alive: list):
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
    whitelist_count = sum(1 for _, stype, _ in alive if stype == "whitelist")
    blacklist_count = sum(1 for _, stype, _ in alive if stype == "blacklist")
    
    print(f"{'─'*65}")
    print(f"{'ИТОГО (белые)':<21} {whitelist_count:>6}")
    print(f"{'ИТОГО (чёрные)':<21} {blacklist_count:>6}")
    print(f"{'ВСЕГО':<21} {len(all_rtts):>6} {min(all_rtts):>7.0f} {sum(all_rtts)/len(all_rtts):>7.0f} {max(all_rtts):>7.0f}  ⚡{fast_total}/🐢{len(all_rtts)-fast_total}")
    print(f"{'─'*65}")

# ─────────────────────────────────────────────────────────────
# ОСНОВНАЯ ФУНКЦИЯ
# ─────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("🚀 SHARKIVPN - ТОЛЬКО igareck (белые + чёрные списки)")
    print(f"📁 GitHub: {GITHUB_REPO}")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)
    
    # Загружаем кэш
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
                print(f"\n📦 Загружен кэш ({len(cache)} записей)")
        except:
            pass
    
    all_alive = []
    
    # Проверяем все источники
    for name, (url, stype, limit) in SOURCES.items():
        if stype == "whitelist":
            # Белые списки - проверяем ВСЕ конфиги
            working = check_whitelist_source(name, url, cache)
            all_alive.extend(working)
        else:
            # Чёрные списки - ищем ТОЛЬКО 20 лучших
            working = check_blacklist_source(name, url, cache)
            all_alive.extend(working)
    
    # Сохраняем кэш
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)
    print(f"\n💾 Кэш сохранён ({len(cache)} записей)")
    
    if not all_alive:
        print("\n❌ Не найдено рабочих конфигов")
        return
    
    # Сортируем по RTT
    all_alive.sort(key=lambda x: x[2])
    
    # Статистика
    print_stats(all_alive)
    
    # Генерируем файлы
    servers_content = format_servers_txt(all_alive)
    singbox_json = generate_singbox_json(all_alive)
    json_content = json.dumps(singbox_json, ensure_ascii=False, indent=2)
    
    # Сохраняем локально
    with open(GITHUB_SERVERS_FILE, "w", encoding="utf-8") as f:
        f.write(servers_content)
    
    with open(GITHUB_JSON_FILE, "w", encoding="utf-8") as f:
        f.write(json_content)
    
    print(f"\n💾 Локально сохранено:")
    print(f"   • {GITHUB_SERVERS_FILE} ({len(all_alive)} конфигов)")
    print(f"   • {GITHUB_JSON_FILE} (JSON для Happ)")
    
    # Загружаем на GitHub
    upload_to_github(GITHUB_SERVERS_FILE, servers_content)
    upload_to_github(GITHUB_JSON_FILE, json_content)
    
    # Итог
    fast = sum(1 for _, _, r in all_alive if r < RTT_FAST)
    whitelist_count = sum(1 for _, stype, _ in all_alive if stype == "whitelist")
    blacklist_count = sum(1 for _, stype, _ in all_alive if stype == "blacklist")
    
    print(f"\n✅ ГОТОВО!")
    print(f"   • Всего конфигов: {len(all_alive)}")
    print(f"   • Белые списки: {whitelist_count} (все рабочие)")
    print(f"   • Чёрные списки: {blacklist_count} (по {MAX_PER_BLACKLIST} с каждого)")
    print(f"   • Быстрые (⚡ <{RTT_FAST}ms): {fast}")
    print(f"   • Медленные (🐢 ≥{RTT_FAST}ms): {len(all_alive)-fast}")
    print(f"\n🔗 Ссылки:")
    print(f"   • https://github.com/{GITHUB_REPO}/blob/{GITHUB_BRANCH}/{GITHUB_SERVERS_FILE}")
    print(f"   • https://github.com/{GITHUB_REPO}/blob/{GITHUB_BRANCH}/{GITHUB_JSON_FILE}")

if __name__ == "__main__":
    main()
