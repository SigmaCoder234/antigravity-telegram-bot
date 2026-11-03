# 🤖 Claude Code Telegram Bot Assistant

Полнофункциональный Telegram-бот для удаленного управления и взаимодействия с ИИ-агентом **[Claude Code](https://code.claude.com)** (CLI `claude`). Бот позволяет отправлять текстовые задачи, передавать изображения для анализа и выполнения инструкций, управлять консолью сервера в интерактивном режиме с кнопками подтверждения `[y/N]`, перемещаться по файловой системе в виде интерактивного древа, переключаться между отдельными чатами/диалогами, а также автоматически запускается после перезагрузки сервера.

---

## ✨ Новые и основные возможности

1. **💬 Мульти-чаты и история диалогов (`/chats`):**
   - Просмотр списка ваших сохраненных диалогов с названиями и счетчиком сообщений.
   - Мгновенное переключение между контекстами и задачами.
   - Возможность создания новых диалогов, переименования и удаления старых.

2. **🌲 Интерактивное древо файлов сервера (`/tree` или `/files`):**
   - Наглядный вывод файловой структуры папок и файлов в виде дерева.
   - Интерактивные кнопки: нажимайте на `📁 папки`, чтобы заходить внутрь, `⬆️ Наверх`, чтобы подняться, и `📍 Сделать рабочей (CWD)`, чтобы агент выполнял команды в этой папке.
   - Просмотр информации о файле и кнопка `[📥 Скачать файл]` прямо в Telegram.

3. **🔄 Автозапуск 24/7 (Systemd):**
   - Бот зарегистрирован в `systemd` как служба `telegram-bot.service`.
   - Автоматически стартует при включении или перезагрузке сервера.

4. **📸 Обработка фотографий и документов:**
   - Отправляйте скриншоты кода, ошибок, схем или интерфейсов — Claude загрузит их и изучит через инструмент `Read` (мультимодальное зрение).
   - Автоматическая отправка сгенерированных агентом файлов и картинок обратно в чат.

5. **🛡️ Интерактивные подтверждения консоли (`[y/N]`, пароли, апдейты):**
   - Команда `/exec <cmd>` запускает Bash в псевдотерминале (PTY).
   - При появлении запроса подтверждения (`[Y/n]`, `[y/N]`, `password:`, `continue?`) бот отправляет интерактивные кнопки: `[✅ Yes (y)]`, `[❌ No (n)]`, `[⏎ Enter]`, `[⏹ Прервать]`.

6. **📰 Ответы Claude как rich-сообщения Telegram:**
   - Markdown-ответ Claude отправляется через `sendRichMessage` (Bot API 10.1+): настоящие заголовки, таблицы, списки, блоки кода, цитаты, разделители и формулы прямо в чате.
   - Длинные ответы делятся по разделам (никогда внутри блока кода, формулы или таблицы).
   - Если Telegram отклонит rich-сообщение, бот автоматически отправит ответ в прежнем HTML-формате. Отключить: `RICH_MESSAGES=false`.
   - **Стриминг ответа (`sendRichMessageDraft`):** в личном чате ответ печатается вживую, по мере генерации, а под текстом показывается текущее действие Claude (команда, файл, поиск). На черновике есть кнопка «стоп» — она прерывает работу агента. В группах и при недоступности черновиков бот показывает прежнее статус-сообщение. Отключить: `STREAM_RESPONSES=false`.

7. **⚡ Быстрые команды:**
   - `/chats` — список и выбор сохраненных диалогов
   - `/tree` — интерактивное древо файлов и навигация
   - `/new` — создать новый чистый диалог
   - `/btw <вопрос>` — попутный вопрос в ответвлении сессии (`--fork-session`), основной контекст не меняется
   - `/plan <задача>` — запуск Claude в режиме планирования (`--permission-mode plan`)
   - `/model` — выбор модели (Opus, Sonnet, Haiku, Fable — алиасы или полные id)
   - `/effort` — глубина размышлений (`low`, `medium`, `high`, `xhigh`, `max`)
   - `/mode` — переключение Автопилот / Режим подтверждений
   - `/status` — мониторинг ресурсов сервера и параметров агента
   - `/stop` — отмена активной задачи

---

## 🧩 Как бот работает с Claude Code

Каждое сообщение запускает `claude -p "<запрос>" --output-format stream-json --verbose` в рабочей папке чата.

| Возможность бота | Флаги Claude Code |
|---|---|
| Продолжение диалога | `--resume <session_id>` (id сессии хранится для каждого чата в `data/sessions.json`) |
| `/btw` | `--resume <id> --fork-session` |
| `/plan` | `--permission-mode plan` (план берётся из `ExitPlanMode`) |
| Режим «Автопилот» | `--permission-mode bypassPermissions` |
| Режим подтверждений | инструкция в `--append-system-prompt`: сначала спросить, потом выполнять |
| `/model`, `/effort` | `--model`, `--effort` |
| Лимиты | ошибки `usage limit` / `429` распознаются, бот сам напишет, когда лимит сбросится |

Статус в Telegram обновляется в реальном времени: какие команды выполняет Claude, какие файлы читает/изменяет, какие субагенты запускает.

## 🚀 Деплой на сервер

### 1. Требования

| Компонент | Версия | Зачем |
|---|---|---|
| Linux с `systemd` | Ubuntu 22.04+ / Debian 12+ и аналоги | автозапуск бота |
| Python | 3.10 – 3.14 | сам бот (`aiogram` 3.31+) |
| Node.js | 22+ | Claude Code CLI |
| Claude Code | последняя | ИИ-агент (`claude`) |
| Telegram-бот | токен от [@BotFather](https://t.me/BotFather) | |
| Аккаунт Claude | подписка Pro/Max или API-ключ `ANTHROPIC_API_KEY` | доступ к моделям |

Свой Telegram ID можно узнать у [@userinfobot](https://t.me/userinfobot) — он понадобится для `ALLOWED_USER_IDS`.

### 2. Системные пакеты

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip curl

# Node.js 22 (официальный репозиторий NodeSource)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node --version   # должно быть v22 или новее
```

### 3. Пользователь для бота (рекомендуется)

Claude Code **не разрешает режим без подтверждений (`bypassPermissions`) от root**, а «Автопилот» бота работает именно в нём. Поэтому бота лучше запускать от отдельного пользователя:

```bash
sudo useradd -m -s /bin/bash claudebot
# Если агент должен управлять системой (apt, systemctl и т.п.), дайте sudo без пароля.
# Это фактически полный доступ к серверу — делайте осознанно:
# echo 'claudebot ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/claudebot
```

> Работать от root тоже можно — см. [вариант с root](#вариант-запуск-от-root) ниже.

### 4. Claude Code и авторизация

```bash
sudo npm install -g @anthropic-ai/claude-code
which claude && claude --version
```

Войдите в аккаунт Claude **от имени пользователя бота** (данные входа сохраняются в его `~/.claude`):

```bash
sudo -iu claudebot
claude            # откроется мастер входа: выберите аккаунт Claude и пройдите авторизацию по ссылке
# после входа выйдите из claude (/exit) и проверьте:
claude -p "ответь одним словом: pong"
exit
```

Вместо входа по подписке можно указать API-ключ: `ANTHROPIC_API_KEY=sk-ant-...` в `.env` (шаг 6).

### 5. Код бота и зависимости

```bash
sudo -iu claudebot
git clone https://github.com/SigmaCoder234/antigravity-telegram-bot.git ~/telegram_bot
cd ~/telegram_bot
python3 -m venv venv
venv/bin/pip install -U pip
venv/bin/pip install -r requirements.txt
# необязательно: картинки для формул в HTML-режиме
# venv/bin/pip install matplotlib
cp .env.example .env
```

### 6. Настройка `.env`

Минимально нужны две строки:

```ini
TELEGRAM_BOT_TOKEN=123456789:AA...      # токен от @BotFather
ALLOWED_USER_IDS=111111111              # ваш Telegram ID (через запятую, если несколько)
```

> 🔐 Бот даёт полный доступ к серверу через ИИ-агента. Если оставить `ALLOWED_USER_IDS` пустым, администратором станет **первый, кто напишет боту** — не оставляйте его пустым на рабочем сервере.

Остальные параметры:

| Параметр | По умолчанию | Описание |
|---|---|---|
| `DEFAULT_MODEL` | `opus` | `opus`, `sonnet`, `haiku`, `fable` или полный id (`claude-opus-5-5`) |
| `DEFAULT_EFFORT` | `high` | `low`, `medium`, `high`, `xhigh`, `max` |
| `DEFAULT_CWD` | домашняя папка | рабочая папка агента по умолчанию |
| `DEFAULT_MODE` | `auto` | `auto` — автопилот, `review` — сначала спрашивать |
| `CLAUDE_BIN_PATH` | автопоиск | путь к `claude`, если systemd его не находит (`which claude`) |
| `ANTHROPIC_API_KEY` | — | ключ API вместо входа по подписке |
| `FALLBACK_MODEL` | — | запасная модель при перегрузке основной, например `sonnet` |
| `MAX_BUDGET_USD` | — | лимит расходов на один запрос (только для API-ключа) |
| `CLAUDE_EXTRA_ARGS` | — | дополнительные флаги `claude`, например `--add-dir /srv/projects` |
| `RICH_MESSAGES` | `true` | ответы как rich-сообщения Telegram (заголовки, таблицы, формулы) |
| `RICH_MAX_CHARS` | `16000` | максимальная длина одного rich-сообщения до разбиения |
| `STREAM_RESPONSES` | `true` | печатать ответ вживую в личном чате |
| `IS_SANDBOX` | — | `1` — разрешить автопилот от root (только на изолированном сервере) |

### 7. Пробный запуск

```bash
cd ~/telegram_bot
venv/bin/python bot.py
```

В консоли должно появиться `🚀 Бот @имя_бота успешно запущен`. Напишите боту в Telegram `/start`, затем любой вопрос — ответ должен печататься вживую. Остановите бота `Ctrl+C` и выйдите из пользователя: `exit`.

### 8. Служба systemd

Создайте unit-файл (пути — для пользователя `claudebot`):

```bash
sudo tee /etc/systemd/system/telegram-bot.service > /dev/null <<'UNIT'
[Unit]
Description=Claude Code Telegram Bot Assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=claudebot
WorkingDirectory=/home/claudebot/telegram_bot
ExecStart=/home/claudebot/telegram_bot/venv/bin/python /home/claudebot/telegram_bot/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=HOME=/home/claudebot
Environment=PATH=/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now telegram-bot
sudo systemctl status telegram-bot --no-pager
journalctl -u telegram-bot -f        # логи в реальном времени
```

### 9. Обновление

```bash
sudo -iu claudebot bash -c 'cd ~/telegram_bot && git pull && venv/bin/pip install -U -r requirements.txt'
sudo npm update -g @anthropic-ai/claude-code   # обновить Claude Code
sudo systemctl restart telegram-bot
```

Диалоги и настройки пользователей хранятся в `data/sessions.json` и сохраняются при обновлении.

### Вариант: запуск от root

Если сервер изолирован и вы осознанно работаете от root, используйте файлы из репозитория как есть:

```bash
git clone https://github.com/SigmaCoder234/antigravity-telegram-bot.git /root/telegram_bot
cd /root/telegram_bot
pip install -r requirements.txt          # или venv, как выше; тогда поправьте ExecStart
cp .env.example .env                     # заполните токен и ALLOWED_USER_IDS
echo 'IS_SANDBOX=1' >> .env              # иначе Claude откажется работать без подтверждений
claude                                   # вход в аккаунт Claude от root
cp systemd/telegram-bot.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now telegram-bot
```

В этом варианте логи пишутся в `/root/telegram_bot/data/bot.log` (`tail -f data/bot.log`).

### Переход со старой версии (agy / Antigravity)

1. Обновите код (`git pull`) и зависимости (`pip install -U -r requirements.txt`).
2. Установите Claude Code и войдите в аккаунт (шаг 4).
3. В `.env` замените `AGY_BIN_PATH` на `CLAUDE_BIN_PATH` (или удалите — путь найдётся сам). Старое значение `DEFAULT_MODEL=gemini-...` автоматически заменяется на `opus`.
4. Перезапустите службу. Список чатов сохранится, но каждый старый диалог продолжится с чистого контекста Claude; модели Gemini, выбранные пользователями, сбросятся на модель по умолчанию.

### Решение проблем

| Симптом | Причина и решение |
|---|---|
| `Не найден исполняемый файл Claude Code` | systemd не видит `claude` в `PATH`. Укажите полный путь из `which claude` в `CLAUDE_BIN_PATH`. |
| Ошибка о запуске с правами root/sudo | Бот запущен от root в режиме автопилота. Запустите от отдельного пользователя или добавьте `IS_SANDBOX=1`. |
| Ошибка авторизации (нужен вход / неверный ключ API) | Claude не авторизован для пользователя службы. Выполните `sudo -iu claudebot claude` и войдите, либо задайте `ANTHROPIC_API_KEY`. |
| Ответы приходят простым текстом без таблиц | Старая версия Telegram у получателя или rich-сообщения отклонены — бот сам откатывается на HTML. Обновите приложение Telegram; проверьте `aiogram>=3.31` (`pip show aiogram`). |
| Ответ не печатается вживую | Стриминг работает только в личном чате. Проверьте `STREAM_RESPONSES=true`; в логах ищите `Rich draft streaming disabled`. |
| Бот не отвечает, `⛔ Доступ ограничен` | Ваш ID не в `ALLOWED_USER_IDS`. Бот показывает ID в этом сообщении — добавьте его и перезапустите службу. |
| `⏳ Лимит использования исчерпан` | Закончился лимит подписки или API. Бот сам напишет, когда лимит сбросится; можно задать `FALLBACK_MODEL`. |

---

## 🛠️ Управление службой бота на сервере

```bash
# Статус службы:
sudo systemctl status telegram-bot     # или: ./run.sh status

# Логи в реальном времени:
journalctl -u telegram-bot -f          # или: ./run.sh logs
# (при запуске от root по unit-файлу из репозитория: tail -f data/bot.log)

# Перезапуск / остановка:
sudo systemctl restart telegram-bot    # или: ./run.sh restart
sudo systemctl stop telegram-bot       # или: ./run.sh stop
```
