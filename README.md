# Трекер отказа от курения — Telegram Mini App

## Структура проекта
```
quit-tracker-bot/
├── bot.py           — телеграм-бот (aiogram), даёт кнопку "Открыть трекер"
├── backend.py       — сервер (FastAPI), отдаёт страницу и хранит данные
├── static/
│   └── index.html   — сама веб-страница (Mini App)
├── requirements.txt
├── .env.example      — шаблон настроек, скопировать в .env
└── README.md
```

## Шаг 1. Открыть проект в PyCharm
File → Open → выбрать папку `quit-tracker-bot`.

## Шаг 2. Создать виртуальное окружение
PyCharm обычно предложит это сам при открытии проекта (внизу справа
всплывёт подсказка "Creating virtual environment"). Если нет — сделать
вручную:
- Settings → Project → Python Interpreter → Add Interpreter → Add Local Interpreter → Virtualenv

## Шаг 3. Установить зависимости
Открыть терминал в PyCharm (внизу, вкладка Terminal) и выполнить:
```bash
pip install -r requirements.txt
```

## Шаг 4. Получить токен бота
1. Написать в Telegram боту **@BotFather**
2. Команда `/newbot`, придумать имя и username
3. Скопировать выданный токен

## Шаг 5. Настроить .env
Скопировать `.env.example` в `.env` и вставить токен:
```
BOT_TOKEN=123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WEBAPP_URL=https://...   # заполним на следующем шаге
```

## Шаг 6. Запустить бэкенд
В терминале:
```bash
uvicorn backend:app --reload --port 8000
```
Проверить: открыть в браузере `http://localhost:8000` — должна открыться
страница трекера (работает в тестовом режиме, без Telegram).

## Шаг 7. Получить HTTPS-адрес для теста (Telegram требует HTTPS)
Telegram не разрешает открывать Mini App по обычному http://localhost.
Для локальной разработки проще всего использовать **ngrok**:

1. Скачать: https://ngrok.com/download
2. Запустить в отдельном терминале:
   ```bash
   ngrok http 8000
   ```
3. Скопировать выданный адрес вида `https://xxxx.ngrok-free.app`
4. Вставить его в `.env` как `WEBAPP_URL`

## Шаг 8. Запустить бота
В PyCharm — правой кнопкой на `bot.py` → Run.
Или в терминале:
```bash
python bot.py
```

## Шаг 9. Проверить
Открыть своего бота в Telegram, отправить `/start`, нажать кнопку
"Открыть трекер" — должна открыться веб-страница внутри Telegram.

---

## Что дальше (когда захотите выложить бота "в люди")
- **Хостинг** вместо ngrok: Railway.app или Render.com — оба бесплатно
  дают HTTPS-адрес и умеют запускать Python-проекты прямо из GitHub
- **База данных**: SQLite (уже используется) отлично подходит, пока
  пользователей немного; при росте — можно перейти на Postgres
- **Безопасность**: сейчас бэкенд верит `user_id`, который присылает
  сама страница — для маленького личного проекта это нормально, но для
  публичного бота стоит проверять `initData` от Telegram по инструкции:
  https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
