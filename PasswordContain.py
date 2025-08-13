import discord
from discord.ext import commands
from discord.ui import View, Modal, TextInput, Button, Select
from discord import Interaction, Embed, SelectOption
from datetime import datetime
import logging
import sqlite3
import uuid

# Название канала
PASSWORDS_CHANNEL_NAME = "кладовщик-log"

def is_officer(user) -> bool:
    if hasattr(user, "author"):
        user = user.author
    elif hasattr(user, "user"):
        user = user.user
    return any(role.name in ['Лейтенант', 'Офицер', 'Капитан', 'Лидер', 'Генерал','Ветеран'] for role in getattr(user, "roles", []))

def is_logi(user) -> bool:
    if hasattr(user, "author"):
        user = user.author
    elif hasattr(user, "user"):
        user = user.user
    return any(role.name in ['Капитан', 'Лидер', 'Генерал','Ветеран','Логист'] for role in getattr(user, "roles", []))

# Подключение к БД
conn = sqlite3.connect('foxhole_passwords.db')
c = conn.cursor()

# ======================== МОДАЛКА СОЗДАНИЯ ПАРОЛЯ ========================
class CreatePasswordModal(Modal):
    def __init__(self, is_officer_user: bool):
        super().__init__(title="🛠 Добавить пароль склада")

        self.code = TextInput(label="Код", placeholder="Например: 090518", max_length=6)
        self.hex = TextInput(label="Гекс", placeholder="Например: Weathered Expanse", max_length=100)
        self.city = TextInput(label="Город", placeholder="Например: Foxcatcher", max_length=100)
        self.description = TextInput(label="Название склада", placeholder="Название", max_length=100)

        self.is_officer_user = is_officer_user
        if is_officer_user:
            self.important_field = TextInput(
                label="Важный склад? (да/нет)",
                placeholder="да или нет",
                required=False,
                max_length=3
            )
            self.add_item(self.important_field)

        self.add_item(self.code)
        self.add_item(self.hex)
        self.add_item(self.city)
        self.add_item(self.description)

    async def on_submit(self, interaction: Interaction):
        entry_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        important_value = 0
        if self.is_officer_user and hasattr(self, "important_field"):
            if self.important_field.value.lower().strip() in ["да", "yes", "y", "1"]:
                important_value = 1

        c.execute('''
            INSERT INTO foxhole_passwords (id, code, author, hex, city, description, important, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            entry_id,
            self.code.value,
            str(interaction.user),
            self.hex.value,
            self.city.value,
            self.description.value or "",
            important_value,
            now
        ))
        conn.commit()

        embed = Embed(
            title="✅ Пароль добавлен",
            description=f"**Код:** {self.code.value}\n**Гекс:** {self.hex.value}\n**Город:** {self.city.value}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        if self.description.value:
            embed.add_field(name="Название", value=self.description.value, inline=False)
        if important_value:
            embed.add_field(name="Статус", value="🛑 ВАЖНЫЙ", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ======================== ВЫБОР ГЕКСОВ ========================
class HexSelectView(View):
    def __init__(self):
        super().__init__(timeout=300)
        c.execute("SELECT DISTINCT hex FROM foxhole_passwords ORDER BY hex ASC")
        hexes = [row[0] for row in c.fetchall() if row[0]]

        if not hexes:
            options = [SelectOption(label="Нет данных", value="none")]
        else:
            options = [SelectOption(label=h, value=h) for h in hexes]

        select = Select(
            placeholder="Выбери гекс",
            options=options,
            custom_id="select_hex"
        )
        select.callback = self.select_hex
        self.add_item(select)

    async def select_hex(self, interaction: Interaction):
        chosen_hex = interaction.data["values"][0]

        if chosen_hex == "none":
            await interaction.response.send_message("Нет доступных гексов.", ephemeral=True)
            return

        c.execute("SELECT DISTINCT city FROM foxhole_passwords WHERE hex = ? ORDER BY city ASC", (chosen_hex,))
        cities = [row[0] for row in c.fetchall() if row[0]]

        if not cities:
            await interaction.response.send_message("📭 В этом гексе нет городов с паролями.", ephemeral=True)
            return

        view = CitySelectView(chosen_hex, cities)
        await interaction.response.send_message(f"Выбери город в гексе **{chosen_hex}**:", view=view, ephemeral=True)

# ======================== ВЫБОР ГОРОДА ========================
class CitySelectView(View):
    def __init__(self, hex_name, cities):
        super().__init__(timeout=300)
        self.hex_name = hex_name

        cities = [city for city in cities if city]

        if not cities:
            options = [SelectOption(label="Нет городов", value="none")]
        else:
            options = [SelectOption(label=city, value=city) for city in cities]

        select = Select(
            placeholder="Выбери город",
            options=options,
            custom_id="select_city"
        )
        select.callback = self.select_city
        self.add_item(select)

    async def select_city(self, interaction: Interaction):
        chosen_city = interaction.data["values"][0]

        if chosen_city == "none":
            await interaction.response.send_message("Нет доступных городов.", ephemeral=True)
            return

        # Фильтруем выборку в зависимости от роли
        if is_logi(interaction.user):
            c.execute(
                "SELECT code, description, author, important, created_at FROM foxhole_passwords "
                "WHERE hex = ? AND city = ? ORDER BY created_at DESC",
                (self.hex_name, chosen_city)
            )
        else:
            c.execute(
                "SELECT code, description, author, important, created_at FROM foxhole_passwords "
                "WHERE hex = ? AND city = ? AND important = 0 ORDER BY created_at DESC",
                (self.hex_name, chosen_city)
            )

        rows = c.fetchall()
        if not rows:
            await interaction.response.send_message("📭 В этом городе нет складов.", ephemeral=True)
            return

        embed = Embed(
            title=f"📦 Склады в гексе {self.hex_name}, городе {chosen_city}",
            color=discord.Color.blurple()
        )

        for code, desc, author, important, created in rows:
            display_name = f"{code}"
            if important and is_officer(interaction.user):
                display_name = f"🛑 {display_name}"
            embed.add_field(
                name=display_name,
                value=f"{desc or 'Без названия'}\nДобавил: {author}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)



# ======================== УДАЛЕНИЕ: ВЫБОР ГЕКСА ========================
class DeleteHexSelectView(View):
    def __init__(self):
        super().__init__(timeout=300)
        c.execute("SELECT DISTINCT hex FROM foxhole_passwords ORDER BY hex ASC")
        hexes = [row[0] for row in c.fetchall() if row[0]]

        if not hexes:
            options = [SelectOption(label="Нет данных", value="none")]
        else:
            options = [SelectOption(label=h, value=h) for h in hexes]

        select = Select(
            placeholder="Выбери гекс для удаления",
            options=options,
            custom_id="delete_select_hex"
        )
        select.callback = self.select_hex
        self.add_item(select)

    async def select_hex(self, interaction: Interaction):
        if not is_officer(interaction.user):
            await interaction.response.send_message("⛔ У тебя нет прав удалять пароли.", ephemeral=True)
            return

        chosen_hex = interaction.data["values"][0]

        if chosen_hex == "none":
            await interaction.response.send_message("Нет доступных гексов для удаления.", ephemeral=True)
            return

        c.execute("SELECT DISTINCT city FROM foxhole_passwords WHERE hex = ? ORDER BY city ASC", (chosen_hex,))
        cities = [row[0] for row in c.fetchall() if row[0]]

        if not cities:
            await interaction.response.send_message("📭 В этом гексе нет городов с паролями для удаления.", ephemeral=True)
            return

        view = DeleteCitySelectView(chosen_hex, cities)
        await interaction.response.send_message(f"Выбери город в гексе **{chosen_hex}** для удаления:", view=view, ephemeral=True)

# ======================== УДАЛЕНИЕ: ВЫБОР ГОРОДА ========================
class DeleteCitySelectView(View):
    def __init__(self, hex_name, cities):
        super().__init__(timeout=300)
        self.hex_name = hex_name

        cities = [city for city in cities if city]

        if not cities:
            options = [SelectOption(label="Нет городов", value="none")]
        else:
            options = [SelectOption(label=city, value=city) for city in cities]

        select = Select(
            placeholder="Выбери город для удаления",
            options=options,
            custom_id="delete_select_city"
        )
        select.callback = self.select_city
        self.add_item(select)

    async def select_city(self, interaction: Interaction):
        if not is_officer(interaction.user):
            await interaction.response.send_message("⛔ У тебя нет прав удалять пароли.", ephemeral=True)
            return

        chosen_city = interaction.data["values"][0]

        if chosen_city == "none":
            await interaction.response.send_message("Нет доступных городов для удаления.", ephemeral=True)
            return

        c.execute(
            "SELECT id, code, description FROM foxhole_passwords WHERE hex = ? AND city = ? ORDER BY created_at DESC",
            (self.hex_name, chosen_city)
        )
        rows = c.fetchall()
        if not rows:
            await interaction.response.send_message("📭 В этом городе нет паролей для удаления.", ephemeral=True)
            return

        options = []
        for row in rows:
            pid, code, desc = row
            label = f"{code} — {desc or 'Без названия'}"
            if len(label) > 100:
                label = label[:97] + "..."
            options.append(SelectOption(label=label, value=pid))

        if not options:
            options = [SelectOption(label="Нет паролей для удаления", value="none")]

        view = DeletePasswordSelectView(self.hex_name, chosen_city, options)
        await interaction.response.send_message(f"Выбери пароль для удаления в гексе **{self.hex_name}**, городе **{chosen_city}**:", view=view, ephemeral=True)

# ======================== УДАЛЕНИЕ: ВЫБОР ПАРОЛЯ ========================
class DeletePasswordSelectView(View):
    def __init__(self, hex_name, city_name, options):
        super().__init__(timeout=300)
        self.hex_name = hex_name
        self.city_name = city_name

        if not options:
            options = [SelectOption(label="Нет паролей", value="none")]

        select = Select(
            placeholder="Выбери пароль для удаления",
            options=options,
            custom_id="delete_select_password"
        )
        select.callback = self.delete_password
        self.add_item(select)

    async def delete_password(self, interaction: Interaction):
        if not is_officer(interaction.user):
            await interaction.response.send_message("⛔ У тебя нет прав удалять пароли.", ephemeral=True)
            return

        password_id = interaction.data["values"][0]
        if password_id == "none":
            await interaction.response.send_message("Нет пароля для удаления.", ephemeral=True)
            return

        c.execute("SELECT code FROM foxhole_passwords WHERE id = ?", (password_id,))
        row = c.fetchone()
        if not row:
            await interaction.response.send_message("❌ Этот пароль уже удалён или не найден.", ephemeral=True)
            return

        c.execute("DELETE FROM foxhole_passwords WHERE id = ?", (password_id,))
        conn.commit()

        await interaction.response.send_message(
            f"✅ Пароль с кодом **{row[0]}** из гекса **{self.hex_name}**, города **{self.city_name}** удалён.",
            ephemeral=True
        )

# ======================== ВЬЮ КНОПОК ========================
class PasswordsView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Добавить пароль", style=discord.ButtonStyle.primary, custom_id="add_password")
    async def add_password(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(CreatePasswordModal(is_officer(interaction.user)))


    @discord.ui.button(label="🔍 Поиск паролей", style=discord.ButtonStyle.secondary, custom_id="search_passwords")
    async def search_passwords(self, interaction: Interaction, button: Button):
        c.execute("SELECT COUNT(*) FROM foxhole_passwords")
        if c.fetchone()[0] == 0:
            await interaction.response.send_message("📭 Пока нет паролей.", ephemeral=True)
            return
        await interaction.response.send_message("Выбери гекс:", view=HexSelectView(), ephemeral=True)

    @discord.ui.button(label="❌ Удалить пароль", style=discord.ButtonStyle.danger, custom_id="delete_password")
    async def delete_password(self, interaction: Interaction, button: Button):
        c.execute("SELECT COUNT(*) FROM foxhole_passwords")
        if c.fetchone()[0] == 0:
            await interaction.response.send_message("📭 Нет паролей для удаления.", ephemeral=True)
            return
        await interaction.response.send_message("Выбери гекс для удаления пароля:", view=DeleteHexSelectView(), ephemeral=True)

# ======================== ФУНКЦИЯ ДЛЯ ИНИЦИАЛИЗАЦИИ ========================
async def setup_passwords_message(bot: commands.Bot, channel_name=PASSWORDS_CHANNEL_NAME):
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name)
    if not channel:
        print(f"Канал '{channel_name}' не найден.")
        return

    async for message in channel.history(limit=50):
        if message.author == bot.user:
            await message.delete()

    embed = Embed(
        title="🔐 Управление паролями складов",
        description="Используй кнопки ниже, чтобы добавлять, искать и удалять пароли от складов.\n\n"
                    "🔍 **Поиск паролей** — выбор гекса и города и просмотр складов.\n"
                    "➕ **Добавить пароль** — добавление нового пароля.\n"
                    "❌ **Удалить пароль** — выбор пароля для удаления.",
        color=discord.Color.dark_gold()
    )
    await channel.send(embed=embed, view=PasswordsView())

def setup_passwords(bot):
    @bot.event
    async def on_ready():
        logging.info(f"Бот готов как {bot.user} (ID: {bot.user.id})")
        await setup_passwords_message(bot)
        bot.add_view(PasswordsView())
        logging.info("Зарегистрировано представление PasswordView")
        
if __name__ == "__main__":
    logging.error("Этот файл должен быть импортирован в PykeBOT.py, а не запущен напрямую.")