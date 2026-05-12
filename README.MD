Markdown

# Wi-Fi Probe Request Analyzer

Программный комплекс для анализа Probe Request пакетов Wi-Fi 
с последующей геолокацией через API WiGLE и визуализацией на карте.

## Функционал

- Перевод интерфейса в режим мониторинга
- Захват Probe Request через airodump-ng
- Извлечение уникальных SSID
- Запрос координат через WiGLE API
- Построение интерактивной карты (Folium)

## Требования

- Python 3.9+
- aircrack-ng
- requests
- folium

## Установка зависимостей

```bash
pip install -r requirements.txt
Запуск
Bash

python main.py
Структура проекта
main.py — основной код
sample_data/ — примеры входных и выходных данных
Автор
ФИО, 2026
ВКР