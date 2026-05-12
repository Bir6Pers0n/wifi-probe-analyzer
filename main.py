import subprocess
import csv
import os
import signal
import sys
import time
import json
import re
import requests
from datetime import datetime
from typing import Set
from requests.auth import HTTPBasicAuth

# ----------------------------------------------------------------------
# Конфигурационные параметры
# ----------------------------------------------------------------------
CSV_FILE = "/tmp/wifidump-01.csv"           # Файл, создаваемый airodump-ng
OUTPUT_ESSID_FILE = "probed_essids.txt"     # Список найденных SSID
WIGLE_RAW_FILE = "wigle_raw.jsonl"          # Сырые данные от WiGLE
WIGLE_MAP_FILE = "wigle_map.html"           # Итоговая карта


def run_command(command: list) -> subprocess.CompletedProcess:
    """Выполнение команды с проверкой кода возврата."""
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"Ошибка выполнения команды: {' '.join(command)}")
        print(result.stderr.strip())
        sys.exit(1)
    return result


def enable_monitor_mode(interface: str) -> None:
    """Перевод сетевого интерфейса в режим мониторинга."""
    print(f"Перевод интерфейса {interface} в режим мониторинга...")
    run_command(["sudo", "ip", "link", "set", interface, "down"])
    run_command(["sudo", "iw", "dev", interface, "set", "type", "monitor"])
    run_command(["sudo", "ip", "link", "set", interface, "up"])
    print("Интерфейс переведен в режим мониторинга.\n")


def disable_monitor_mode(interface: str) -> None:
    """Возврат интерфейса в управляемый режим."""
    print("Возврат интерфейса в обычный режим...")
    run_command(["sudo", "ip", "link", "set", interface, "down"])
    run_command(["sudo", "iw", "dev", interface, "set", "type", "managed"])
    run_command(["sudo", "ip", "link", "set", interface, "up"])
    print("Интерфейс восстановлен.\n")


def is_valid_essid(essid: str) -> bool:
    """Фильтрация некорректных или служебных SSID."""
    if not essid or len(essid) <= 2:
        return False
    if essid.startswith(('<', '(', '[', '{', '.')):
        return False
    if re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', essid):  # MAC-адрес
        return False
    if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', essid):   # IP-адрес
        return False
    return True


def extract_probed_essid() -> Set[str]:
    """Извлечение уникальных SSID из CSV-файла airodump-ng."""
    essids = set()

    if not os.path.exists(CSV_FILE):
        print("CSV-файл не найден. Сначала выполните захват трафика.")
        return essids

    with open(CSV_FILE, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        station_section = False

        for row in reader:
            if not row:
                continue
            if any("Station MAC" in cell for cell in row):
                station_section = True
                continue
            if not station_section:
                continue

            for field in row[6:]:
                ssid = field.strip()
                if is_valid_essid(ssid):
                    essids.add(ssid)

    # Сохранение в текстовый файл
    with open(OUTPUT_ESSID_FILE, "w", encoding="utf-8") as f:
        f.write(f"# Сбор выполнен: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Найдено уникальных SSID: {len(essids)}\n\n")
        for ssid in sorted(essids):
            f.write(ssid + "\n")

    print(f"Извлечено {len(essids)} уникальных SSID. Список сохранен в {OUTPUT_ESSID_FILE}")
    return essids


def query_wigle_api(ssid: str, lat1="", lat2="", lon1="", lon2="",
                    api_name="", api_token="", max_results=0) -> None:
    """Запрос к WiGLE API с пагинацией."""
    url = "https://api.wigle.net/api/v2/network/search"
    params = {"ssid": ssid, "resultsPerPage": 100}
    
    if lat1 and lat2 and lon1 and lon2:
        params.update({"latrange1": lat1, "latrange2": lat2,
                       "longrange1": lon1, "longrange2": lon2})

    collected = 0
    print(f"Запрос к WiGLE для SSID: {ssid}")

    while True:
        if max_results and collected >= max_results:
            break

        try:
            response = requests.get(url, params=params,
                                    auth=HTTPBasicAuth(api_name, api_token),
                                    timeout=20)
            if response.status_code != 200:
                print(f"HTTP ошибка: {response.status_code}")
                break

            data = response.json()
            if not data.get("success"):
                print("Ошибка API WiGLE")
                break

            results = data.get("results", [])
            if not results:
                break

            # Ограничение по количеству
            if max_results:
                remaining = max_results - collected
                results = results[:remaining]

            # Сохранение в файл
            with open(WIGLE_RAW_FILE, "a", encoding="utf-8") as f:
                for r in results:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

            collected += len(results)
            print(f"   Получено {len(results)} точек (всего: {collected})")

            if not data.get("searchAfter"):
                break

            params["searchAfter"] = data["searchAfter"]
            time.sleep(2)

        except Exception as e:
            print(f"Ошибка запроса: {e}")
            break

    print(f"Готово: {ssid} → {collected} точек\n")


def generate_map() -> None:
    """Создание HTML-карты с маркерами."""
    if not os.path.exists(WIGLE_RAW_FILE):
        print("Файл с данными WiGLE не найден.")
        return

    points = []
    with open(WIGLE_RAW_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                if "trilat" in data and "trilong" in data:
                    points.append(data)
            except:
                continue

    if not points:
        print("Нет данных для построения карты.")
        return

    import folium
    m = folium.Map(location=[points[0]["trilat"], points[0]["trilong"]],
                   zoom_start=12, tiles="OpenStreetMap")

    for p in points:
        folium.Marker(
            location=[p["trilat"], p["trilong"]],
            popup=folium.Popup(f"<b>{p.get('ssid', 'Unknown')}</b><br>"
                               f"MAC: {p.get('netid', '—')}<br>"
                               f"Город: {p.get('city', '—')}", max_width=300),
            tooltip=p.get("ssid", "SSID"),
            icon=folium.Icon(color="red", icon="wifi", prefix="fa")
        ).add_to(m)

    m.save(WIGLE_MAP_FILE)
    print(f"Карта успешно создана: {WIGLE_MAP_FILE} ({len(points)} точек)")


def main():
    print("=" * 50)
    print("  Сбор и анализ Probe Request пакетов Wi-Fi")
    print("  + геолокация через WiGLE + карта Folium")
    print("=" * 50)

    if input("\nЗапустить программу? (y/n): ").strip().lower() not in {"y", ""}:
        return

    interface = input("Интерфейс [по умолчанию wlan0]: ").strip() or "wlan0"
    enable_monitor_mode(interface)

    try:
        while True:
            print("\nЗапуск airodump-ng. Нажмите Ctrl+C для остановки...")
            process = subprocess.Popen([
                "sudo", "airodump-ng", "-w", "/tmp/wifidump",
                "--output-format", "csv", interface
            ])

            try:
                process.wait()
            except KeyboardInterrupt:
                process.send_signal(signal.SIGINT)
                process.wait()
                print("Захват остановлен пользователем.")

            time.sleep(2)
            essids = extract_probed_essid()

            while True:
                print("\n" + "="*50)
                print("1. Получить координаты (WiGLE API)")
                print("2. Продолжить сбор трафика")
                print("3. Построить карту")
                print("4. Выход")
                choice = input("Выберите действие: ").strip()

                if choice == "1":
                    api_name = input("WiGLE API Name: ").strip()
                    api_token = input("WiGLE API Token: ").strip()
                    lat1 = input("lat1 (пусто = без ограничения): ").strip()
                    lat2 = input("lat2: ").strip()
                    lon1 = input("lon1: ").strip()
                    lon2 = input("lon2: ").strip()
                    limit = input("Макс. точек на SSID (0 = все): ").strip()
                    limit = int(limit) if limit.isdigit() else 0

                    for ssid in sorted(essids):
                        query_wigle_api(ssid, lat1, lat2, lon1, lon2,
                                        api_name, api_token, limit)

                elif choice == "2":
                    break
                elif choice == "3":
                    generate_map()
                elif choice == "4":
                    print("Завершение работы...")
                    disable_monitor_mode(interface)
                    sys.exit(0)
                else:
                    print("Неверный выбор!")

    except KeyboardInterrupt:
        print("\nПрограмма прервана пользователем.")
    finally:
        disable_monitor_mode(interface)


if __name__ == "__main__":
    try:
        import requests
        import folium
    except ImportError as e:
        print("Не установлены зависимости.")
        print("Выполните: pip3 install requests folium")
        sys.exit(1)

    main()