import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
from discord import Interaction, Embed
from datetime import datetime, timedelta
import sqlite3
import logging
import uuid
import asyncio
import re

# Названия каналов
PING_ROLE_NAME = "🦆 ГУСЬ"
PING_ROLE_CHANNEL_NAME = "〚👨‍👧‍👦〛выдача-ролей"
APPLICATION_CHANNEL_NAME = "〚📩〛приём-заявок"
SUBMIT_APPLICATION_CHANNEL_NAME = "〚📨〛подать-заявление"
LOG_CHANNEL_NAME = "log"

# Глобальный словарь: ID пользователя → дедлайн ожидания скриншота
pending_applicants = {}

# Настройка логирования
logging.basicConfig(level=logging.INFO)

conn = sqlite3.connect('applications.db')
c = conn.cursor()

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

# Создание таблицы для заявок
c.execute('''
    CREATE TABLE IF NOT EXISTS applications (
        application_id TEXT PRIMARY KEY,
        user_id INTEGER,
        application_type TEXT,
        nickname TEXT,
        age TEXT,
        experience TEXT,
        motivation TEXT,
        image_url TEXT,
        status TEXT,
        submitted_at TEXT,
        processed_at TEXT,
        processed_by INTEGER,
        source TEXT,
        clan_tag TEXT,
        second_image_url TEXT
    )
''')
safe_add_column("applications", "image_url", "TEXT")
safe_add_column("applications", "source", "TEXT")
safe_add_column("applications", "clan_tag", "TEXT")
safe_add_column("applications", "second_image_url", "TEXT")
conn.commit()

class ApplicationModal(Modal):
    def __init__(self, application_type: str, image_urls: list = None):
        super().__init__(title=f"Заявка на {application_type}")
        self.application_type = application_type
        self.image_urls = image_urls or []

        if application_type == "Участник клана":
            self.nickname = TextInput(
                label="Игровой никнейм",
                placeholder="Ваш ник в игре (например, МОСКВА)",
                required=True,
                max_length=50
            )
            self.age = TextInput(
                label="Возраст",
                placeholder="Ваш возраст (например, 19)",
                required=True,
                max_length=3
            )
            self.experience = TextInput(
                label="Количество часов в игре",
                placeholder="Сколько у вас часов в игре? (например, 150 часов)",
                required=True,
                max_length=100
            )
            self.motivation = TextInput(
                label="Цель вступления",
                placeholder="Почему вы хотите присоединиться? (например, хочу кататься на узколинейке 10 часов подряд)",
                style=discord.TextStyle.long,
                required=True,
                max_length=1000
            )
            self.source = TextInput(
                label="Как узнали о клане",
                placeholder="Например: табличка, ник человека, сообщение в чате",
                required=True,
                max_length=200
            )
            self.add_item(self.nickname)
            self.add_item(self.age)
            self.add_item(self.experience)
            self.add_item(self.motivation)
            self.add_item(self.source)
        else:  # Союзник
            self.clan_tag = TextInput(
                label="Тег вашего клана",
                placeholder="Введите тег вашего клана",
                required=True,
                max_length=50
            )
            self.nickname = TextInput(
                label="Ваше имя",
                placeholder="Ваше имя в игре",
                required=True,
                max_length=100
            )
            self.add_item(self.clan_tag)
            self.add_item(self.nickname)

    async def on_submit(self, interaction: Interaction):
        try:
            application_id = str(uuid.uuid4())
            submitted_at = datetime.now().isoformat()
            image_url = self.image_urls[0] if self.image_urls else None
            second_image_url = self.image_urls[1] if len(self.image_urls) > 1 else None

            # Сохраняем данные в зависимости от типа заявки
            if self.application_type == "Участник клана":
                c.execute(
                    '''INSERT INTO applications (application_id, user_id, application_type, nickname, age, experience, motivation, image_url, status, submitted_at, source, second_image_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (application_id, interaction.user.id, self.application_type, self.nickname.value,
                     self.age.value, self.experience.value, self.motivation.value, image_url, 'pending', submitted_at, self.source.value, second_image_url)
                )
            else:  # Союзник
                c.execute(
                    '''INSERT INTO applications (application_id, user_id, application_type, nickname, image_url, second_image_url, status, submitted_at, clan_tag)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (application_id, interaction.user.id, self.application_type, self.nickname.value,
                     image_url, second_image_url, 'pending', submitted_at, self.clan_tag.value)
                )
            conn.commit()

            # Создаем основной эмбед
            embed = Embed(
                title=f"📝 Новая заявка на {self.application_type} от {interaction.user.display_name}",
                description=f"**ID заявки:** {application_id}\n**Пользователь:** {interaction.user.mention}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            if self.application_type == "Участник клана":
                embed.add_field(name="Никнейм", value=self.nickname.value, inline=False)
                embed.add_field(name="Возраст", value=self.age.value, inline=True)
                embed.add_field(name="Тип заявки", value=self.application_type, inline=True)
                embed.add_field(name="Игровой опыт", value=self.experience.value[:1000], inline=False)
                embed.add_field(name="Цель", value=self.motivation.value[:1000], inline=False)
                embed.add_field(name="Как узнали о клане", value=self.source.value, inline=False)
            else:
                embed.add_field(name="Тег клана", value=self.clan_tag.value, inline=False)
                embed.add_field(name="Имя", value=self.nickname.value, inline=False)
                embed.add_field(name="Тип заявки", value=self.application_type, inline=True)
            if image_url:
                embed.set_image(url=image_url)
            embed.set_footer(text=f"Подана: {submitted_at}")

            # Создаем второй эмбед для второго скриншота
            embeds = [embed]
            if second_image_url:
                second_embed = Embed(color=discord.Color.blue())
                second_embed.set_image(url=second_image_url)
                second_embed.set_footer(text="Второй скриншот")
                embeds.append(second_embed)

            # Ищем канал для заявок по имени
            application_channel_name = APPLICATION_CHANNEL_NAME  # Замените на нужное имя каналавфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвфвф
            application_channel = discord.utils.get(interaction.guild.text_channels, name=application_channel_name)
            if not application_channel:
                logging.error(f"Канал '{application_channel_name}' не найден.")
                await interaction.response.send_message(f"❌ Канал '{application_channel_name}' не найден.", ephemeral=True, delete_after=10)
                return

            view = ApplicationActionView()
            await application_channel.send(embeds=embeds, view=view)
            await interaction.response.send_message(f"✅ Заявка на {self.application_type} успешно подана!", ephemeral=True, delete_after=10)

        except sqlite3.Error as e:
            logging.error(f"Ошибка базы данных при подаче заявки: {e}")
            await interaction.response.send_message("❌ Ошибка при подаче заявки.", ephemeral=True, delete_after=10)

class ApplicationWithImageView(View):
    def __init__(self, application_type: str, bot):
        super().__init__(timeout=300)
        self.application_type = application_type
        self.bot = bot
        self.image_urls = []

    async def delete_old_ephemeral(self, interaction: Interaction):
        try:
            async for message in interaction.channel.history(limit=50):
                if message.author == self.bot.user and message.is_system() and message.flags.ephemeral:
                    try:
                        await message.delete()
                    except discord.errors.NotFound:
                        logging.info("Old ephemeral message already deleted.")
        except Exception as e:
            logging.error(f"Error deleting old ephemeral messages: {e}")

    @discord.ui.button(label="📎 Прикрепить скриншоты", style=discord.ButtonStyle.primary)
    async def attach_image(self, interaction: Interaction, button: Button):
        await self.delete_old_ephemeral(interaction)
        # ✅ Добавляем пользователя в список ожидающих скриншот
        pending_applicants[interaction.user.id] = datetime.utcnow() + timedelta(seconds=60)

        await interaction.response.send_message(
            "📎 Пришлите два скриншота (**F1** и **главное меню**) в **одном сообщении**.",
            ephemeral=True
        )

        def check(m):
            return m.author == interaction.user and m.attachments and isinstance(m.channel, discord.TextChannel)

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            attachments = msg.attachments

            if len(attachments) < 2:
                followup_msg = await interaction.followup.send(
                    "❌ Для заявки требуется **два скриншота** (F1 и главное меню), отправленные **в одном сообщении**.",
                    ephemeral=True
                )
                await asyncio.sleep(20)
                await followup_msg.delete()
                # ❌ Удаляем пользователя из списка — больше не ждём скриншот
                pending_applicants.pop(interaction.user.id, None)

                return

            # Проверка типа вложений
            valid_attachments = []
            for att in attachments[:2]:
                if att.content_type and att.content_type.startswith('image/'):
                    valid_attachments.append(att)
                else:
                    await self.delete_old_ephemeral(interaction)
                    followup_msg = await interaction.followup.send(
                        f"❌ Файл `{att.filename}` не является изображением.",
                        ephemeral=True
                    )
                    await asyncio.sleep(20)
                    await followup_msg.delete()
                    # ❌ Удаляем пользователя из списка — больше не ждём скриншот
                    pending_applicants.pop(interaction.user.id, None)

                    return

            log_channel = discord.utils.get(msg.guild.text_channels, name="log")
            if not log_channel:
                await self.delete_old_ephemeral(interaction)
                followup_msg = await interaction.followup.send("❌ Канал `log` не найден.", ephemeral=True)
                await asyncio.sleep(20)
                await followup_msg.delete()
                pending_applicants.pop(interaction.user.id, None)
                return

            # Сначала загружаем изображения в оперативную память
            files = []
            for att in valid_attachments:
                try:
                    file = await att.to_file()
                    files.append(file)
                except Exception as e:
                    logging.error(f"Не удалось загрузить файл: {att.filename} — {e}")
                    await self.delete_old_ephemeral(interaction)
                    followup_msg = await interaction.followup.send(
                        f"❌ Не удалось загрузить файл `{att.filename}`. Попробуйте ещё раз.",
                        ephemeral=True
                    )
                    await asyncio.sleep(20)
                    await followup_msg.delete()
                    pending_applicants.pop(interaction.user.id, None)
                    return

            # Отправляем в лог
            log_message = await log_channel.send(
                f"📎 Скриншоты для заявки от {interaction.user.mention}",
                files=files
            )

            # Получаем URL и только потом удаляем сообщение
            self.image_urls = [a.url for a in log_message.attachments[:2]]

            try:
                await msg.delete()
            except discord.errors.NotFound:
                logging.info("Сообщение с вложением уже удалено.")


            try:
                await interaction.message.delete()
            except discord.errors.NotFound:
                logging.info("Сообщение взаимодействия уже удалено.")

            # Показываем модальное окно
            modal = ApplicationModal(self.application_type, self.image_urls)
            await self.delete_old_ephemeral(interaction)
            pending_applicants.pop(interaction.user.id, None)
            await interaction.followup.send(
                "📝 Заполните данные заявки:",
                view=ModalView(modal),
                ephemeral=True
            )

        except asyncio.TimeoutError:
            await self.delete_old_ephemeral(interaction)
            followup_msg = await interaction.followup.send(
                "⏰ Время ожидания скриншотов истекло.",
                ephemeral=True
            )
            await asyncio.sleep(20)
            await followup_msg.delete()
            pending_applicants.pop(interaction.user.id, None)
        except Exception as e:
            logging.error(f"Ошибка при обработке скриншотов: {e}")
            await self.delete_old_ephemeral(interaction)
            followup_msg = await interaction.followup.send(
                "❌ Произошла ошибка при обработке скриншотов.",
                ephemeral=True
            )
            await asyncio.sleep(20)
            await followup_msg.delete()
            pending_applicants.pop(interaction.user.id, None)


class ModalView(View):
    def __init__(self, modal):
        super().__init__()
        self.modal = modal

    @discord.ui.button(label="Заполнить данные", style=discord.ButtonStyle.primary)
    async def show_modal(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(self.modal)

class ApplicationView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Подать заявку на участника клана", style=discord.ButtonStyle.primary, custom_id="apply_clan_member")
    async def clan_member_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_message(
            "Необходимо прикрепить два скриншота (F1 и главное меню, где кнопка 'Высадка') к заявке",
            view=ApplicationWithImageView("Участник клана", interaction.client),
            ephemeral=True
        )

    @discord.ui.button(label="Подать заявку на союзника", style=discord.ButtonStyle.secondary, custom_id="apply_ally")
    async def ally_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_message(
            "Необходимо прикрепить два скриншота (F1 и главное меню, где кнопка 'Высадка') к заявке",
            view=ApplicationWithImageView("Союзник", interaction.client),
            ephemeral=True
        )

class ApplicationActionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    async def delete_old_ephemeral(self, interaction: Interaction):
        """Delete previous ephemeral messages in the same channel for the user."""
        try:
            async for message in interaction.channel.history(limit=50):
                if message.author == interaction.client.user and message.is_system() and message.flags.ephemeral:
                    try:
                        await message.delete()
                    except discord.errors.NotFound:
                        logging.info("Old ephemeral message already deleted.")
        except Exception as e:
            logging.error(f"Error deleting old ephemeral messages: {e}")

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="accept_application")
    async def accept_button(self, interaction: Interaction, button: Button):
        from PykeBOT import is_officer
        if not is_officer(interaction.user):
            await interaction.response.send_message("🚫 У вас нет прав офицера.", ephemeral=True, delete_after=10)
            return

        try:
            # Parse application_id and user_id from embed
            embed = interaction.message.embeds[0]
            description = embed.description
            id_line = [line for line in description.split('\n') if line.startswith("**ID заявки:** ")][0]
            application_id = id_line.split("**ID заявки:** ")[1].strip()
            user_line = [line for line in description.split('\n') if line.startswith("**Пользователь:** ")][0]
            mention = user_line.split("**Пользователь:** ")[1].strip()
            user_id_match = re.search(r'<@(\d+)>', mention)
            if not user_id_match:
                raise ValueError("Не удалось извлечь user_id из упоминания.")
            user_id = int(user_id_match.group(1))

            c.execute("SELECT application_type, nickname, status, image_url, second_image_url, source, clan_tag FROM applications WHERE application_id = ?", (application_id,))
            row = c.fetchone()
            if not row:
                await interaction.response.send_message("🚫 Заявка не найдена.", ephemeral=True, delete_after=20)
                return
            application_type, nickname, status, image_url, second_image_url, source, clan_tag = row
            if status != 'pending':
                await interaction.response.send_message("🚫 Заявка уже обработана.", ephemeral=True, delete_after=20)
                return

            member = interaction.guild.get_member(user_id)
            if not member:
                await interaction.response.send_message("🚫 Пользователь не найден на сервере.", ephemeral=True, delete_after=20)
                return

            new_nick = nickname  # по умолчанию

            # Определяем роли и ник
            if application_type == "Участник клана":
                role_names = ["Рекрут"]
                if not nickname.startswith("[Arct]"):
                    prefix = "[Arct] "
                    suffix = " (*Имя*)"
                    max_length = 32
                    max_nick_len = max_length - len(prefix) - len(suffix)
                    trimmed_nick = nickname[:max_nick_len] if len(nickname) > max_nick_len else nickname
                    new_nick = f"{prefix}{trimmed_nick}{suffix}"
                    try:
                        await member.edit(nick=new_nick)
                    except discord.Forbidden:
                        pass
                    except discord.HTTPException:
                        pass
            else:
                role_names = ["Союзник"]

            given_roles = []
            for role_name in role_names:
                role = discord.utils.get(interaction.guild.roles, name=role_name)
                if role and role not in member.roles:
                    await member.add_roles(role)
                    given_roles.append(role.name)

            # Обновляем статус в базе
            c.execute(
                "UPDATE applications SET status = ?, processed_at = ?, processed_by = ? WHERE application_id = ?",
                ('accepted', datetime.now().isoformat(), interaction.user.id, application_id)
            )
            conn.commit()

            # Далее обновляем эмбед и логируем
            embed.title = f"✅ Заявка на {application_type} принята"
            embed.color = discord.Color.green()
            embed.add_field(name="Обработал", value=interaction.user.mention, inline=False)
            if given_roles:
                embed.add_field(name="Выданные роли", value=", ".join(given_roles), inline=False)
            if image_url:
                embed.set_image(url=image_url)

            embeds = [embed]
            if len(interaction.message.embeds) > 1 and second_image_url:
                second_embed = interaction.message.embeds[1]
                second_embed.color = discord.Color.green()
                embeds.append(second_embed)

            await interaction.message.edit(embeds=embeds, view=None)

            log_channel = discord.utils.get(interaction.guild.text_channels, name=LOG_CHANNEL_NAME)
            if log_channel:
                log_embed = discord.Embed(
                    title=f"✅ Участник верифицирован" if application_type == "Участник клана" else f"✅ Заявка на {application_type} принята",
                    description=f"{member.mention} был верифицирован {interaction.user.mention}",
                    color=discord.Color.green()
                )
                log_embed.add_field(name="Ник", value=new_nick, inline=False)
                if application_type == "Участник клана" and source:
                    log_embed.add_field(name="Как узнали о клане", value=source, inline=False)
                elif application_type == "Союзник" and clan_tag:
                    log_embed.add_field(name="Тег клана", value=clan_tag, inline=False)
                if given_roles:
                    log_embed.add_field(name="Выданные роли", value=", ".join(given_roles), inline=False)
                if image_url:
                    log_embed.set_image(url=image_url)
                log_embeds = [log_embed]
                if second_image_url:
                    log_second_embed = discord.Embed(color=discord.Color.green())
                    log_second_embed.set_image(url=second_image_url)
                    log_second_embed.set_footer(text="Второй скриншот")
                    log_embeds.append(log_second_embed)
                await log_channel.send(embeds=log_embeds)

            await interaction.response.send_message(f"✅ Заявка {application_id} принята.", ephemeral=True, delete_after=10)

        except Exception as e:
            logging.error(f"Ошибка при принятии заявки: {e}")
            await interaction.response.send_message("❌ Ошибка при принятии заявки.", ephemeral=True, delete_after=10)

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger, custom_id="reject_application")
    async def reject_button(self, interaction: Interaction, button: Button):
        from PykeBOT import is_officer  # Import here to avoid circular import
        if not is_officer(interaction.user):
            await self.delete_old_ephemeral(interaction)
            await interaction.response.send_message("🚫 У вас нет прав офицера.", ephemeral=True, delete_after=10)
            return

        try:
            # Parse application_id and user_id from embed
            embed = interaction.message.embeds[0]
            description = embed.description
            id_line = [line for line in description.split('\n') if line.startswith("**ID заявки:** ")][0]
            application_id = id_line.split("**ID заявки:** ")[1].strip()
            user_line = [line for line in description.split('\n') if line.startswith("**Пользователь:** ")][0]
            mention = user_line.split("**Пользователь:** ")[1].strip()
            user_id_match = re.search(r'<@(\d+)>', mention)
            if not user_id_match:
                raise ValueError("Не удалось извлечь user_id из упоминания.")
            user_id = int(user_id_match.group(1))
            applicant = interaction.client.get_user(user_id)
            if not applicant:
                raise ValueError("Не удалось найти пользователя.")

            c.execute("SELECT application_type, status, image_url, second_image_url, source, clan_tag FROM applications WHERE application_id = ?", (application_id,))
            row = c.fetchone()
            if not row:
                await self.delete_old_ephemeral(interaction)
                await interaction.response.send_message("🚫 Заявка не найдена.", ephemeral=True, delete_after=20)
                return
            application_type, status, image_url, second_image_url, source, clan_tag = row
            if status != 'pending':
                await self.delete_old_ephemeral(interaction)
                await interaction.response.send_message("🚫 Заявка уже обработана.", ephemeral=True, delete_after=20)
                return

            c.execute(
                "UPDATE applications SET status = ?, processed_at = ?, processed_by = ? WHERE application_id = ?",
                ('rejected', datetime.now().isoformat(), interaction.user.id, application_id)
            )
            conn.commit()

            # Update main embed
            embed.title = f"❌ Заявка на {application_type} отклонена"
            embed.color = discord.Color.red()
            embed.add_field(name="Обработал", value=interaction.user.mention, inline=False)
            if image_url:
                embed.set_image(url=image_url)

            # Update second embed if it exists
            embeds = [embed]
            if len(interaction.message.embeds) > 1 and second_image_url:
                second_embed = interaction.message.embeds[1]
                second_embed.color = discord.Color.red()
                embeds.append(second_embed)

            await interaction.message.edit(embeds=embeds, view=None)

            # Log to log channel
            log_channel = discord.utils.get(interaction.guild.text_channels, name=LOG_CHANNEL_NAME)
            if log_channel:
                log_embed = Embed(
                    title=f"❌ Заявка на {application_type} отклонена",
                    description=f"Заявка от {applicant.mention} была отклонена {interaction.user.mention}",
                    color=discord.Color.red()
                )
                if application_type == "Участник клана" and source:
                    log_embed.add_field(name="Как узнали о клане", value=source, inline=False)
                elif application_type == "Союзник" and clan_tag:
                    log_embed.add_field(name="Тег клана", value=clan_tag, inline=False)
                if image_url:
                    log_embed.set_image(url=image_url)
                log_embeds = [log_embed]
                if second_image_url:
                    log_second_embed = Embed(color=discord.Color.red())
                    log_second_embed.set_image(url=second_image_url)
                    log_second_embed.set_footer(text="Второй скриншот")
                    log_embeds.append(log_second_embed)
                await log_channel.send(embeds=log_embeds)

            await self.delete_old_ephemeral(interaction)
            await interaction.response.send_message(f"❌ Заявка {application_id} отклонена.", ephemeral=True, delete_after=10)

        except Exception as e:
            logging.error(f"Ошибка при отклонении заявки: {e}")
            await self.delete_old_ephemeral(interaction)
            await interaction.response.send_message("❌ Ошибка при отклонении заявки.", ephemeral=True, delete_after=10)

async def setup_application_message(bot, channel_name=SUBMIT_APPLICATION_CHANNEL_NAME):
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name)
    if not channel:
        logging.error(f"Канал '{channel_name}' не найден.")
        return

    async for message in channel.history(limit=100):
        if message.author == bot.user:
            await message.delete()

    embed = Embed(
        title="📝 Подача заявки в клан Arct",
        description="Нажмите одну из кнопок ниже, чтобы подать заявку на участника клана или союзника.\nТребуется прикрепить два скриншота (F1 и главное меню).",
        color=discord.Color.blurple()
    )
    embed.set_footer(text="Заполните форму внимательно!")
    await channel.send(embed=embed, view=ApplicationView())

class PingGooseView(View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id

    @discord.ui.button(label="Кря!🦆", style=discord.ButtonStyle.success, custom_id="ping_goose_button")
    async def give_ping_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("Ой, роль куда-то улетела! 🦢", ephemeral=True)
            logging.warning(f"Роль {self.role_id} не найдена в гильдии {interaction.guild.id}")
            return

        member = interaction.user
        if role in member.roles:
            await interaction.response.send_message("Ты уже гусь! 🦆", ephemeral=True)
        else:
            try:
                await member.add_roles(role)
                await interaction.response.send_message("Пинг принят! Теперь ты 🦆", ephemeral=True)
                logging.info(f"Роль {role.name} выдана пользователю {member} ({member.id})")
            except discord.Forbidden:
                await interaction.response.send_message("У меня нет прав выдать роль :( 🦢", ephemeral=True)
                logging.warning(f"Нет прав выдать роль {role.name} пользователю {member} ({member.id})")
            except Exception as e:
                await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)
                logging.error(f"Ошибка при выдаче роли {role.name} пользователю {member} ({member.id}): {e}")

async def setup_ping_role_message(bot: commands.Bot):
    guild = discord.utils.get(bot.guilds)
    if guild is None:
        logging.error("Гильдия не найдена.")
        return

    channel = discord.utils.get(guild.text_channels, name=PING_ROLE_CHANNEL_NAME)
    if channel is None:
        logging.error(f"Канал {PING_ROLE_CHANNEL_NAME} не найден.")
        return

    role = discord.utils.get(guild.roles, name=PING_ROLE_NAME)
    if role is None:
        logging.error(f"Роль {PING_ROLE_NAME} не найдена.")
        return

    # Проверяем, есть ли уже сообщение с кнопкой
    async for message in channel.history(limit=50):
        if message.author == bot.user:
            for row in message.components:
                for comp in row.children:
                    if getattr(comp, "custom_id", None) == "ping_goose_button":
                        bot.add_view(PingGooseView(role.id))
                        logging.info("Найдено и активировано старое сообщение с кнопкой гуся.")
                        return

    # Если сообщения нет, создаём новое
    view = PingGooseView(role.id)
    await channel.send("Нажми кнопку и получи оповещения на игры в 🦆!", view=view)
    bot.add_view(view)
    logging.info("Создано новое сообщение с кнопкой гуся.")

async def restore_action_views(bot):
    bot.add_view(ApplicationActionView())

def setup_application(bot):
    async def new_setup_hook(self):
        # вызываем базовый setup_hook, если он есть
        base = super(type(self), self)
        if hasattr(base, "setup_hook"):
            await base.setup_hook()

        # Регистрируем вью
        self.add_view(ApplicationView())
        await restore_action_views(self)
        logging.info("Зарегистрированы представления ApplicationView и ApplicationActionView в setup_hook")

        # Делаем инициализацию, которая раньше была в on_ready
        await setup_application_message(self)
        await setup_ping_role_message(self)
        logging.info("Выполнены setup_application_message и setup_ping_role_message")

    bot.__class__.setup_hook = new_setup_hook

if __name__ == "__main__":
    logging.error("Этот файл должен быть импортирован в PykeBOT.py, а не запущен напрямую.")