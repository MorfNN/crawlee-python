#!/bin/bash
# Скрипт для запуска Gemini Automation

echo "🤖 Gemini Automation - Старт"
echo "================================"
echo ""

# Проверяем требования
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден. Пожалуйста, установите Python 3.10+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | grep -oE '[0-9]+\.[0-9]+')
echo "✅ Python версия: $PYTHON_VERSION"

# Проверяем зависимости
echo ""
echo "📦 Проверяем зависимости..."

if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "📥 Установка зависимостей..."
    pip install -r requirements-automation.txt
fi

# Проверяем Playwright
if ! python3 -c "import playwright" 2>/dev/null; then
    echo "📥 Установка Playwright браузеров..."
    playwright install chromium
fi

echo "✅ Все зависимости установлены"
echo ""

# Запускаем приложение
echo "🚀 Запуск Gemini Automation..."
echo ""
echo "📡 URL: http://localhost:8000"
echo "🔗 WebSocket: ws://localhost:8000/ws"
echo ""
echo "Нажмите Ctrl+C для остановки"
echo ""

python3 gemini_automation.py
