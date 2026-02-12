"""
Gemini Browser Automation - управление сессиями с волнообразным запуском и анти-бан механизмами
"""
import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright, Browser, Page, BrowserContext


@dataclass
class Task:
    """Модель задачи"""
    id: str
    prompt: str
    session_count: int
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "pending"  # pending, running, stopped, completed
    active_sessions: int = 0
    completed_sessions: int = 0
    
    def to_dict(self):
        return asdict(self)


class GeminiAutomationManager:
    """Менеджер для управления сессиями Gemini"""
    
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.session_tasks: dict[str, asyncio.Task] = {}
        self.browser: Optional[Browser] = None
        self.running = False
        
    async def init_browser(self):
        """Инициализация браузера"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=False)
        
    async def close_browser(self):
        """Закрытие браузера"""
        if self.browser:
            await self.browser.close()
            
    async def create_session(
        self,
        task_id: str,
        task_prompt: str,
        session_id: str,
        delay_before_start: float = 0
    ):
        """Создает и управляет одной сессией"""
        key = f"{task_id}_{session_id}"
        
        try:
            # Ждем перед стартом для волнообразного распределения
            if delay_before_start > 0:
                await asyncio.sleep(delay_before_start)
                
            if not self.browser:
                raise RuntimeError("Browser not initialized")
                
            # Создаем контекст браузера
            context: BrowserContext = await self.browser.new_context()
            page: Page = await context.new_page()
            
            task = self.tasks[task_id]
            task.active_sessions += 1
            
            try:
                while task.status == "running":
                    # Переходим на сайт
                    await page.goto("https://gemini.browserbase.com/")
                    await page.wait_for_load_state("networkidle")
                    
                    # Ждем появления input field
                    input_selector = 'input[name="message"]'
                    await page.wait_for_selector(input_selector, timeout=10000)
                    
                    # Вводим текст с варьированием скорости печати (анти-бан)
                    input_field = await page.query_selector(input_selector)
                    await input_field.click()
                    await asyncio.sleep(random.uniform(0.5, 1.5))  # Random delay
                    
                    # Печатаем текст с задержками как человек
                    for char in task_prompt:
                        await page.keyboard.press(char) if len(char) == 1 else await page.keyboard.type(char)
                        await asyncio.sleep(random.uniform(0.05, 0.15))
                    
                    # Ждем появления кнопки Run
                    run_button_selector = 'button[type="submit"]'
                    await page.wait_for_selector(run_button_selector, timeout=5000)
                    run_button = await page.query_selector(run_button_selector)
                    
                    # Нажимаем Run с случайной задержкой
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    await run_button.click()
                    
                    # Следим за появлением кнопки Allow
                    allow_monitor_task = asyncio.create_task(
                        self._monitor_and_click_allow(page, task_id)
                    )
                    
                    # Ждем завершения задачи (~5 минут + задержка на Allow)
                    session_timeout = 330  # 5.5 минут
                    await asyncio.sleep(session_timeout)
                    
                    # Отменяем монитор Allow
                    allow_monitor_task.cancel()
                    try:
                        await allow_monitor_task
                    except asyncio.CancelledError:
                        pass
                    
                    # Следим за появлением Restart кнопки
                    await self._wait_and_click_restart(page)
                    
                    task.completed_sessions += 1
                    
            finally:
                task.active_sessions -= 1
                await page.close()
                await context.close()
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error in session {key}: {e}")
        finally:
            if key in self.session_tasks:
                del self.session_tasks[key]
    
    async def _monitor_and_click_allow(self, page: Page, task_id: str):
        """Мониторит появление кнопки Allow и нажимает её"""
        allow_button_xpath = "//button[contains(text(), 'Allow')]"
        
        while True:
            try:
                allow_buttons = await page.query_selector_all(allow_button_xpath)
                
                if allow_buttons:
                    # Берем последнюю(самую новую) кнопку Allow
                    await allow_buttons[-1].click()
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    
                await asyncio.sleep(1)  # Проверяем каждую секунду
                
            except Exception as e:
                print(f"Error in Allow monitor: {e}")
                await asyncio.sleep(1)
    
    async def _wait_and_click_restart(self, page: Page, timeout: float = 60):
        """Ждет появления Restart кнопки и нажимает её"""
        restart_button_xpath = "//button[contains(., 'Restart')]"
        
        try:
            restart_button = await page.wait_for_selector(
                f"xpath={restart_button_xpath}",
                timeout=timeout * 1000
            )
            
            if restart_button:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                await restart_button.click()
                await asyncio.sleep(2)  # Даем время на перезагрузку
                
        except Exception as e:
            print(f"Restart button not found or error: {e}")
    
    async def run_task(self, task: Task):
        """Запускает задачу с волнообразным распределением сессий"""
        task.status = "running"
        task.active_sessions = 0
        task.completed_sessions = 0
        
        if not self.browser:
            await self.init_browser()
        
        # Волнообразный запуск сессий
        session_count = task.session_count
        
        # Режим 1: Небольшие волны с перерывами (для 10-100 сессий)
        if session_count <= 100:
            sessions_per_wave = min(3, max(1, session_count // 5))  # 3-5 сессий в волне
            waves_count = (session_count + sessions_per_wave - 1) // sessions_per_wave
            delay_between_waves = random.uniform(45, 75)  # 45-75 сек между волнами
            
        # Режим 2: Средние волны (для 101-500)
        elif session_count <= 500:
            sessions_per_wave = random.randint(5, 10)
            waves_count = (session_count + sessions_per_wave - 1) // sessions_per_wave
            delay_between_waves = random.uniform(30, 60)
            
        # Режим 3: Крупные волны (для 500+)
        else:
            sessions_per_wave = random.randint(10, 20)
            waves_count = (session_count + sessions_per_wave - 1) // sessions_per_wave
            delay_between_waves = random.uniform(20, 40)
        
        session_id_counter = 0
        
        for wave_num in range(waves_count):
            if task.status != "running":
                break
                
            # Количество сессий в этой волне
            sessions_in_wave = min(
                sessions_per_wave,
                session_count - (wave_num * sessions_per_wave)
            )
            
            print(f"Task {task.id}: Starting wave {wave_num + 1}/{waves_count} "
                  f"with {sessions_in_wave} sessions")
            
            # Запускаем сессии в волне с задержками
            wave_start_time = asyncio.get_event_loop().time()
            
            for _ in range(sessions_in_wave):
                if task.status != "running":
                    break
                
                session_id_counter += 1
                session_id = str(session_id_counter)
                
                # Распределяем сессии в волне с интервалом 5-15 сек
                initial_delay = random.uniform(0, 15)
                
                task_key = f"{task.id}_{session_id}"
                session_task = asyncio.create_task(
                    self.create_session(task.id, task.prompt, session_id, initial_delay)
                )
                self.session_tasks[task_key] = session_task
            
            # Ждем перед следующей волной
            if wave_num < waves_count - 1:
                await asyncio.sleep(delay_between_waves)
        
        # Ждем завершения всех сессий
        if task.status == "running":
            task.status = "completed"
    
    async def start_task(self, task_id: str):
        """Запускает задачу"""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        
        task = self.tasks[task_id]
        asyncio.create_task(self.run_task(task))
    
    async def stop_task(self, task_id: str):
        """Останавливает задачу и все её сессии"""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        
        task = self.tasks[task_id]
        task.status = "stopped"
        
        # Отменяем все сессии этой задачи
        keys_to_remove = [k for k in self.session_tasks.keys() if k.startswith(task_id)]
        for key in keys_to_remove:
            self.session_tasks[key].cancel()
            try:
                await self.session_tasks[key]
            except asyncio.CancelledError:
                pass
            del self.session_tasks[key]
    
    async def add_task(self, task_id: str, prompt: str, session_count: int) -> Task:
        """Добавляет новую задачу"""
        task = Task(
            id=task_id,
            prompt=prompt,
            session_count=session_count
        )
        self.tasks[task_id] = task
        return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Получает задачу по ID"""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> list[Task]:
        """Получает все задачи"""
        return list(self.tasks.values())


# FastAPI приложение
app = FastAPI(title="Gemini Automation")
manager = GeminiAutomationManager()

# Веб-сокеты для real-time обновлений
ws_connections: list[WebSocket] = []


@app.on_event("startup")
async def startup():
    """Инициализация при запуске"""
    await manager.init_browser()


@app.on_event("shutdown")
async def shutdown():
    """Очистка при выключении"""
    await manager.close_browser()


@app.post("/api/tasks")
async def create_task(task_data: dict):
    """Создает новую задачу"""
    task_id = f"task_{int(asyncio.get_event_loop().time() * 1000)}"
    prompt = task_data.get("prompt", "")
    session_count = task_data.get("sessions", 1)
    
    if not prompt or session_count < 1:
        raise HTTPException(status_code=400, detail="Invalid task data")
    
    task = await manager.add_task(task_id, prompt, session_count)
    await notify_clients({"type": "task_created", "task": task.to_dict()})
    
    return {"id": task_id, "status": "created"}


@app.post("/api/tasks/{task_id}/start")
async def start_task(task_id: str):
    """Запускает задачу"""
    try:
        await manager.start_task(task_id)
        task = manager.get_task(task_id)
        await notify_clients({"type": "task_started", "task": task.to_dict()})
        return {"status": "started"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    """Останавливает задачу"""
    try:
        await manager.stop_task(task_id)
        task = manager.get_task(task_id)
        await notify_clients({"type": "task_stopped", "task": task.to_dict()})
        return {"status": "stopped"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/tasks")
async def get_tasks():
    """Получает все задачи"""
    tasks = manager.get_all_tasks()
    return {"tasks": [t.to_dict() for t in tasks]}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """Получает информацию о задаче"""
    task = manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket соединение для real-time обновлений"""
    await websocket.accept()
    ws_connections.append(websocket)
    
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        ws_connections.remove(websocket)


async def notify_clients(message: dict):
    """Отправляет сообщение всем подключенным клиентам"""
    for connection in ws_connections:
        try:
            await connection.send_json(message)
        except Exception:
            pass


@app.get("/")
async def get_index():
    """Возвращает главную страницу"""
    return FileResponse("index.html")


# Статические файлы
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
