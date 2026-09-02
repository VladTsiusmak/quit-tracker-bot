"""
Телеграм-бот. Единственная задача — поздороваться и дать кнопку,
которая открывает Mini App (наш трекер отказа от вредных привычек).

Запуск:
    python bot.py

Перед запуском заполните .env (см. .env.example):
    BOT_TOKEN   — токен от @BotFather
    WEBAPP_URL  — https-адрес, на котором крутится backend.py
                  (для локальной разработки — адрес от ngrok)
"""

import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN. Заполните файл .env (см. .env.example)")
if not WEBAPP_URL:
    raise RuntimeError("Не найден WEBAPP_URL. Заполните файл .env (см. .env.example)")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="Открыть трекер",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )]
        ]
    )
    await message.answer(
        "Привет! Это трекер отказа от вредных привычек.\n\n"
        "Нажмите кнопку ниже, чтобы указать, от чего вы отказались "
        "(вейп / под-система, алкоголь — можно сразу от нескольких) "
        "и увидеть свой прогресс.",
        reply_markup=keyboard,
    )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())