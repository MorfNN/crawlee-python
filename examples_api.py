#!/usr/bin/env python3
"""
Примеры использования Gemini Automation API
Запустите gemini_automation.py перед использованием этих примеров
"""

import asyncio
import json
import sys
from pathlib import Path

import aiohttp


BASE_URL = "http://localhost:8000"


async def list_all_tasks():
    """Пример 1: Получить все задачи"""
    print("\n📋 Пример 1: Получить все задачи")
    print("-" * 50)
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/api/tasks") as resp:
            data = await resp.json()
            print(json.dumps(data, indent=2, ensure_ascii=False))


async def create_simple_task():
    """Пример 2: Создать простую задачу"""
    print("\n📝 Пример 2: Создать задачу")
    print("-" * 50)
    
    task_data = {
        "prompt": "Сколько стоит акция NVIDIA?",
        "sessions": 5
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/api/tasks",
            json=task_data
        ) as resp:
            result = await resp.json()
            print(f"Задача создана:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return result.get('id')


async def start_task(task_id: str):
    """Пример 3: Запустить задачу"""
    print(f"\n▶️  Пример 3: Запустить задачу {task_id}")
    print("-" * 50)
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/api/tasks/{task_id}/start"
        ) as resp:
            result = await resp.json()
            print(f"Статус: {result}")


async def monitor_task(task_id: str, duration: int = 30):
    """Пример 4: Мониторить задачу в реальном времени"""
    print(f"\n🔍 Пример 4: Мониторить задачу {task_id} ({duration}с)")
    print("-" * 50)
    
    async with aiohttp.ClientSession() as session:
        for i in range(duration):
            async with session.get(
                f"{BASE_URL}/api/tasks/{task_id}"
            ) as resp:
                task = await resp.json()
                
                status_emoji = {
                    'pending': '⏳',
                    'running': '▶️',
                    'stopped': '⏹',
                    'completed': '✅'
                }.get(task['status'], '?')
                
                print(
                    f"{i+1}/{duration} | {status_emoji} {task['status']:10} | "
                    f"Активных: {task['active_sessions']:2} | "
                    f"Завершено: {task['completed_sessions']:3}/{task['session_count']}"
                )
            
            if task['status'] in ['completed', 'stopped']:
                break
            
            await asyncio.sleep(1)


async def stop_task(task_id: str):
    """Пример 5: Остановить задачу"""
    print(f"\n⏹ Пример 5: Остановить задачу {task_id}")
    print("-" * 50)
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/api/tasks/{task_id}/stop"
        ) as resp:
            result = await resp.json()
            print(f"Статус: {result}")


async def create_and_run_multiple_tasks():
    """Пример 6: Создать и запустить несколько задач параллельно"""
    print("\n🚀 Пример 6: Несколько задач параллельно")
    print("-" * 50)
    
    tasks_data = [
        {
            "prompt": "Найди последние новости о Claude AI",
            "sessions": 3
        },
        {
            "prompt": "Расскажи о Python асинхронном программировании",
            "sessions": 2
        },
        {
            "prompt": "Какие тренды в веб-разработке в 2026?",
            "sessions": 4
        }
    ]
    
    task_ids = []
    
    async with aiohttp.ClientSession() as session:
        # Создаем задачи
        for i, task_data in enumerate(tasks_data):
            async with session.post(
                f"{BASE_URL}/api/tasks",
                json=task_data
            ) as resp:
                result = await resp.json()
                task_ids.append(result['id'])
                print(f"✅ Задача {i+1} создана: {result['id']}")
        
        print("\nЗапуск всех задач...")
        
        # Запускаем все задачи
        for task_id in task_ids:
            async with session.post(
                f"{BASE_URL}/api/tasks/{task_id}/start"
            ) as resp:
                print(f"▶️  Задача {task_id} запущена")
        
        print("\nМониторим выполнение...")
        
        # Мониторим задачи
        while True:
            all_completed = True
            
            for task_id in task_ids:
                async with session.get(
                    f"{BASE_URL}/api/tasks/{task_id}"
                ) as resp:
                    task = await resp.json()
                    
                    progress = (
                        (task['completed_sessions'] / task['session_count'] * 100)
                        if task['session_count'] > 0 else 0
                    )
                    
                    print(
                        f"{task_id[:10]:10} | "
                        f"{task['status']:10} | "
                        f"Прогресс: {progress:5.1f}% | "
                        f"{task['completed_sessions']}/{task['session_count']}"
                    )
                    
                    if task['status'] not in ['completed', 'stopped']:
                        all_completed = False
            
            if all_completed:
                print("\n✅ Все задачи завершены!")
                break
            
            print("-" * 60)
            await asyncio.sleep(5)


async def health_check():
    """Пример 7: Проверить здоровье приложения"""
    print("\n🏥 Пример 7: Проверка здоровья приложения")
    print("-" * 50)
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/health") as resp:
            health = await resp.json()
            print(json.dumps(health, indent=2, ensure_ascii=False))


async def demo_workflow():
    """Демонстрационный workflow"""
    print("\n" + "=" * 60)
    print("🤖 ДЕМОНСТРАЦИЯ GEMINI AUTOMATION")
    print("=" * 60)
    
    try:
        # Проверяем здоровье
        await health_check()
        
        # Пример 1: Список задач
        await list_all_tasks()
        
        # Пример 2: Создаем задачу
        task_id = await create_simple_task()
        
        if task_id:
            # Пример 3: Запускаем задачу
            await start_task(task_id)
            
            # Пример 4: Мониторим
            await monitor_task(task_id, duration=20)
        
        print("\n" + "=" * 60)
        print("✅ Демонстрация завершена")
        print("=" * 60)
        
    except aiohttp.ClientConnectorError:
        print("\n❌ Ошибка: Не могу подключиться к серверу")
        print(f"Убедитесь, что приложение запущено на {BASE_URL}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)


async def main():
    """Главная функция"""
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "list":
            await list_all_tasks()
        elif command == "create":
            prompt = input("Введите текст задачи: ")
            sessions = int(input("Количество сессий: ") or "5")
            task_id = await create_simple_task()
        elif command == "demo":
            await demo_workflow()
        else:
            print(f"Неизвестная команда: {command}")
    else:
        # По умолчанию запускаем демо
        await demo_workflow()


if __name__ == "__main__":
    print("Примеры использования Gemini Automation API")
    print(f"Сервер: {BASE_URL}")
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⏹ Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)
