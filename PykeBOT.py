import discord
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
from discord import SelectOption, Interaction, Embed
from datetime import datetime
from ApplicationGet import setup_application, pending_applicants
from PasswordContain import setup_passwords
import sqlite3
import os
import io
from dotenv import load_dotenv
import logging
import random
import asyncio  # Добавлено для автозамены
import re

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Загрузка токена
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Настройка интентов
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Подключение к базе данных
conn = sqlite3.connect('tasks.db')
pas = sqlite3.connect('foxhole_passwords.db')

c = conn.cursor()
p = pas.cursor()

# Создание таблиц, если не существуют
c.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        category TEXT,
        status TEXT,
        assigned_to INTEGER,
        created_by INTEGER,
        created_at TEXT,
        completed_at TEXT
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS presets (
        preset_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        title TEXT,
        description TEXT,
        category TEXT
    )
''')

# Утилита для добавления столбцов, если их нет
def safe_add_column(table: str, column: str, col_type: str, default=None):
    try:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
        if default is not None:
            c.execute(f'UPDATE {table} SET {column} = ?', (default,))
        conn.commit()
        logging.info(f"Added column '{column}' to table '{table}'")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            logging.info(f"Column '{column}' already exists in '{table}'")
        else:
            logging.error(f"Error adding column '{column}' to '{table}': {e}")
            
            
def safe_add_column_pass(table: str, column: str, col_type: str, default=None):
    try:
        p.execute(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
        if default is not None:
            p.execute(f'UPDATE {table} SET {column} = ?', (default,))
        pas.commit()
        logging.info(f"Added column '{column}' to table '{table}'")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            logging.info(f"Column '{column}' already exists in '{table}'")
        else:
            logging.error(f"Error adding column '{column}' to '{table}': {e}")

# Создание таблицы с hex и city вместо location
p.execute('''
    CREATE TABLE IF NOT EXISTS foxhole_passwords (
        id TEXT PRIMARY KEY,
        code TEXT,
        author TEXT,
        hex TEXT,
        city TEXT,
        description TEXT,
        created_at TEXT
    )
''')
pas.commit()

safe_add_column("tasks", "accepted_at", "TEXT")

# Добавляем недостающие поля в foxhole_passwords
safe_add_column_pass("foxhole_passwords", "hex", "TEXT")
safe_add_column_pass("foxhole_passwords", "city", "TEXT")
safe_add_column_pass("foxhole_passwords", "important", "INTEGER", default=0)  # Важный склад


# Добавляем недостающие поля в presets
safe_add_column("presets", "due_date", "TEXT")
safe_add_column("presets", "points", "INTEGER", default=2)
safe_add_column("presets", "image_url", "TEXT")
safe_add_column("presets", "repeat_daily", "INTEGER", default=0)

# Создание таблицы логов очков
c.execute('''
    CREATE TABLE IF NOT EXISTS points_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_id INTEGER,
        points_earned INTEGER,
        timestamp TEXT
    )
''')
c.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON points_log (user_id)")

conn.commit()

# Категории задач
CATEGORIES = {
    'Фарм': '⛏️',
    'Логистика': '🚚',
    'Завод': '🏭',
    'Рекрутинг': '👤',
    'Разведка': '👀',
    'МПФ': '🏭',
    'Строительство': '⛏️',
    'Другое': '📦'
}

# Проверка ролей
def is_officer(user) -> bool:
    if hasattr(user, "author"):
        user = user.author
    elif hasattr(user, "user"):
        user = user.user
    return any(role.name in ['Лейтенант', 'Офицер', 'Капитан', 'Лидер','Генерал','Ветеран'] for role in getattr(user, "roles", []))

def is_clan(user) -> bool:
    if hasattr(user, "author"):
        user = user.author
    elif hasattr(user, "user"):
        user = user.user
    return any(role.name in ['Лейтенант', 'Офицер', 'Капитан', 'Лидер', 'Сержант', 'Солдат', 'Рекрут', 'Соклановец','Генерал','Ветеран'] for role in getattr(user, "roles", []))

def is_rekrut(member: discord.Member) -> bool:
    return any(role.name in ['Рекрут'] for role in member.roles)

# Функция для создания маленького эмбеда
def create_small_embed(large_embed):
    small_embed = discord.Embed(title=large_embed.title, color=large_embed.color)
    if large_embed.description:
        small_desc = large_embed.description[:100] + "..." if len(large_embed.description) > 100 else large_embed.description
        small_embed.description = small_desc
    return small_embed

# Функции для отложенной замены эмбедов
async def delayed_edit(interaction, small_embed):
    await asyncio.sleep(600)  # 10 минут
    try:
        await interaction.edit_original_response(embed=small_embed)
    except discord.HTTPException as e:
        logging.error(f"Failed to edit original response: {e}")

async def delayed_replace(message, small_embed):
    await asyncio.sleep(600)  # 10 минут
    try:
        await message.edit(embed=small_embed)
    except discord.HTTPException as e:
        logging.error(f"Failed to edit message: {e}")

# Модальное окно для создания задачи
class CreateTaskModal(Modal, title="Создать задачу"):
    def __init__(self, category: str, image_url: str = None):
        super().__init__()
        self.category = category
        self.image_url = image_url
        self.title_input = TextInput(label="Заголовок", placeholder="Краткое название задачи")
        self.description_input = TextInput(label="Описание", style=discord.TextStyle.long)
        self.due_date_input = TextInput(label="Срок выполнения", placeholder="Например, 2025-12-31 23:59", required=False)
        self.points_input = TextInput(label="Баллы за выполнение", placeholder="Введите количество баллов (целое число >=1)", required=True)
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.due_date_input)
        self.add_item(self.points_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("🚫 Недостаточно прав.", ephemeral=True)
        
        title = self.title_input.value.strip()
        description = self.description_input.value.strip()
        due_date = self.due_date_input.value.strip() if self.due_date_input.value else None
        points_str = self.points_input.value.strip()

        if not title or not description:
            return await interaction.response.send_message("🚫 Заголовок и описание не могут быть пустыми.", ephemeral=True)
        if not points_str.isdigit() or int(points_str) < 1:
            return await interaction.response.send_message("🚫 Баллы должны быть целым числом >=1.", ephemeral=True)
        
        points = int(points_str)
        created_at = datetime.now().isoformat()

        try:
            c.execute(
                "INSERT INTO tasks (title, description, category, status, assigned_to, created_by, created_at, due_date, points, image_url) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (title, description, self.category, 'available', None, interaction.user.id, created_at, due_date, points, self.image_url)
            )
            conn.commit()
            task_id = c.lastrowid
            
            embed = discord.Embed(
                title=f"✅ Задача #{task_id} создана",
                description=f"**{title}**\n{description}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Категория", value=self.category)
            if due_date:
                embed.add_field(name="Срок выполнения", value=due_date)
            embed.add_field(name="Баллы", value=points)
            if self.image_url:
                embed.set_image(url=self.image_url)
            embed.set_footer(text=f"Создал(а): {interaction.user.display_name}")
            await interaction.response.send_message(embed=embed)
            bot.loop.create_task(delayed_edit(interaction, create_small_embed(embed)))
        except sqlite3.Error as e:
            logging.error(f"Ошибка базы данных: {e}")
            await interaction.response.send_message("❌ Произошла ошибка при создании задачи.", ephemeral=True)
class CreateTaskWithImageView(View):
    def __init__(self, category: str):
        super().__init__(timeout=300)
        self.category = category
        self.image_url = None

    @discord.ui.button(label="Прикрепить изображение", style=discord.ButtonStyle.secondary)
    async def attach_image(self, interaction: Interaction, button: Button):
        await interaction.response.send_message("📎 Пришлите изображение в следующем сообщении.", ephemeral=True)

        def check(m):
            return m.author == interaction.user and m.attachments and m.channel == interaction.channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            attachment = msg.attachments[0]

            # Найти канал log
            log_channel = discord.utils.get(msg.guild.text_channels, name="log")
            if not log_channel:
                await interaction.followup.send("❌ Канал log не найден.", ephemeral=True)
                return

            # Отправить изображение в канал log
            log_message = await log_channel.send(
                f"Изображение для задачи от {interaction.user.mention}",
                file=await attachment.to_file()
            )
            # Получить ссылку на вложение
            log_url = log_message.attachments[0].url
            self.image_url = log_url
            await msg.delete()

            try:
                await interaction.message.edit(view=None)
            except discord.NotFound:
                pass

            await interaction.followup.send(
                "✅ Изображение прикреплено! Не удаляйте изображение из канала log!",
                ephemeral=True
            )

            modal = CreateTaskModal(self.category, self.image_url)
            await interaction.followup.send(
                "📝 Нажмите кнопку, чтобы заполнить детали задачи:",
                view=ModalView(modal),
                ephemeral=True
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Время ожидания изображения истекло.", ephemeral=True)
        except Exception as e:
            logging.error(f"Ошибка при обработке изображения: {e}")
            await interaction.followup.send("❌ Произошла ошибка при обработке изображения.", ephemeral=True)
    @discord.ui.button(label="Создать без изображения", style=discord.ButtonStyle.primary)
    async def create_without_image(self, interaction: Interaction, button: Button):
    # Открывается модальное окно без image_url
        await interaction.response.send_modal(CreateTaskModal(self.category))

# Добавляем вспомогательный класс для отображения модального окна
class ModalView(View):
    def __init__(self, modal):
        super().__init__()
        self.modal = modal

    @discord.ui.button(label="Заполнить данные", style=discord.ButtonStyle.primary)
    async def show_modal(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(self.modal)
        
# Select для выбора категории при создании задачи
class CreateTaskCategorySelect(Select):
    def __init__(self, parent_view):
        options = [SelectOption(label=cat, value=cat) for cat in CATEGORIES.keys()]
        super().__init__(placeholder="Выберите категорию", options=options, custom_id="select_create_category_v11")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        category = self.values[0]
        await interaction.response.send_message(
            "Хотите прикрепить изображение к задаче?",
            view=CreateTaskWithImageView(category),
            ephemeral=True
        )

# Представление для выбора категории при создании задачи
class CreateTaskCategoryView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(CreateTaskCategorySelect(self))

# Модальное окно для создания пресета
class CreatePresetModal(Modal, title="Создать новый пресет"):
    def __init__(self, category: str, image_url: str = None):
        super().__init__()
        self.category = category
        self.image_url = image_url
        self.name_input = TextInput(label="Имя пресета", placeholder="Например: «Фарм-нон-стоп» (короткое уникальное имя)")
        self.title_input = TextInput(label="Заголовок задачи", placeholder="Краткий заголовок, который увидят все в списке задач")
        self.description_input = TextInput(label="Описание задачи", style=discord.TextStyle.long, placeholder="Подробно опишите, что нужно сделать")
        self.due_date_input = TextInput(label="Срок выполнения (опционально)", placeholder="YYYY-MM-DD HH:MM", required=False)
        self.points_input = TextInput(label="Баллы за выполнение", placeholder="Введите количество баллов (целое число >=1)", required=True)
        for item in (self.name_input, self.title_input, self.description_input, self.due_date_input, self.points_input):
            self.add_item(item)

    async def on_submit(self, interaction: Interaction):
        if not self.category:
            return await interaction.response.send_message("🚫 Категория не выбрана.", ephemeral=True)
        name = self.name_input.value.strip()
        title = self.title_input.value.strip()
        desc = self.description_input.value.strip()
        category = self.category
        due_date = self.due_date_input.value.strip() or None
        points_str = self.points_input.value.strip()
        if not all([name, title, desc, category]):
            return await interaction.response.send_message("🚫 Все поля кроме срока выполнения обязательны.", ephemeral=True)
        if category not in CATEGORIES:
            return await interaction.response.send_message(f"🚫 Неверная категория. Доступно: {', '.join(CATEGORIES.keys())}.", ephemeral=True)
        if not points_str.isdigit() or int(points_str) < 1:
            return await interaction.response.send_message("🚫 Баллы должны быть целым числом >=1.", ephemeral=True)
        
        points = int(points_str)
        
        try:
            c.execute(
                "INSERT INTO presets (name, title, description, category, due_date, points, image_url) VALUES (?,?,?,?,?,?,?)",
                (name, title, desc, category, due_date, points, self.image_url)
            )
            conn.commit()
            embed = discord.Embed(
                title=f"✅ Пресет «{name}» создан",
                description=f"**{title}**\n{desc}",
                color=discord.Color.green()
            )
            if self.image_url:
                embed.set_image(url=self.image_url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except sqlite3.IntegrityError:
            await interaction.response.send_message("🚫 Пресет с таким именем уже существует.", ephemeral=True)
            
class CreatePresetWithImageView(View):
    def __init__(self, category: str):
        super().__init__(timeout=300)
        self.category = category
        self.image_url = None

    @discord.ui.button(label="Прикрепить изображение", style=discord.ButtonStyle.secondary)
    async def attach_image(self, interaction: Interaction, button: Button):
        await interaction.response.send_message("📎 Пришлите изображение в следующем сообщении.", ephemeral=True)

        def check(m):
            return m.author == interaction.user and m.attachments and m.channel == interaction.channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            attachment = msg.attachments[0]

            # Найти канал log
            log_channel = discord.utils.get(msg.guild.text_channels, name="log")
            if not log_channel:
                await interaction.followup.send("❌ Канал log не найден.", ephemeral=True)
                return

            # Отправить изображение в канал log
            log_message = await log_channel.send(
                f"Изображение для пресета от {interaction.user.mention}",
                file=await attachment.to_file()
            )
            # Получить ссылку на вложение
            log_url = log_message.attachments[0].url
            self.image_url = log_url
            await msg.delete()

            try:
                await interaction.message.edit(view=None)
            except discord.NotFound:
                pass

            await interaction.followup.send(
                "✅ Изображение прикреплено! Не удаляйте изображение из канала log!",
                ephemeral=True
            )

            modal = CreatePresetModal(self.category, self.image_url)
            await interaction.followup.send(
                "📝 Нажмите кнопку, чтобы заполнить детали пресета:",
                view=ModalView(modal),
                ephemeral=True
            )

        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Время ожидания изображения истекло.", ephemeral=True)
        except Exception as e:
            logging.error(f"Ошибка при обработке изображения: {e}")
            await interaction.followup.send("❌ Произошла ошибка при обработке изображения.", ephemeral=True)
    @discord.ui.button(label="Создать без изображения", style=discord.ButtonStyle.primary)
    async def create_without_image(self, interaction: Interaction, button: Button):
        # Открывается модальное окно без image_url
        await interaction.response.send_modal(CreatePresetModal(self.category))
        
# Кнопка удаления задачи
class DeleteTaskButton(Button):
    def __init__(self, parent_view):
        super().__init__(label="Удалить задачу", style=discord.ButtonStyle.danger, custom_id="btn_delete_task")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        view: AllTasksView = self.parent_view
        tid = view.selected_task_id
        if not is_officer(interaction.user):
            return await interaction.response.send_message("🚫 Недостаточно прав.", ephemeral=True)
        try:
            c.execute("DELETE FROM tasks WHERE task_id = ?", (tid,))
            conn.commit()
            await interaction.channel.send(f"🗑️ {interaction.user.mention} удалил(а) задачу #{tid}")
            await interaction.response.edit_message(content=f"🗑️ Задача #{tid} удалена", embed=None, view=None)
            view.stop()
        except sqlite3.Error as e:
            logging.error(f"Ошибка при удалении задачи: {e}")
            await interaction.response.send_message("❌ Не удалось удалить задачу.", ephemeral=True)

# Select для выбора категории для получения задачи
# Select для выбора категории для получения задачи
class CategorySelectGet(Select):
    def __init__(self, parent_view):
        options = [SelectOption(label="Любой тип задачи", value="any")] + [SelectOption(label=cat, value=cat) for cat in CATEGORIES.keys()]
        super().__init__(placeholder="Выберите категорию", options=options, custom_id="select_category_get_v11")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        category = self.values[0]
        try:
            if is_rekrut(interaction.user):
                c.execute("SELECT COUNT(*) FROM tasks WHERE status = 'assigned' AND assigned_to = ?", (interaction.user.id,))
                if c.fetchone()[0] > 0:
                    return await interaction.response.send_message("🚫 Рекруты могут выполнять только одну задачу одновременно.", ephemeral=True)
            if category == "any":
                c.execute("SELECT task_id, title, description, created_by, created_at, due_date, points, category, image_url FROM tasks WHERE status = 'available' AND assigned_to IS NULL ORDER BY created_at ASC LIMIT 1")
            else:
                c.execute("SELECT task_id, title, description, created_by, created_at, due_date, points, category, image_url FROM tasks WHERE category = ? AND status = 'available' AND assigned_to IS NULL ORDER BY created_at ASC LIMIT 1", (category,))
            task = c.fetchone()
            if task:
                task_id, title, description, created_by, created_at, due_date, points, task_category, image_url = task
                c.execute("UPDATE tasks SET status='assigned', assigned_to=?, accepted_at=? WHERE task_id=?", (interaction.user.id, datetime.now().isoformat(), task_id))
                conn.commit()
                guild = interaction.guild
                created_by_user = guild.get_member(created_by) if guild else bot.get_user(created_by)
                embed = Embed(title=f"✅ Задача #{task_id} назначена", description=f"**{title}**\n{description}", color=discord.Color.blue(), timestamp=datetime.now())
                embed.add_field(name="Категория", value=task_category)
                embed.add_field(name="Баллы", value=points)
                if due_date:
                    embed.add_field(name="Срок выполнения", value=due_date)
                embed.add_field(name="Создал(а)", value=(created_by_user.mention if created_by_user else "Unknown"))
                embed.add_field(name="Назначена", value=interaction.user.mention)
                embed.add_field(name="Хронология", value=f"Создана: {created_at}\nПринята: {datetime.now().isoformat()}")
                if image_url:
                    embed.set_image(url=image_url)
                message = await interaction.channel.send(embed=embed)
                bot.loop.create_task(delayed_replace(message, create_small_embed(embed)))
                await interaction.response.send_message(f"✅ Вам назначена задача #{task_id}: {title}", ephemeral=True)
            else:
                await interaction.response.send_message(f"🚫 Нет доступных задач{' в категории ' + category if category != 'any' else ''}.", ephemeral=True)
        except sqlite3.Error as e:
            logging.error(f"Ошибка базы данных: {e}")
            await interaction.response.send_message("❌ Произошла ошибка при получении задачи.", ephemeral=True)

# Представление для получения задачи
class GetTaskView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(CategorySelectGet(self))

# Select для выбора категории задач
class TaskCategorySelect(Select):
    def __init__(self, parent_view):
        options = [SelectOption(label="Свободные задачи", value="available"), SelectOption(label="Мои задачи", value="mine")]
        super().__init__(placeholder="Выберите категорию задач", options=options, custom_id="select_category_v11")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        view: TaskManagementView = self.parent_view
        view.category = self.values[0]
        try:
            if view.category == "available":
                c.execute("SELECT COUNT(*) FROM tasks WHERE status = 'available'")
            elif view.category == "mine":
                c.execute("SELECT COUNT(*) FROM tasks WHERE (assigned_to = ? OR created_by = ?) AND status IN ('available', 'assigned')", (interaction.user.id, interaction.user.id))
            total_tasks = c.fetchone()[0]
            view.total_pages = (total_tasks + 24) // 25
            view.current_page = 1
            view.state = "view_tasks"
            await view.update_view(interaction)
        except sqlite3.Error as e:
            logging.error(f"Ошибка базы данных: {e}")
            await interaction.response.send_message("❌ Произошла ошибка при получении задач.", ephemeral=True)

# Select для выбора категории всех задач
class AllTasksSelect(Select):
    def __init__(self, parent_view):
        options = [SelectOption(label="Актуальные задачи", value="active"), SelectOption(label="Выполненные задачи", value="completed")]
        super().__init__(placeholder="Выберите категорию задач", options=options, custom_id="select_all_tasks_v11")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        view: AllTasksView = self.parent_view
        view.category = self.values[0]
        try:
            if view.category == "active":
                c.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('available', 'assigned')")
            elif view.category == "completed":
                c.execute("SELECT COUNT(*) FROM tasks WHERE status = 'completed'")
            total_tasks = c.fetchone()[0]
            view.total_pages = (total_tasks + 24) // 25
            view.current_page = 1
            view.state = "view_tasks"
            await view.update_view(interaction)
        except sqlite3.Error as e:
            logging.error(f"Ошибка базы данных: {e}")
            await interaction.response.send_message("❌ Произошла ошибка при получении задач.", ephemeral=True)

# Select для выбора задачи
class TaskSelect(Select):
    def __init__(self, options, parent_view):
        super().__init__(placeholder="Выберите задачу", options=options, custom_id="select_task_v11")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        view = self.parent_view
        view.selected_task_id = int(self.values[0])
        view.state = "view_task_details"
        await view.update_view(interaction)

# Кнопка "Назад"
class PreviousButton(Button):
    def __init__(self, parent_view):
        super().__init__(label="⬅️ Назад", style=discord.ButtonStyle.secondary, custom_id="btn_prev_v11")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        view = self.parent_view
        view.current_page -= 1
        view.state = "view_tasks"
        await view.update_view(interaction)

# Кнопка "Вперёд"
class NextButton(Button):
    def __init__(self, parent_view):
        super().__init__(label="➡️ Вперёд", style=discord.ButtonStyle.secondary, custom_id="btn_next_v11")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        view = self.parent_view
        view.current_page += 1
        view.state = "view_tasks"
        await view.update_view(interaction)

# Кнопка "Принять"
class AcceptButton(Button):
    def __init__(self, parent_view):
        super().__init__(label="Принять", style=discord.ButtonStyle.success, custom_id="btn_accept_v11")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        view = self.parent_view
        tid = view.selected_task_id
        if not tid:
            return await interaction.response.send_message("❗ Сначала выберите задачу", ephemeral=True)
        try:
            if is_rekrut(interaction.user):
                c.execute("SELECT COUNT(*) FROM tasks WHERE status = 'assigned' AND assigned_to = ?", (interaction.user.id,))
                if c.fetchone()[0] > 0:
                    return await interaction.response.send_message("🚫 Рекруты могут выполнять только одну задачу одновременно.", ephemeral=True)
            row = c.execute("SELECT status, title FROM tasks WHERE task_id = ?", (tid,)).fetchone()
            if not row or row[0] != 'available':
                return await interaction.response.send_message("🚫 Нельзя принять", ephemeral=True)
            title = row[1]
            c.execute("UPDATE tasks SET status='assigned', assigned_to=?, accepted_at=? WHERE task_id=?", (interaction.user.id, datetime.now().isoformat(), tid))
            conn.commit()
            await interaction.channel.send(f"✅ {interaction.user.mention} принял(а) задачу #{tid}: {title}")
            await interaction.response.edit_message(content=f"✅ Задача #{tid} принята", embed=None, view=None)
            view.stop()
        except sqlite3.Error as e:
            logging.error(f"Ошибка базы данных: {e}")
            await interaction.response.send_message("❌ Произошла ошибка при принятии задачи.", ephemeral=True)

# Кнопка "Завершить"
class CompleteButton(Button):
    def __init__(self, parent_view):
        super().__init__(label="Завершить", style=discord.ButtonStyle.green, custom_id="btn_complete")
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        tid = self.parent_view.selected_task_id
        if not tid:
            return await interaction.response.send_message("❗ Сначала выберите задачу", ephemeral=True)

        try:
            row = c.execute(
                "SELECT status, assigned_to, title, points FROM tasks WHERE task_id = ?",
                (tid,)
            ).fetchone()
            if not row:
                return await interaction.response.send_message("🚫 Задача не найдена", ephemeral=True)

            status, assigned_to, title, points = row

            if status != "assigned" or assigned_to != interaction.user.id:
                return await interaction.response.send_message("🚫 Нельзя завершить эту задачу", ephemeral=True)

            c.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ? WHERE task_id = ?",
                (datetime.now().isoformat(), tid)
            )
            conn.commit()

            earned_text = ""
            if points and points > 0:
                c.execute(
                    "INSERT INTO points_log (user_id, task_id, points_earned, timestamp) VALUES (?, ?, ?, ?)",
                    (interaction.user.id, tid, points, datetime.now().isoformat())
                )
                conn.commit()
                earned_text = f"\n🎉 Вы получили **{points}** баллов!"

            result = f"✅ {interaction.user.mention} завершил(а) задачу #{tid}: **{title}**{earned_text}"
            await interaction.response.send_message(result, ephemeral=False)

            if interaction.message:
                await interaction.message.edit(view=None)

            self.parent_view.stop()

        except sqlite3.Error as e:
            logging.error(f"CompleteButton error: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Ошибка при завершении задачи.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Ошибка при завершении задачи.", ephemeral=True)

# Кнопка "Отвязать"
class UnassignButton(Button):
    def __init__(self, parent_view):
        super().__init__(label="Отвязать", style=discord.ButtonStyle.secondary, custom_id="btn_unassign_v11")
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        view = self.parent_view
        tid = view.selected_task_id
        if not tid:
            return await interaction.response.send_message("❗ Сначала выберите задачу", ephemeral=True)
        try:
            row = c.execute("SELECT title, status, assigned_to FROM tasks WHERE task_id = ?", (tid,)).fetchone()
            if not row:
                return await interaction.response.send_message("🚫 Задача не найдена", ephemeral=True)
            title, status, assigned_to = row
            if status != 'assigned':
                return await interaction.response.send_message("🚫 Задача не назначена", ephemeral=True)
            if assigned_to != interaction.user.id and not is_officer(interaction.user):
                return await interaction.response.send_message("🚫 Вы можете отвязать только свои задачи или иметь права офицера.", ephemeral=True)
            row = c.execute("""
                SELECT title, description, category, points, created_by, created_at, due_date
                FROM tasks WHERE task_id = ?
            """, (tid,)).fetchone()
            title, description, category, points, created_by, created_at, due_date = row

            c.execute("UPDATE tasks SET status='available', assigned_to=NULL, accepted_at=NULL WHERE task_id=?", (tid,))
            conn.commit()

            embed = Embed(
                title=f"❌ Задача #{tid} отвязана",
                description=f"**{title}**\n{description[:1000]}",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Категория", value=category)
            embed.add_field(name="Баллы", value=points)
            embed.add_field(name="Создана", value=created_at)
            if due_date:
                embed.add_field(name="Срок выполнения", value=due_date)

            message = await interaction.channel.send(embed=embed)
            bot.loop.create_task(delayed_replace(message, create_small_embed(embed)))
            self.parent_view.stop()
        except sqlite3.Error as e:
            logging.error(f"Ошибка БД при отвязывании задачи #{tid}: {e}")
            await interaction.response.send_message("❌ Произошла ошибка при отказе от задачи.", ephemeral=True)

# Select для выбора задачи для завершения или отвязывания
# Select для выбора задачи для завершения или отвязывания
class TaskActionSelect(Select):
    def __init__(self, options, action_type, parent_view):
        super().__init__(placeholder="Выберите задачу", options=options, custom_id=f"select_task_{action_type}_v11")
        self.action_type = action_type
        self.parent_view = parent_view

    async def callback(self, interaction: Interaction):
        tid = int(self.values[0])
        try:
            if self.action_type == "complete":
                try:
                    row = c.execute(
                        "SELECT status, assigned_to, title, points FROM tasks WHERE task_id = ?",
                        (tid,)
                    ).fetchone()
                    if not row:
                        return await interaction.response.send_message("🚫 Задача не найдена", ephemeral=True)

                    status, assigned_to, title, points = row

                    if status != "assigned" or assigned_to != interaction.user.id:
                        return await interaction.response.send_message("🚫 Нельзя завершить эту задачу", ephemeral=True)

                    c.execute(
                        "UPDATE tasks SET status = 'completed', completed_at = ? WHERE task_id = ?",
                        (datetime.now().isoformat(), tid)
                    )
                    conn.commit()

                    earned_text = ""
                    if points and points > 0:
                        c.execute(
                            "INSERT INTO points_log (user_id, task_id, points_earned, timestamp) VALUES (?, ?, ?, ?)",
                            (interaction.user.id, tid, points, datetime.now().isoformat())
                        )
                        conn.commit()
                        earned_text = f"\n🎉 Вы получили **{points}** баллов!"

                    result = f"✅ {interaction.user.mention} завершил(а) задачу #{tid}: **{title}**{earned_text}"
                    await interaction.response.send_message(result, ephemeral=False)

                    if interaction.message:
                        try:
                            await interaction.message.edit(view=None)
                        except discord.errors.NotFound:
                            logging.warning(f"Сообщение для задачи #{tid} не найдено при попытке убрать View")

                    self.parent_view.stop()

                except sqlite3.Error as e:
                    logging.error(f"TaskActionSelect.complete error: {e}")
                    if not interaction.response.is_done():
                        await interaction.response.send_message("❌ Ошибка при завершении задачи.", ephemeral=True)
                    else:
                        await interaction.followup.send("❌ Ошибка при завершении задачи.", ephemeral=True)
            elif self.action_type == "unassign":
                row = c.execute("SELECT title, status, assigned_to, image_url FROM tasks WHERE task_id = ?", (tid,)).fetchone()
                if not row:
                    return await interaction.response.send_message("🚫 Задача не найдена", ephemeral=True)
                title, status, assigned_to, image_url = row
                if status != 'assigned':
                    return await interaction.response.send_message("🚫 Задача не назначена", ephemeral=True)
                if assigned_to != interaction.user.id and not is_officer(interaction.user):
                    return await interaction.response.send_message("🚫 Вы можете отвязать только свои задачи или иметь права офицера.", ephemeral=True)
                c.execute("UPDATE tasks SET status='available', assigned_to=NULL, accepted_at=NULL WHERE task_id=?", (tid,))
                conn.commit()

                row = c.execute("""
                    SELECT title, description, category, points, created_by, created_at, due_date
                    FROM tasks WHERE task_id = ?
                """, (tid,)).fetchone()
                title, description, category, points, created_by, created_at, due_date = row

                embed = Embed(
                    title=f"❌ Задача #{tid} отвязана",
                    description=f"**{title}**\n{description[:1000]}",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                embed.add_field(name="Категория", value=category)
                embed.add_field(name="Баллы", value=points)
                embed.add_field(name="Создана", value=created_at)
                if due_date:
                    embed.add_field(name="Срок выполнения", value=due_date)
                if image_url:
                    embed.set_image(url=image_url)

                message = await interaction.channel.send(embed=embed)
                bot.loop.create_task(delayed_replace(message, create_small_embed(embed)))

                if interaction.message:
                    try:
                        await interaction.response.edit_message(content=f"❌ Задача #{tid} отвязана", embed=None, view=None)
                    except discord.errors.NotFound:
                        logging.warning(f"Сообщение для задачи #{tid} не найдено при попытке редактирования")
                        await interaction.followup.send(f"❌ Задача #{tid} отвязана (исходное сообщение недоступно).", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ Задача #{tid} отвязана", ephemeral=True)
                
                self.parent_view.stop()
        except sqlite3.Error as e:
            logging.error(f"Ошибка базы данных: {e}")
            await interaction.response.send_message("❌ Ошибка при выполнении действия.", ephemeral=True)

# Представление для управления задачами
class TaskManagementView(View):
    def __init__(self, interaction: Interaction):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.state = "select_category"
        self.category = None
        self.current_page = 1
        self.total_pages = 1
        self.selected_task_id = None
        self.add_item(TaskCategorySelect(self))

    async def update_view(self, interaction: Interaction):
        self.clear_items()
        if self.state == "select_category":
            self.add_item(TaskCategorySelect(self))
            await interaction.response.edit_message(content="Выберите категорию задач:", embed=None, view=self)
        elif self.state == "view_tasks":
            offset = (self.current_page - 1) * 25
            if self.category == "available":
                c.execute("SELECT task_id, title FROM tasks WHERE status = 'available' LIMIT 25 OFFSET ?", (offset,))
            elif self.category == "mine":
                c.execute("SELECT task_id, title FROM tasks WHERE (assigned_to = ? OR created_by = ?) AND status IN ('available', 'assigned') LIMIT 25 OFFSET ?", (interaction.user.id, interaction.user.id, offset))
            tasks = c.fetchall()
            if not tasks:
                await interaction.response.edit_message(content=f"Нет задач в категории '{self.category}'.", embed=None, view=None)
                self.stop()
                return
            options = [SelectOption(label=(title or "Без названия")[:100], value=str(tid)) for tid, title in tasks]
            self.add_item(TaskSelect(options, self))
            if self.current_page > 1:
                self.add_item(PreviousButton(self))
            if self.current_page < self.total_pages:
                self.add_item(NextButton(self))
            await interaction.response.edit_message(content=f"Выберите задачу (страница {self.current_page}/{self.total_pages}):", view=self)
        elif self.state == "view_task_details":
            try:
                row = c.execute(
                    "SELECT title, description, category, status, created_by, assigned_to, created_at, accepted_at, completed_at, due_date, points, image_url "
                    "FROM tasks WHERE task_id = ?",
                    (self.selected_task_id,)
                ).fetchone()
                if not row:
                    await interaction.response.edit_message(content="🚫 Задача не найдена", embed=None, view=None)
                    self.stop()
                    return
                title, description, category, status, created_by, assigned_to, created_at, accepted_at, completed_at, due_date, points, image_url = row
                guild = interaction.guild
                created_by_user = guild.get_member(created_by) if guild else bot.get_user(created_by)
                assigned_to_user = guild.get_member(assigned_to) if guild and assigned_to else None
                embed = Embed(title=f"Задача #{self.selected_task_id}: {title}", 
                     description=(description[:1000] if description else "Без описания"), 
                     color=discord.Color.blue())
                embed.add_field(name="Категория", value=(category or "Не указана"))
                embed.add_field(name="Статус", value=status)
                embed.add_field(name="Создал(а)", value=(created_by_user.mention if created_by_user else "Unknown"))
                embed.add_field(name="Принят(а)", value=(assigned_to_user.mention if assigned_to_user else "Не принят"))
                embed.add_field(name="Баллы", value=points)
                if due_date:
                    embed.add_field(name="Срок выполнения", value=due_date)
                timeline = []
                if created_at:
                    timeline.append(f"Создана: {created_at}")
                if accepted_at:
                    timeline.append(f"Принята: {accepted_at}")
                if completed_at:
                    timeline.append(f"Завершена: {completed_at}")
                if timeline:
                    embed.add_field(name="Хронология", value="\n".join(timeline), inline=False)
                if image_url:
                    embed.set_image(url=image_url)
                buttons = []
                if status == 'available':
                    buttons.append(AcceptButton(self))
                elif status == 'assigned' and assigned_to == interaction.user.id:
                    buttons.append(CompleteButton(self))
                if status == 'assigned' and (assigned_to == interaction.user.id or is_officer(interaction.user)):
                    buttons.append(UnassignButton(self))
                for button in buttons:
                    self.add_item(button)
                await interaction.response.edit_message(content=None, embed=embed, view=self)
            except sqlite3.Error as e:
                logging.error(f"Ошибка базы данных: {e}")
                await interaction.response.edit_message(content="❌ Произошла ошибка при получении задачи.", embed=None, view=None)
                self.stop()

# Представление для просмотра всех задач
class AllTasksView(View):
    def __init__(self, interaction: Interaction):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.state = "select_category"
        self.category = None
        self.current_page = 1
        self.total_pages = 1
        self.selected_task_id = None
        self.add_item(AllTasksSelect(self))

    async def update_view(self, interaction: Interaction):
        self.clear_items()
        if self.state == "select_category":
            self.add_item(AllTasksSelect(self))
            await interaction.response.edit_message(content="Выберите категорию задач:", embed=None, view=self)
        elif self.state == "view_tasks":
            offset = (self.current_page - 1) * 25
            if self.category == "active":
                c.execute("SELECT task_id, title FROM tasks WHERE status IN ('available', 'assigned') LIMIT 25 OFFSET ?", (offset,))
            elif self.category == "completed":
                c.execute("SELECT task_id, title FROM tasks WHERE status = 'completed' LIMIT 25 OFFSET ?", (offset,))
            tasks = c.fetchall()
            
            if not tasks:
                await interaction.response.edit_message(content=f"Нет задач в категории '{self.category}'.", embed=None, view=None)
                self.stop()
                return
            options = [SelectOption(label=(f'{title}({tid})' or "Без названия")[:100], value=str(tid)) for tid, title in tasks]
            self.add_item(TaskSelect(options, self))
            if self.current_page > 1:
                self.add_item(PreviousButton(self))
            if self.current_page < self.total_pages:
                self.add_item(NextButton(self))
            await interaction.response.edit_message(content=f"Выберите задачу (страница {self.current_page}/{self.total_pages}):", view=self)
        elif self.state == "view_task_details":
            try:
                row = c.execute(
                    "SELECT title, description, category, status, created_by, assigned_to, created_at, accepted_at, completed_at, due_date, points, image_url "
                    "FROM tasks WHERE task_id = ?",
                    (self.selected_task_id,)
                ).fetchone()
                if not row:
                    await interaction.response.edit_message(content="🚫 Задача не найдена", embed=None, view=None)
                    self.stop()
                    return
                title, description, category, status, created_by, assigned_to, created_at, accepted_at, completed_at, due_date, points, image_url = row
                guild = interaction.guild
                created_by_user = guild.get_member(created_by) if guild else bot.get_user(created_by)
                assigned_to_user = guild.get_member(assigned_to) if guild and assigned_to else None
                embed = Embed(title=f"Задача #{self.selected_task_id}: {title}", 
                     description=(description[:1000] if description else "Без описания"), 
                     color=discord.Color.blue())
                embed.add_field(name="Категория", value=(category or "Не указана"))
                embed.add_field(name="Статус", value=status)
                embed.add_field(name="Создал(а)", value=(created_by_user.mention if created_by_user else "Unknown"))
                embed.add_field(name="Принят(а)", value=(assigned_to_user.mention if assigned_to_user else "Не принят"))
                embed.add_field(name="Баллы", value=points)
                if due_date:
                    embed.add_field(name="Срок выполнения", value=due_date)
                timeline = []
                if created_at:
                    timeline.append(f"Создана: {created_at}")
                if accepted_at:
                    timeline.append(f"Принята: {accepted_at}")
                if completed_at:
                    timeline.append(f"Завершена: {completed_at}")
                if timeline:
                    embed.add_field(name="Хронология", value="\n".join(timeline), inline=False)
                if image_url:
                    embed.set_image(url=image_url)
                buttons = []
                if status == 'assigned' and is_officer(interaction.user):
                    buttons.append(UnassignButton(self))
                if is_officer(interaction.user):
                    buttons.append(DeleteTaskButton(self))
                for button in buttons:
                    self.add_item(button)
                await interaction.response.edit_message(content=None, embed=embed, view=self)
            except sqlite3.Error as e:
                logging.error(f"Ошибка базы данных: {e}")
                await interaction.response.edit_message(content="❌ Произошла ошибка при получении задачи.", embed=None, view=None)
                self.stop()

# Select для выбора категории пресета
class PresetCategorySelect(Select):
    def __init__(self):
        options = [SelectOption(label=cat, value=cat) for cat in CATEGORIES.keys()]
        super().__init__(placeholder="Выберите категорию пресета", options=options, custom_id="preset_cat_select")
    
    async def callback(self, interaction: Interaction):
        category = self.values[0]
        await interaction.response.send_message(
            "Хотите прикрепить изображение к пресету?",
            view=CreatePresetWithImageView(category),
            ephemeral=True
        )

# Представление для выбора категории пресета
class PresetCategoryView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(PresetCategorySelect())

# Select для выбора пресета
class PresetSelect(Select):
    def __init__(self, presets_page, view):
        options = [SelectOption(label=name, value=str(preset_id)) for preset_id, name in presets_page]
        super().__init__(placeholder="Выберите пресет", options=options, custom_id="preset_select")
        self.parent_view = view

    async def callback(self, interaction: Interaction):
        preset_id = int(self.values[0])
        c.execute("SELECT name, title, description, category, due_date, points, image_url FROM presets WHERE preset_id = ?", (preset_id,))
        row = c.fetchone()
        if not row:
            return await interaction.response.send_message("🚫 Пресет не найден.", ephemeral=True)
        name, title, desc, category, due_date, points, image_url = row
        embed = Embed(title=f"Пресет «{name}»", color=discord.Color.blurple())
        embed.add_field(name="Заголовок", value=title, inline=False)
        embed.add_field(name="Описание", value=desc, inline=False)
        embed.add_field(name="Категория", value=category)
        embed.add_field(name="Баллы", value=points)
        embed.add_field(name="Срок выполнения", value=due_date or "не задан")
        if image_url:  # Добавляем изображение, если оно есть
            embed.set_image(url=image_url)
        view = PresetActionView(preset_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# Кнопка навигации для пресетов
class PresetNavButton(Button):
    def __init__(self, label, direction, view):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.direction = direction
        self.parent_view = view

    async def callback(self, interaction: Interaction):
        view: PresetManagementView = self.parent_view
        view.page += self.direction
        await view.update(interaction)

# Представление для управления пресетами
class PresetManagementView(View):
    def __init__(self, *, per_page=25):
        super().__init__(timeout=None)
        c.execute("SELECT preset_id, name FROM presets ORDER BY name")
        self.presets = c.fetchall()
        self.per_page = per_page
        self.page = 0
        self.max_page = (len(self.presets) - 1) // per_page
        self._make_page()

    def _make_page(self):
        self.clear_items()
        start = self.page * self.per_page
        page_presets = self.presets[start : start + self.per_page]
        self.add_item(PresetSelect(page_presets, self))
        if self.page > 0:
            self.add_item(PresetNavButton("⬅️ Назад", -1, self))
        if self.page < self.max_page:
            self.add_item(PresetNavButton("Вперёд ➡️", +1, self))

    async def update(self, interaction: Interaction):
        self._make_page()
        await interaction.response.edit_message(view=self)

# Представление для действий с пресетом
class PresetActionView(View):
    def __init__(self, preset_id):
        super().__init__(timeout=None)
        self.preset_id = preset_id

        # Проверяем текущее состояние repeat_daily
        c.execute("SELECT repeat_daily FROM presets WHERE preset_id = ?", (preset_id,))
        row = c.fetchone()
        is_repeat_enabled = bool(row and row[0])
        
        # Добавляем кнопку повторения с соответствующим текстом и стилем
        btn_label = "Отключить ежедневное повторение" if is_repeat_enabled else "Включить ежедневное повторение"
        btn_style = discord.ButtonStyle.danger if is_repeat_enabled else discord.ButtonStyle.success

    @discord.ui.button(label="Задать пресет", style=discord.ButtonStyle.success)
    async def set_preset(self, interaction: Interaction, button: Button):
        c.execute("SELECT title, description, category, due_date, points, image_url FROM presets WHERE preset_id = ?", (self.preset_id,))
        row = c.fetchone()
        if not row:
            return await interaction.response.send_message("🚫 Пресет не найден.", ephemeral=True)
        title, desc, category, due_date, points, image_url = row
        created_at = datetime.now().isoformat()
        c.execute(
            "INSERT INTO tasks (title, description, category, status, assigned_to, created_by, created_at, due_date, points, image_url) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, desc, category, 'available', None, interaction.user.id, created_at, due_date, points, image_url)
        )
        conn.commit()
        task_id = c.lastrowid
        embed = Embed(
            title=f"✅ Задача #{task_id} создана",
            description=f"**{title}**\n{desc}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Категория", value=category)
        embed.add_field(name="Баллы", value=points)
        if due_date:
            embed.add_field(name="Срок выполнения", value=due_date)
        if image_url:
            embed.set_image(url=image_url)
        embed.set_footer(text=f"Создал(а): {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @discord.ui.button(label="Удалить пресет", style=discord.ButtonStyle.danger)
    async def delete_preset(self, interaction: Interaction, button: Button):
        c.execute("DELETE FROM presets WHERE preset_id = ?", (self.preset_id,))
        conn.commit()
        await interaction.response.send_message("🗑️ Пресет удалён.", ephemeral=True)

    @discord.ui.button(label="Переключить повторение", style=discord.ButtonStyle.secondary)
    async def toggle_repeat(self, interaction: Interaction, button: Button):
        # Получаем текущее состояние
        c.execute("SELECT repeat_daily FROM presets WHERE preset_id = ?", (self.preset_id,))
        row = c.fetchone()
        current_state = bool(row and row[0])
        
        # Меняем состояние на противоположное
        new_state = not current_state
        c.execute("UPDATE presets SET repeat_daily = ? WHERE preset_id = ?", (int(new_state), self.preset_id))
        conn.commit()

        # Обновляем кнопку
        button.label = "Отключить ежедневное повторение" if new_state else "Включить ежедневное повторение"
        button.style = discord.ButtonStyle.danger if new_state else discord.ButtonStyle.success

        # Обновляем сообщение
        await interaction.response.edit_message(view=self)
        
        
class PresetRepeatButton(discord.ui.Button):
    def __init__(self, preset_id):
        c.execute("SELECT repeat_daily FROM presets WHERE preset_id = ?", (preset_id,))
        row = c.fetchone()
        repeat_enabled = bool(row and row[0])
        label = "Отключить ежедневное повторение" if repeat_enabled else "Включить ежедневное повторение"
        style = discord.ButtonStyle.danger if repeat_enabled else discord.ButtonStyle.success
        super().__init__(label=label, style=style, custom_id=f"preset_repeat_toggle_{preset_id}")
        self.preset_id = preset_id

    async def callback(self, interaction: discord.Interaction):
        # Прочитать текущее состояние
        c.execute("SELECT repeat_daily FROM presets WHERE preset_id = ?", (self.preset_id,))
        row = c.fetchone()
        current_state = bool(row and row[0])
        new_state = not current_state
        # Записать новое состояние
        c.execute("UPDATE presets SET repeat_daily = ? WHERE preset_id = ?", (int(new_state), self.preset_id))
        conn.commit()
        # Пересоздать View, чтобы обновить кнопку
        await interaction.response.edit_message(view=PresetActionView(self.preset_id))

class SetPresetButton(discord.ui.Button):
    def __init__(self, preset_id):
        super().__init__(label="Задать пресет", style=discord.ButtonStyle.success, custom_id=f"preset_action_set_{preset_id}")
        self.preset_id = preset_id
    async def callback(self, interaction: discord.Interaction):
        c.execute("SELECT title, description, category, due_date, points, image_url FROM presets WHERE preset_id = ?", (self.preset_id,))
        row = c.fetchone()
        if not row:
            return await interaction.response.send_message("🚫 Пресет не найден.", ephemeral=True)
        title, desc, category, due_date, points, image_url = row
        created_at = datetime.now().isoformat()
        c.execute(
            "INSERT INTO tasks (title, description, category, status, assigned_to, created_by, created_at, due_date, points, image_url) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, desc, category, 'available', None, interaction.user.id, created_at, due_date, points, image_url)
        )
        conn.commit()
        task_id = c.lastrowid
        embed = Embed(
            title=f"✅ Задача #{task_id} создана",
            description=f"**{title}**\n{desc}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Категория", value=category)
        embed.add_field(name="Баллы", value=points)
        if due_date:
            embed.add_field(name="Срок выполнения", value=due_date)
        if image_url:
            embed.set_image(url=image_url)
        embed.set_footer(text=f"Создал(а): {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed, ephemeral=False)

class DeletePresetButton(discord.ui.Button):
    def __init__(self, preset_id):
        super().__init__(label="Удалить пресет", style=discord.ButtonStyle.danger, custom_id=f"preset_action_delete_{preset_id}")
        self.preset_id = preset_id
    async def callback(self, interaction: discord.Interaction):
        c.execute("DELETE FROM presets WHERE preset_id = ?", (self.preset_id,))
        conn.commit()
        await interaction.response.send_message("🗑️ Пресет удалён.", ephemeral=True)

class PresetActionView(discord.ui.View):
    def __init__(self, preset_id):
        super().__init__(timeout=None)
        self.preset_id = preset_id
        self.add_item(PresetRepeatButton(preset_id))
        self.add_item(SetPresetButton(preset_id))
        self.add_item(DeletePresetButton(preset_id))


# Задача для ежедневного добавления повторяющихся пресетов
async def daily_repeat_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now()
        next_run = now.replace(hour=11, minute=0, second=0, microsecond=0)
        if now >= next_run:
            next_run = next_run.replace(day=now.day + 1)
        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        try:
            c.execute("SELECT name, title, description, category, due_date, points, image_url FROM presets WHERE repeat_daily = 1")
            presets = c.fetchall()
            for name, title, desc, category, due_date, points, image_url in presets:
                created_at = datetime.now().isoformat()
                c.execute(
                    "INSERT INTO tasks (title, description, category, status, assigned_to, created_by, created_at, due_date, points, image_url) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (title, desc, category, 'available', None, None, created_at, due_date, points, image_url)
                )
            conn.commit()
            logging.info(f"Added {len(presets)} daily repeated tasks at 11:00 AM.")
        except Exception as e:
            logging.error(f"Ошибка при добавлении ежедневных задач: {e}")
            
            
# Главное меню
class MainMenu(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🆕 Взять новую задачу", style=discord.ButtonStyle.primary, custom_id="get_task_v12", row=0)
    async def get_task_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_message("🔍 Выберите категорию задачи:", view=GetTaskView(), ephemeral=True)

    @discord.ui.button(label="📋 Мои задачи", style=discord.ButtonStyle.secondary, custom_id="manage_tasks_v12", row=0)
    async def manage_tasks_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_message("📂 Выберите категорию задач:", view=TaskManagementView(interaction), ephemeral=True)

    @discord.ui.button(label="✅ Завершить задачу", style=discord.ButtonStyle.success, custom_id="complete_task_v12", row=0)
    async def complete_task_button(self, interaction: Interaction, button: Button):
        try:
            c.execute(
                "SELECT task_id, title FROM tasks WHERE status = 'assigned' AND assigned_to = ?",
                (interaction.user.id,)
            )
            tasks = c.fetchall()
            if not tasks:
                return await interaction.response.send_message("🚫 У вас нет принятых задач.", ephemeral=True)
            options = [SelectOption(label=f"{tid} — {title[:80]}", value=str(tid)) for tid, title in tasks]
            tmp = View()
            tmp.add_item(TaskActionSelect(options, "complete", self))
            await interaction.response.send_message("📋 Выберите задачу для завершения:", view=tmp, ephemeral=True)
        except sqlite3.Error as e:
            logging.error(f"Ошибка БД при получении назначенных задач: {e}")
            await interaction.response.send_message("❌ Не удалось получить ваши задачи.", ephemeral=True)

    @discord.ui.button(label="🏆 Лидерборд", style=discord.ButtonStyle.blurple, custom_id="leaderboard_v2", row=1)
    async def leaderboard_button(self, interaction: Interaction, button: Button):
        try:
            c.execute(
                "SELECT user_id, SUM(points_earned) as total FROM points_log GROUP BY user_id ORDER BY total DESC LIMIT 10"
            )
            leaders = c.fetchall()
            embed = Embed(
                title="🏆 Топ‑10 по баллам",
                description="Смотрите, кто впереди!",
                color=discord.Color.gold()
            )
            if leaders:
                for i, (uid, total) in enumerate(leaders, 1):
                    member = interaction.guild.get_member(uid)
                    name = member.display_name if member else f"User {uid}"
                    embed.add_field(name=f"{i}. {name}", value=f"{total} баллов", inline=False)
            else:
                embed.description = "Пока никто не заработал ни одного балла."
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except sqlite3.Error as e:
            logging.error(f"Ошибка БД при построении лидерборда: {e}")
            await interaction.response.send_message("❌ Не удалось построить лидерборд.", ephemeral=True)

    @discord.ui.button(label="❌ Отказаться от задачи", style=discord.ButtonStyle.danger, custom_id="unassign_task_v12", row=1)
    async def unassign_task_button(self, interaction: Interaction, button: Button):
        try:
            if is_officer(interaction.user):
                c.execute("SELECT task_id, title FROM tasks WHERE status = 'assigned'")
            else:
                c.execute(
                    "SELECT task_id, title FROM tasks WHERE status = 'assigned' AND assigned_to = ?",
                    (interaction.user.id,)
                )
            tasks = c.fetchall()
            if not tasks:
                return await interaction.response.send_message("🚫 Нет задач для отказа.", ephemeral=True)
            options = [SelectOption(label=f"{tid} — {title[:80]}", value=str(tid)) for tid, title in tasks]
            tmp = View()
            tmp.add_item(TaskActionSelect(options, "unassign", self))
            await interaction.response.send_message("📂 Выберите задачу для отказа:", view=tmp, ephemeral=True)
        except sqlite3.Error as e:
            logging.error(f"Ошибка БД при получении назначенных задач: {e}")
            await interaction.response.send_message("❌ Не удалось получить задачи.", ephemeral=True)

    @discord.ui.button(label="⚙️ Меню офицеров", style=discord.ButtonStyle.danger, custom_id="admin_menu_v12", row=2)
    async def admin_menu_button(self, interaction: Interaction, button: Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("🚫 У вас нет прав офицера.", ephemeral=True)
        embed = Embed(
            title="⚙️ Меню офицеров",
            description="Здесь вы можете управлять задачами и шаблонами",
            color=discord.Color.dark_gold()
        )
        await interaction.response.send_message(embed=embed, view=AdminMenu(), ephemeral=True)

# Меню для офицеров
class AdminMenu(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Добавить новую задачу", style=discord.ButtonStyle.secondary, custom_id="create_task_v11")
    async def create_task_button(self, interaction: Interaction, button: Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("🚫 Недостаточно прав.", ephemeral=True)
        await interaction.response.send_message("Выберите категорию:", view=CreateTaskCategoryView(), ephemeral=True)

    @discord.ui.button(label="Посмотреть все задачи", style=discord.ButtonStyle.secondary, custom_id="all_tasks_v11")
    async def all_tasks_button(self, interaction: Interaction, button: Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("🚫 Недостаточно прав.", ephemeral=True)
        await interaction.response.send_message("Выберите категорию задач:", view=AllTasksView(interaction), ephemeral=True)

    @discord.ui.button(label="Управление шаблонами задач", style=discord.ButtonStyle.secondary, custom_id="manage_presets_v12")
    async def manage_presets(self, interaction: Interaction, button: Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("🚫 Недостаточно прав.", ephemeral=True)
        c.execute("SELECT COUNT(*) FROM presets")
        count = c.fetchone()[0]
        if count == 0:
            await interaction.response.send_message("🚫 Нет доступных шаблонов.", ephemeral=True)
        else:
            await interaction.response.send_message("📦 Управление шаблонами: выберите из списка", view=PresetManagementView(), ephemeral=True)

    @discord.ui.button(label="Создать новый шаблон", style=discord.ButtonStyle.primary, custom_id="btn_create_preset")
    async def create_preset(self, interaction: Interaction, button: Button):
        if not is_officer(interaction.user):
            return await interaction.response.send_message("🚫 Недостаточно прав.", ephemeral=True)
        await interaction.response.send_message("📦 Для нового шаблона сначала выберите категорию:", view=PresetCategoryView(), ephemeral=True)

# Основной класс бота
intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True

class TaskBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        self.add_view(MainMenu())
        self.add_view(AdminMenu())
        logging.info("Зарегистрированы представления MainMenu и AdminMenu")

    async def close(self):
        await super().close()
        conn.close()
        logging.info("Соединение с базой данных закрыто")

bot = TaskBot()

@bot.event
async def on_ready():
    logging.info(f"Бот готов как {bot.user} (ID: {bot.user.id})")
    if not hasattr(bot, 'repeat_task_started'):
        bot.repeat_task_started = True
        bot.loop.create_task(daily_repeat_task())
        await setup_passwords_message(bot)

@bot.command(name="menu", aliases=["ьутг"])
async def menu_cmd(ctx: commands.Context):
    await ctx.message.delete() 
    embed = Embed(
        title="📋 Главное меню",
        description="Нажмите одну из кнопок ниже, чтобы начать",
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Панель управления задачами")
    await ctx.send(embed=embed, view=MainMenu(), delete_after=600)
    
@bot.command(name="addpoints")
@commands.check(is_officer)
async def add_points(ctx, member: discord.Member, points: int, *, reason: str = None):
    await ctx.message.delete() 
    timestamp = datetime.now().isoformat()
    c.execute(
        "INSERT INTO points_log (user_id, task_id, points_earned, timestamp) VALUES (?, NULL, ?, ?)",
        (member.id, points, timestamp)
    )
    conn.commit()
    text = f"✅ Офицер {ctx.author.mention} добавил {points} баллов {member.mention}"
    if reason:
        text += f" (причина: {reason})"
    await ctx.send(text)

@bot.command(name="removepoints")
@commands.check(is_officer)
async def remove_points(ctx, member: discord.Member, points: int, *, reason: str = None):
    await ctx.message.delete() 
    timestamp = datetime.now().isoformat()
    c.execute(
        "INSERT INTO points_log (user_id, task_id, points_earned, timestamp) VALUES (?, NULL, ?, ?)",
        (member.id, -abs(points), timestamp)
    )
    conn.commit()
    text = f"⚠️ Офицер {ctx.author.mention} убрал {points} баллов у {member.mention}"
    if reason:
        text += f" (причина: {reason})"
    await ctx.send(text)

@bot.command(name="setpoints")
@commands.check(is_officer)
async def set_points(ctx, member: discord.Member, total: int):
    await ctx.message.delete() 
    c.execute("DELETE FROM points_log WHERE user_id = ?", (member.id,))
    timestamp = datetime.now().isoformat()
    c.execute(
        "INSERT INTO points_log (user_id, task_id, points_earned, timestamp) VALUES (?, NULL, ?, ?)",
        (member.id, total, timestamp)
    )
    conn.commit()
    await ctx.send(f"ℹ️ Офицер {ctx.author.mention} установил {member.mention} ровно **{total}** баллов")

@add_points.error
@remove_points.error
@set_points.error
async def points_cmd_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("🚫 У вас нет прав офицера для этой команды.", delete_after=10)

@bot.command(name="debug_tasks")
async def debug_tasks_cmd(ctx: commands.Context):
    try:
        await ctx.message.delete() 
        c.execute("SELECT task_id, title, status, assigned_to FROM tasks")
        tasks = c.fetchall()
        if not tasks:
            return await ctx.send("Таблица задач пуста.")
        await ctx.send("\n".join([f"ID: {tid}, Title: {title}, Status: {status}, Assigned: {assigned_to}" for tid, title, status, assigned_to in tasks]))
    except sqlite3.Error as e:
        logging.error(f"Ошибка базы данных: {e}")
        await ctx.send("❌ Ошибка при получении задач.")

@bot.command(name="notifyall")
@commands.check(is_officer)
async def notify_all(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(embed=discord.Embed(
        title="📤 Рассылка запущена...",
        description=f"Сообщение: `{message}`\nОтправка может занять некоторое время.",
        color=discord.Color.orange()
    ))
    success = 0
    failed = 0
    for member in ctx.guild.members:
        if member.bot or not is_clan(member):
            continue
        try:
            await member.send(f"📢 **Товарищ {member.name}! Вам пришло оповещение от офицеров**:\n{message}")
            success += 1
            await asyncio.sleep(0.5)
        except:
            failed += 1
    await ctx.send(embed=discord.Embed(
        title="✅ Рассылка завершена",
        description=f"Успешно: `{success}`\nНе доставлено: `{failed}` (возможно, ЛС отключены)",
        color=discord.Color.green()
    ))

@bot.command(name="rollcall")
@commands.check(is_officer)
async def rollcall(ctx, count: int = 3, *, role_input: str = None):
    await ctx.message.delete()

    members = [m for m in ctx.guild.members if is_clan(m) and not m.bot and m.status != discord.Status.offline]

    role = None
    if role_input:
        role_input = role_input.strip()
        # Проверяем, передали ли упоминание роли вида <@&ID>
        match = re.match(r"<@&(\d+)>", role_input)
        if match:
            role_id = int(match.group(1))
            role = ctx.guild.get_role(role_id)
        else:
            # Если не упоминание, ищем по имени
            role = discord.utils.find(lambda r: r.name.lower() == role_input.lower(), ctx.guild.roles)

        if not role:
            await ctx.send(f"🚫 Роль `{role_input}` не найдена.", delete_after=10)
            return

        members = [m for m in members if role in m.roles]

    if not members:
        await ctx.send("🚫 Нет доступных участников для выбора.")
        return

    if count > len(members):
        await ctx.send(f"⚠️ Запрошено {count}, но доступно только {len(members)} участников. Выберу всех.")
        count = len(members)

    chosen = random.sample(members, count)
    mentions_list = "\n".join(f"{i+1}. {member.mention}" for i, member in enumerate(chosen))
    embed = Embed(
        title=f"🎲 Rollcall — выбранные участники ({role.name if role else 'Все'})",
        description=mentions_list,
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"Запрос от {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=embed)

@rollcall.error
async def rollcall_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("🚫 У вас нет прав офицера для этой команды.", delete_after=10)
    elif isinstance(error, commands.BadArgument):
        await ctx.send("🚫 Некорректный аргумент. Используйте: `!rollcall [число]`", delete_after=10)
    else:
        await ctx.send("❌ Произошла ошибка при выполнении команды.", delete_after=10)
        logging.error(f"Ошибка в команде rollcall: {error}")


@bot.command(name="verify", aliases=["верифицировать"])
@commands.check(is_officer)
async def verify(ctx):
    await ctx.message.delete()
    if not ctx.message.mentions:
        await ctx.send("❌ Укажи пользователя через @", delete_after=5)
        return

    member = ctx.message.mentions[0]
    recruit_role = discord.utils.get(ctx.guild.roles, name="Рекрут")

    # Проверка: уже ли есть роль верифицированного
    if recruit_role in member.roles:
        await ctx.send("⚠️ Участник уже верифицирован (роль 'Рекрут' уже выдана).", delete_after=10)
        return

    prefix = "[Arct] "
    suffix = " (*Имя*)"  # 7 символов с пробелом

    # Максимально допустимая длина никнейма Discord
    max_length = 32

    # Вычисляем максимальную длину пользовательской части
    max_nick_length = max_length - len(prefix) - len(suffix)

    # Обрезаем ник, если он слишком длинный
    trimmed_nick = nickname[:max_nick_length] if len(nickname) > max_nick_length else nickname

    new_nick = f"{prefix}{trimmed_nick}{suffix}"

    try:
        await member.edit(nick=new_nick)
    except discord.Forbidden:
        logging.warning(f"Не удалось изменить ник для {member.id}")
    except discord.HTTPException as e:
        logging.error(f"Ошибка при установке ника для {member.id}: {e}")

    # Выдача ролей
    role_names = ["Рекрут"]
    given_roles = []
    for role_name in role_names:
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if role and role not in member.roles:
            await member.add_roles(role)
            given_roles.append(role.name)

    # Отправка эмбеда
    embed = discord.Embed(
        title="✅ Участник верифицирован",
        description=f"{member.mention} был верифицирован {ctx.author.mention}",
        color=discord.Color.green()
    )
    embed.add_field(name="Ник", value=new_nick, inline=False)
    if given_roles:
        embed.add_field(name="Выданные роли", value=", ".join(given_roles), inline=False)

    log_channel = discord.utils.get(ctx.guild.text_channels, name="log")
    if log_channel:
        await log_channel.send(embed=embed)
    await ctx.send(embed=embed, delete_after=10)


@bot.command(name="export_passwords")
@commands.check(is_officer)
async def export_passwords(ctx):
    p.execute('SELECT code, location, description, author, created_at FROM foxhole_passwords ORDER BY created_at DESC')
    rows = p.fetchall()

    if not rows:
        await ctx.send("📭 Пока нет паролей для экспорта.")
        return

    # Задаём ширину для каждой колонки
    widths = {
        "code": 8,
        "location": 15,
        "description": 30,
        "author": 15,
        "created_at": 20
    }

    # Заголовки таблицы
    header = (
        "Код".ljust(widths["code"]) + " | " +
        "Локация".ljust(widths["location"]) + " | " +
        "Название".ljust(widths["description"]) + " | " +
        "Добавил".ljust(widths["author"]) + " | " +
        "Дата".ljust(widths["created_at"]) + "\n"
    )

    separator = "-" * (sum(widths.values()) + 4 * 3 + 1) + "\n"  # Разделитель под шапкой
    file_content = header + separator

    for code, location, description, author, created_at in rows:
        file_content += (
            str(code).ljust(widths["code"]) + " | " +
            str(location).ljust(widths["location"]) + " | " +
            (description or "Без названия").ljust(widths["description"]) + " | " +
            str(author).ljust(widths["author"]) + " | " +
            str(created_at).ljust(widths["created_at"]) + "\n"
        )

    file = discord.File(io.StringIO(file_content), filename="passwords.txt")
    await ctx.send("📄 Вот файл со всеми паролями:", file=file)


@bot.command(name="help", aliases=["commands"])
async def help_cmd(ctx: commands.Context):
    await ctx.message.delete() 
    is_user_officer = is_officer(ctx.author)
    embed = Embed(
        title="📖 Список команд",
        description="Вот доступные команды бота:",
        color=discord.Color.green()
    )
    embed.add_field(name="📋 !menu", value="Открыть главное меню с кнопками", inline=False)
    embed.add_field(name="ℹ️ !help / !commands", value="Показать это сообщение", inline=False)
    if is_user_officer:
        embed.add_field(
            name="🎖️ Офицерские команды",
            value=(
                "**`!addpoints @пользователь [баллы] [причина]`** – добавить баллы\n"
                "**`!removepoints @пользователь [баллы] [причина]`** – снять баллы\n"
                "**`!setpoints @пользователь [итог]`** – установить точное число баллов\n"
                "**`!notifyall [текст]`** – отправить личное сообщение всем участникам\n"
                "**`!rollcall [число(не обязательно)] [имя роли(не обязательно)]`** – случайный выбор участников\n"
                "**`!verify/верифицировать @пользователь`** – верифицировать пользователя\n"
                "**`!export_passwords`** – получить файл со всеми паролями складов\n"
            ),
            inline=False
        )
    await ctx.send(embed=embed)

@bot.event
async def on_message(message):
    now = datetime.utcnow()

    # ✅ Если пользователь сейчас подаёт скриншот — не удаляем сообщение
    user_deadline = pending_applicants.get(message.author.id)
    if user_deadline and now < user_deadline:
        await bot.process_commands(message)
        return

    # 🎯 Стандартная проверка канала и удаления
    if isinstance(message.channel, discord.TextChannel):
        if message.channel.name == "〚📨〛подать-заявление" and not message.author.bot:
            try:
                await asyncio.sleep(1)
                await message.delete()
            except discord.Forbidden:
                logging.warning("Недостаточно прав для удаления сообщения.")
            except discord.HTTPException as e:
                logging.error(f"Ошибка при удалении сообщения: {e}")

    await bot.process_commands(message)



@bot.event
async def on_member_join(member):
    try:
        role_name = ["Не верифицирован"]
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if role and role not in member.roles:
            await member.add_roles(role)
        dm_message = (
            f"Привет, {member.name}!\n\n"
            "Добро пожаловать на сервер **Arct**!\n"
            "Пожалуйста оставте заявку по форме в https://discord.com/channels/1377967613124280363/1402684607035478158, чтобы получить роли и доступ к каналам."
        )
        await member.send(dm_message)
    except discord.Forbidden:
        pass


# В основном файле запуска:


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    setup_application(bot)    # Регистрируем события, вьюхи и обработчики
    setup_passwords(bot)      # Если есть еще какие-то setup

    bot.run(TOKEN)            # Запускаем бота
