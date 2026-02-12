#!/usr/bin/env python3
"""
Специальный скрипт для запуска Gemini Automation через GitHub Actions
с детальным захватом логов и результатов
"""

import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# Импортируем основной менеджер
from gemini_automation_extended import GeminiAutomationManager, Task


class GitHubActionsRunner:
    """Wrapper для запуска в GitHub Actions с улучшенным логированием"""
    
    def __init__(self, session_count: int = 5, prompt: str = "Сколько стоит акция NVIDIA?"):
        self.session_count = session_count
        self.prompt = prompt
        self.task_id = str(uuid.uuid4())[:8]
        self.manager = GeminiAutomationManager()
        self.results_dir = Path('results')
        self.tasks_log = []
        
    async def run(self):
        """Запускает автоматизацию с полным логированием"""
        
        print("\n" + "="*80)
        print("🚀 GEMINI AUTOMATION - GITHUB ACTIONS MODE")
        print("="*80)
        print(f"⏰ Started at: {datetime.now().isoformat()}")
        print(f"📋 Task ID: {self.task_id}")
        print(f"📊 Session Count: {self.session_count}")
        print(f"📝 Prompt: {self.prompt[:60]}...")
        print("="*80 + "\n")
        
        try:
            # Инициализируем браузер
            print("🌐 Initializing browser...")
            await self.manager.init_browser()
            print("✅ Browser initialized\n")
            
            # Создаем задачу
            print("📝 Creating task...")
            task = Task(
                id=self.task_id,
                prompt=self.prompt,
                session_count=self.session_count
            )
            self.manager.tasks[self.task_id] = task
            print(f"✅ Task created: {self.task_id}\n")
            
            # Логируем начало
            self.tasks_log.append({
                'timestamp': datetime.now().isoformat(),
                'event': 'task_created',
                'task_id': self.task_id,
                'session_count': self.session_count
            })
            
            # Запускаем задачу
            print("▶️  Starting automation task...")
            print("-"*80)
            
            await self.manager.run_task(task)
            
            # Ждем завершения с логированием
            iteration = 0
            while task.status == "running" and task.active_sessions > 0:
                iteration += 1
                
                # Выводим статус каждые 10 секунд
                if iteration % 2 == 0:
                    status = (
                        f"📊 Status: Active={task.active_sessions} | "
                        f"Completed={task.completed_sessions} | "
                        f"Failed={task.failed_sessions}"
                    )
                    print(status)
                    
                    self.tasks_log.append({
                        'timestamp': datetime.now().isoformat(),
                        'event': 'status_update',
                        'active': task.active_sessions,
                        'completed': task.completed_sessions,
                        'failed': task.failed_sessions
                    })
                
                await asyncio.sleep(5)
            
            print("-"*80)
            
            # Финальное сохранение
            print("💾 Saving results...")
            task.save_to_file()
            
            # Результаты
            print("\n" + "="*80)
            print("✅ TASK COMPLETED")
            print("="*80)
            print(f"⏱️  Duration: {datetime.now().isoformat()}")
            print(f"📊 Summary:")
            print(f"   Total Sessions:   {task.session_count}")
            print(f"   Completed:        {task.completed_sessions}")
            print(f"   Failed:           {task.failed_sessions}")
            print(f"   Success Rate:     {(task.completed_sessions/task.session_count*100):.1f}%")
            print(f"📁 Results saved to: {self.results_dir}/{self.task_id}/")
            print("="*80 + "\n")
            
            self.tasks_log.append({
                'timestamp': datetime.now().isoformat(),
                'event': 'task_completed',
                'completed': task.completed_sessions,
                'failed': task.failed_sessions,
                'total': task.session_count
            })
            
            # Сохраняем логи tasks
            self._save_tasks_log()
            
            return task.completed_sessions >= task.session_count * 0.8  # 80% успеха
            
        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            
            self.tasks_log.append({
                'timestamp': datetime.now().isoformat(),
                'event': 'error',
                'error': str(e)
            })
            self._save_tasks_log()
            
            return False
            
        finally:
            print("🛑 Closing browser...")
            await self.manager.close_browser()
            print("✅ Browser closed\n")
    
    def _save_tasks_log(self):
        """Сохраняет логи задач в JSON"""
        self.results_dir.mkdir(exist_ok=True)
        
        log_file = self.results_dir / f"{self.task_id}_tasks_log.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump({
                'task_id': self.task_id,
                'prompt': self.prompt,
                'session_count': self.session_count,
                'start_time': self.tasks_log[0]['timestamp'] if self.tasks_log else None,
                'end_time': self.tasks_log[-1]['timestamp'] if self.tasks_log else None,
                'events': self.tasks_log
            }, f, ensure_ascii=False, indent=2)
        
        print(f"💾 Tasks log saved: {log_file}")


async def main():
    """Main entry point"""
    
    # Получаем параметры из аргументов или переменных окружения
    import os
    
    session_count = int(os.getenv('SESSION_COUNT', sys.argv[1] if len(sys.argv) > 1 else '5'))
    prompt = os.getenv('TASK_PROMPT', sys.argv[2] if len(sys.argv) > 2 else 'Сколько стоит акция NVIDIA?')
    
    print(f"📌 Config: {session_count} sessions with prompt: {prompt}")
    
    runner = GitHubActionsRunner(
        session_count=session_count,
        prompt=prompt
    )
    
    success = await runner.run()
    
    # Exit code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
