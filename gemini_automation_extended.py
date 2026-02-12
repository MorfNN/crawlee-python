"""
Улучшенная версия Gemini Automation с логированием и сохранением результатов
"""
import asyncio
import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright, Browser, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError


# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('gemini_automation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


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
    failed_sessions: int = 0
    results: list = field(default_factory=list)
    
    def to_dict(self):
        data = asdict(self)
        data['results'] = len(self.results)  # Не отправляем все результаты в UI
        return data
    
    def save_result(self, session_id: str, success: bool, data: dict = None):
        """Сохраняет результат сессии"""
        self.results.append({
            'session_id': session_id,
            'timestamp': datetime.now().isoformat(),
            'success': success,
            'data': data or {}
        })
        
        # Каждые 10 результатов сохраняем в файл
        if len(self.results) % 10 == 0:
            self.save_to_file()
    
    def save_to_file(self):
        """Сохраняет результаты в JSON файл"""
        results_dir = Path('results')
        results_dir.mkdir(exist_ok=True)
        
        file_path = results_dir / f"{self.id}_results.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({
                'task_id': self.id,
                'prompt': self.prompt,
                'session_count': self.session_count,
                'completed_sessions': self.completed_sessions,
                'failed_sessions': self.failed_sessions,
                'results': self.results
            }, f, ensure_ascii=False, indent=2)


class GeminiAutomationManager:
    """Менеджер для управления сессиями Gemini"""
    
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.session_tasks: dict[str, asyncio.Task] = {}
        self.browser: Optional[Browser] = None
        self.playing = True
        
    async def init_browser(self):
        """Инициализация браузера"""
        try:
            logger.info("Инициализация браузера...")
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled']
            )
            logger.info("✅ Браузер инициализирован")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации браузера: {e}")
            raise
        
    async def close_browser(self):
        """Закрытие браузера"""
        if self.browser:
            try:
                await self.browser.close()
                logger.info("Браузер закрыт")
            except Exception as e:
                logger.error(f"Ошибка закрытия браузера: {e}")
            
    async def create_session(
        self,
        task_id: str,
        task_prompt: str,
        session_id: str,
        delay_before_start: float = 0
    ):
        """Создает и управляет одной сессией"""
        key = f"{task_id}_{session_id}"
        task = self.tasks[task_id]
        
        # Логи этой сессии
        session_logs = []
        screenshots_dir = Path('results') / task_id / 'screenshots' / session_id
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Ждем перед стартом для волнообразного распределения
            if delay_before_start > 0:
                await asyncio.sleep(delay_before_start)
                
            if not self.browser:
                raise RuntimeError("Browser not initialized")
            
            logger.info(f"🔄 Сессия {session_id} (задача {task_id}): Старт")
            session_logs.append(f"[{datetime.now().isoformat()}] 🔄 Старт сессии {session_id}")
                
            # Создаем контекст браузера с user-agent
            context: BrowserContext = await self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page: Page = await context.new_page()
            
            # Перехватываем console.log, console.error, console.warn
            def handle_console_message(msg):
                log_entry = f"[{datetime.now().isoformat()}] [{msg.type.upper()}] {msg.text}"
                session_logs.append(log_entry)
                logger.info(f"📱 Сессия {session_id}: {log_entry}")
            
            page.on("console", handle_console_message)
            
            # Скрываем автоматизацию
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
            """)
            
            task.active_sessions += 1
            await notify_clients({"type": "task_update", "task": task.to_dict()})
            
            try:
                iteration = 0
                while task.status == "running" and iteration < 5:  # Max 5 рестартов
                    iteration += 1
                    logger.info(f"🔄 Сессия {session_id}: Итерация {iteration}")
                    
                    try:
                        # Переходим на сайт
                        session_logs.append(f"[{datetime.now().isoformat()}] → Переход на https://gemini.browserbase.com/")
                        await page.goto("https://gemini.browserbase.com/", timeout=30000)
                        await page.wait_for_load_state("networkidle", timeout=30000)
                        session_logs.append(f"[{datetime.now().isoformat()}] ✓ Страница загружена")
                        
                        # Сохраняем скриншот после загрузки
                        screenshot_path = screenshots_dir / f"01_page_loaded.png"
                        await page.screenshot(path=screenshot_path)
                        session_logs.append(f"[{datetime.now().isoformat()}] 📸 Скриншот: {screenshot_path}")
                        
                        # Ждем появления input field
                        input_selector = 'input[name="message"]'
                        await page.wait_for_selector(input_selector, timeout=10000)
                        
                        # Вводим текст с варьированием скорости печати (анти-бан)
                        input_field = await page.query_selector(input_selector)
                        await input_field.click()
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        
                        # Печатаем текст с задержками как человек
                        session_logs.append(f"[{datetime.now().isoformat()}] ⌨️ Ввод текста: {task_prompt[:50]}...")
                        for char in task_prompt:
                            await page.keyboard.type(char)
                            await asyncio.sleep(random.uniform(0.05, 0.15))
                        
                        # Сохраняем скриншот после вввода текста
                        screenshot_path = screenshots_dir / f"02_text_entered.png"
                        await page.screenshot(path=screenshot_path)
                        session_logs.append(f"[{datetime.now().isoformat()}] 📸 Скриншот: {screenshot_path}")
                        
                        # Ждем появления кнопки Run
                        run_button_selector = 'button[type="submit"]'
                        await page.wait_for_selector(run_button_selector, timeout=5000)
                        run_button = await page.query_selector(run_button_selector)
                        
                        # Нажимаем Run с случайной задержкой
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        await run_button.click()
                        session_logs.append(f"[{datetime.now().isoformat()}] 🔨 Нажата кнопка Run")
                        logger.info(f"✅ Сессия {session_id}: Нажата кнопка Run")
                        
                        # Следим за появлением кнопки Allow
                        allow_task = asyncio.create_task(
                            self._monitor_and_click_allow(page, session_id)
                        )
                        
                        # Ждем завершения задачи (~5 минут)
                        session_timeout = 330  # 5.5 минут
                        await asyncio.sleep(session_timeout)
                        
                        # Отменяем монитор Allow
                        allow_task.cancel()
                        try:
                            await allow_task
                        except asyncio.CancelledError:
                            pass
                        
                        # Следим за появлением Restart кнопки
                        await self._wait_and_click_restart(page, session_id)
                        task.completed_sessions += 1
                        task.save_result(session_id, True, {'iteration': iteration})
                        logger.info(f"✅ Сессия {session_id}: Итерация {iteration} завершена")
                        
                    except PlaywrightTimeoutError as e:
                        logger.warning(f"⏱️ Сессия {session_id}: Timeout - {e}")
                        task.failed_sessions += 1
                        break
                    except asyncio.CancelledError:
                        logger.info(f"⏹ Сессия {session_id}: Отменена")
                        break
                    
            finally:
                task.active_sessions -= 1
                
                # Сохраняем логи сессии
                try:
                    logs_path = screenshots_dir / f"00_session_logs.txt"
                    with open(logs_path, 'w', encoding='utf-8') as f:
                        f.write(f"Session ID: {session_id}\n")
                        f.write(f"Task ID: {task_id}\n")
                        f.write(f"Prompt: {task_prompt}\n")
                        f.write(f"=" * 80 + "\n\n")
                        for log in session_logs:
                            f.write(log + "\n")
                    
                    session_logs.append(f"[{datetime.now().isoformat()}] 💾 Логи сохранены в {logs_path}")
                    logger.info(f"💾 Логи сессии {session_id} сохранены")
                except Exception as e:
                    logger.error(f"Ошибка при сохранении логов: {e}")
                
                # Сохраняем содержимое страницы (DOM content)
                try:
                    content = await page.content()
                    html_path = screenshots_dir / f"page_content.html"
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"📄 HTML страницы сохранён в {html_path}")
                except Exception as e:
                    logger.debug(f"Не удалось сохранить HTML: {e}")
                
                await page.close()
                await context.close()
                await notify_clients({"type": "task_update", "task": task.to_dict()})
            
            logger.info(f"✅ Сессия {session_id}: Завершена успешно")
                
        except asyncio.CancelledError:
            logger.info(f"⏹ Сессия {session_id}: Отменена пользователем")
            task.failed_sessions += 1
        except Exception as e:
            logger.error(f"❌ Ошибка в сессии {key}: {e}")
            task.failed_sessions += 1
        finally:
            if key in self.session_tasks:
                del self.session_tasks[key]
    
    async def _monitor_and_click_allow(self, page: Page, session_id: str):
        """Мониторит появление кнопки Allow и нажимает её"""
        allow_count = 0
        
        while True:
            try:
                # Пробуем найти кнопку Allow
                try:
                    allow_button = await page.query_selector('button:has-text("Allow")')
                    
                    if allow_button:
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                        await allow_button.click()
                        allow_count += 1
                        logger.info(f"🔘 Сессия {session_id}: Allow нажата (#{allow_count})")
                        await asyncio.sleep(random.uniform(1, 2))
                except:
                    pass
                
                await asyncio.sleep(1)  # Проверяем каждую секунду
                
            except asyncio.CancelledError:
                logger.info(f"⏹ Монитор Allow для сессии {session_id} отменен")
                break
            except Exception as e:
                logger.debug(f"Ошибка в мониторе Allow: {e}")
                await asyncio.sleep(1)
    
    async def _wait_and_click_restart(self, page: Page, session_id: str, timeout: float = 60):
        """Ждет появления Restart кнопки и нажимает её"""
        try:
            # Ищем кнопку с текстом Restart
            restart_button = await page.wait_for_selector(
                'button:has-text("Restart")',
                timeout=timeout * 1000
            )
            
            if restart_button:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                await restart_button.click()
                logger.info(f"🔄 Сессия {session_id}: Нажата кнопка Restart")
                await asyncio.sleep(2)
                
        except PlaywrightTimeoutError:
            logger.warning(f"⏱️ Сессия {session_id}: Restart не найден за {timeout}с")
        except Exception as e:
            logger.error(f"❌ Ошибка при нажатии Restart: {e}")
    
    async def run_task(self, task: Task):
        """Запускает задачу с волнообразным распределением сессий"""
        task.status = "running"
        task.active_sessions = 0
        task.completed_sessions = 0
        task.failed_sessions = 0
        
        logger.info(f"▶️  Задача {task.id} запущена. Всего сессий: {task.session_count}")
        
        if not self.browser:
            await self.init_browser()
        
        # Волнообразный запуск сессий
        session_count = task.session_count
        
        # Режим 1: Небольшие волны (для 1-100 сессий)
        if session_count <= 100:
            sessions_per_wave = min(3, max(1, session_count // 5))
            waves_count = (session_count + sessions_per_wave - 1) // sessions_per_wave
            delay_between_waves = random.uniform(45, 75)
            
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
        
        logger.info(f"📊 Режим волн: {sessions_per_wave} сессий/волна, "
                   f"{waves_count} волн, задержка {delay_between_waves:.0f}с")
        
        session_id_counter = 0
        
        for wave_num in range(waves_count):
            if task.status != "running":
                logger.info(f"⏹ Задача {task.id}: Остановлена")
                break
                
            # Количество сессий в этой волне
            sessions_in_wave = min(
                sessions_per_wave,
                session_count - (wave_num * sessions_per_wave)
            )
            
            logger.info(f"🌊 Задача {task.id}: Волна {wave_num + 1}/{waves_count} "
                       f"({sessions_in_wave} сессий)")
            await notify_clients({"type": "task_wave", "task_id": task.id, 
                                 "wave": wave_num + 1, "total_waves": waves_count})
            
            # Запускаем сессии в волне с задержками
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
                logger.info(f"⏳ Ожидание {delay_between_waves:.0f}с до следующей волны...")
                await asyncio.sleep(delay_between_waves)
        
        # Ждем завершения всех сессий
        while len([k for k in self.session_tasks.keys() if k.startswith(task.id)]) > 0:
            await asyncio.sleep(2)
        
        if task.status == "running":
            task.status = "completed"
            task.save_to_file()
            logger.info(f"✅ Задача {task.id}: Завершена. "
                       f"Успешно: {task.completed_sessions}, Ошибок: {task.failed_sessions}")
            await notify_clients({"type": "task_completed", "task": task.to_dict()})
    
    async def start_task(self, task_id: str):
        """Запускает задачу"""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        
        task = self.tasks[task_id]
        logger.info(f"📋 Запуск задачи {task_id}")
        asyncio.create_task(self.run_task(task))
    
    async def stop_task(self, task_id: str):
        """Останавливает задачу и все её сессии"""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        
        task = self.tasks[task_id]
        task.status = "stopped"
        
        logger.info(f"⏹ Остановка задачи {task_id}")
        
        # Отменяем все сессии этой задачи
        keys_to_remove = [k for k in self.session_tasks.keys() if k.startswith(task_id)]
        for key in keys_to_remove:
            logger.debug(f"Отмена сессии {key}")
            self.session_tasks[key].cancel()
            try:
                await self.session_tasks[key]
            except asyncio.CancelledError:
                pass
            if key in self.session_tasks:
                del self.session_tasks[key]
        
        task.save_to_file()
        logger.info(f"✅ Задача {task_id}: Остановлена")
    
    async def add_task(self, task_id: str, prompt: str, session_count: int) -> Task:
        """Добавляет новую задачу"""
        task = Task(
            id=task_id,
            prompt=prompt,
            session_count=session_count
        )
        self.tasks[task_id] = task
        logger.info(f"📝 Задача {task_id} создана (сессий: {session_count})")
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

# WebSocket соединения
ws_connections: list[WebSocket] = []

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    """Инициализация при запуске"""
    logger.info("🚀 Запуск приложения Gemini Automation")
    try:
        await manager.init_browser()
    except Exception as e:
        logger.error(f"❌ Ошибка при инициализации: {e}")


@app.on_event("shutdown")
async def shutdown():
    """Очистка при выключении"""
    logger.info("🛑 Выключение приложения")
    await manager.close_browser()


@app.post("/api/tasks")
async def create_task(task_data: dict):
    """Создает новую задачу"""
    task_id = f"task_{int(asyncio.get_event_loop().time() * 1000)}"
    prompt = task_data.get("prompt", "").strip()
    session_count = task_data.get("sessions", 1)
    
    if not prompt or session_count < 1:
        logger.warning(f"❌ Попытка создать задачу с невалидными данными: {task_data}")
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
        logger.error(f"❌ Ошибка при запуске {task_id}: {e}")
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
        logger.error(f"❌ Ошибка при остановке {task_id}: {e}")
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
    logger.info(f"➕ Новое WebSocket соединение. Всего: {len(ws_connections)}")
    
    try:
        while True:
            data = await websocket.receive_text()
            # Ping-pong для проверки соединения
            await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info(f"➖ WebSocket отключен. Осталось: {len(ws_connections) - 1}")
    except Exception as e:
        logger.error(f"❌ Ошибка WebSocket: {e}")
    finally:
        if websocket in ws_connections:
            ws_connections.remove(websocket)


async def notify_clients(message: dict):
    """Отправляет сообщение всем подключенным клиентам"""
    disconnected = []
    for connection in ws_connections:
        try:
            await connection.send_json(message)
        except Exception as e:
            logger.debug(f"Ошибка отправки WebSocket: {e}")
            disconnected.append(connection)
    
    # Удаляем отключенные соединения
    for connection in disconnected:
        if connection in ws_connections:
            ws_connections.remove(connection)


@app.get("/")
async def get_index():
    """Возвращает главную страницу"""
    return FileResponse("index.html")


@app.get("/health")
async def health_check():
    """Проверка здоровья приложения"""
    return {
        "status": "ok",
        "tasks": len(manager.tasks),
        "active_sessions": sum(t.active_sessions for t in manager.tasks.values()),
        "ws_connections": len(ws_connections)
    }


# Статические файлы
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Gemini Automation Automation v1.0")
    logger.info("=" * 50)
    logger.info(f"Запуск на http://0.0.0.0:8000")
    logger.info("=" * 50)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True
    )
