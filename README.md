<a id="top"></a>

<div align="center">

# 🏷️ MiniAuction — Backend

### Кожна ставка має значення.

**REST API для платформи онлайн-аукціонів на FastAPI та MongoDB.**  
Основи для керування лотами, учасниками та ставками — з акцентом на надійну серверну логіку.

[![Backend CI](https://github.com/BashukOleksii/MiniAuction-Backend/actions/workflows/ci.yml/badge.svg)](https://github.com/BashukOleksii/MiniAuction-Backend/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.14.5-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.142.4-009688?style=flat-square&logo=fastapi&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?style=flat-square&logo=mongodb&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square)
![Cloudinary](https://img.shields.io/badge/Cloudinary-Configured-3448C5?style=flat-square&logo=cloudinary&logoColor=white)

**[Можливості](#-можливості)** · **[Швидкий старт](#-швидкий-старт)** · **[API](#-доступні-api-ендпоїнти)** · **[Архітектура](#-архітектура)** · **[План розвитку](#-план-розвитку)**

</div>

---

## 📖 Про проєкт

**MiniAuction** — backend-застосунок для невеликої онлайн-платформи аукціонів. Ідея продукту: продавець виставляє лот на обмежений час, а учасники змагаються за нього, підвищуючи поточну ціну. Наприкінці аукціону система має визначати переможця.

Репозиторій містить **ранню робочу основу API**, а не всі можливості завершеного аукціону. Наразі реалізовано моделі даних, валідацію аукціонів, підключення до MongoDB, індекси, перевірки стану сервісу та отримання активних лотів. Логіка авторизації, створення лотів, завантаження фото й приймання ставок — у планах.

> [!NOTE]
> Поточний етап: **Backend foundation / Work in progress**. Опис доступних маршрутів нижче відповідає коду в гілці `main` на момент підготовки README.

## ✨ Можливості

| Складова | Стан | Деталі |
|:--|:--:|:--|
| REST API на FastAPI | ✅ | Автоматична OpenAPI-документація (`/docs`, `/redoc`) |
| MongoDB Atlas | ✅ | Асинхронний PyMongo-клієнт, перевірка підключення та індекси |
| Моделі `User`, `Auction`, `Bid` | ✅ | Валідація даних через Pydantic v2 |
| Перегляд активних аукціонів | ✅ | Фільтр за статусом та часом, сортування за завершенням, `limit` |
| Health checks | ✅ | Перевірка API та доступності бази даних |
| Cloudinary | 🟡 | Налаштування клієнта є; API завантаження фото ще немає |
| Автоматичні перевірки | ✅ | GitHub Actions: синтаксис, Ruff, Pytest |
| Реєстрація та JWT-авторизація | 🕒 | Заплановано; JWT-параметри вже визначені в конфігурації |
| CRUD аукціонів та завантаження фото | 🕒 | Заплановано |
| Ставки, історія, лідер і переможець | 🕒 | Заплановано; потрібна атомарна бізнес-логіка |

**Позначення:** ✅ реалізовано · 🟡 частково підготовлено · 🕒 заплановано.

## 🧰 Технологічний стек

| Технологія | Призначення |
|:--|:--|
| **Python 3.14.5** | Версія, зафіксована у `.python-version` |
| **FastAPI** | HTTP API, маршрути, залежності, OpenAPI |
| **MongoDB Atlas** | Хмарна документна база даних |
| **PyMongo Async** | Асинхронна робота з MongoDB |
| **Pydantic v2 / pydantic-settings** | Моделі, перевірка значень, конфігурація з `.env` |
| **Cloudinary SDK** | Підготовлена інтеграція для зберігання медіафайлів |
| **Uvicorn** | ASGI-сервер |
| **Pytest + Ruff** | Тести та статичний аналіз |
| **GitHub Actions** | CI для `push` та `pull_request` до `main` |

## 🚀 Швидкий старт

### 1. Клонування

```bash
git clone https://github.com/BashukOleksii/MiniAuction-Backend.git
cd MiniAuction-Backend
```

### 2. Віртуальне середовище

Проєкт орієнтується на **Python 3.14.5** (див. `.python-version`).

**Windows / PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

> [!TIP]
> Якщо PowerShell блокує активацію, можна запускати команди без неї: `.\.venv\Scripts\python.exe -m pip ...`.

### 3. Залежності

Для локальної розробки (включно з тестами та лінтером):

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Для середовища розгортання достатньо `requirements.txt`.

### 4. Змінні середовища

Створіть `.env` із шаблону:

```powershell
# Windows / PowerShell
Copy-Item .env.example .env
```

```bash
# Linux / macOS
cp .env.example .env
```

Налаштуйте значення у `.env`:

```dotenv
APP_NAME=Mini Auction API
APP_ENV=development

MONGODB_URI=mongodb+srv://DB_USER:ENCODED_PASSWORD@CLUSTER_HOST.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB_NAME=mini_auction

CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

JWT_SECRET_KEY=replace_with_a_long_random_value
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
```

> [!IMPORTANT]
> Замініть плейсхолдери на власні значення. **Ніколи не додавайте `.env`, паролі, JWT-секрети чи API-ключі до Git.** Cloudinary-параметри наразі потрібні конфігурації навіть попри відсутність маршруту завантаження файлів.

**Щоб підключити MongoDB Atlas:** створіть кластер, користувача бази даних, скопіюйте connection string і додайте свою IP-адресу до **Network Access**. Якщо пароль містить спеціальні символи, закодуйте їх для URI.

### 5. Запуск сервера

Виконуйте з **кореня репозиторію**:

```bash
uvicorn app.main:app --reload
```

За замовчуванням сервер доступний за адресою `http://127.0.0.1:8000`.

| Сторінка | URL |
|:--|:--|
| Swagger UI | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| ReDoc | [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc) |
| OpenAPI JSON | [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json) |

**Зверніть увагу:** застосунок перевіряє MongoDB під час старту й створює індекси. Якщо база недоступна, запуск не завершиться успішно.

## 🔌 Доступні API-ендпоїнти

Базовий префікс: **`/api/v1`**.

| Метод | Маршрут | Опис |
|:--:|:--|:--|
| `GET` | `/api/v1/health` | Перевірка роботи API |
| `GET` | `/api/v1/health/db` | Перевірка підключення до MongoDB |
| `GET` | `/api/v1/auctions/` | Список активних аукціонів |

### Перевірка API

```bash
curl http://127.0.0.1:8000/api/v1/health
```

```json
{"status": "ok"}
```

### Перевірка MongoDB

```bash
curl http://127.0.0.1:8000/api/v1/health/db
```

За успішного підключення:

```json
{"status": "ok", "database": "connected"}
```

Якщо база перестане відповідати після запуску, маршрут поверне **`503 Service Unavailable`**.

### Отримання активних аукціонів

```bash
curl "http://127.0.0.1:8000/api/v1/auctions/?limit=10"
```

**Параметр `limit`:** від `1` до `100`, за замовчуванням `20`.

Маршрут повертає аукціони, у яких `status = active`, `starts_at ≤ поточний час` і `ends_at > поточний час`. Результати відсортовані за `ends_at` **за зростанням** — найближчі до завершення першими. За відсутності відповідних записів повертається `[]`.

## 🏗️ Архітектура

```mermaid
flowchart TD
    Client[🌐 Frontend / API Client] --> FastAPI[⚡ FastAPI REST API]
    FastAPI --> Routes[API Routes]
    Routes --> Models[Pydantic Models]
    Routes --> DB[Async PyMongo]
    DB --> Atlas[(MongoDB Atlas)]
    FastAPI --> Config[Settings / .env]
    FastAPI --> Cloudinary[Cloudinary configuration]

    Future[Planned: services & repositories] -.-> Routes

    classDef core fill:#0f766e,color:#fff,stroke:#115e59
    classDef store fill:#166534,color:#fff,stroke:#14532d
    class FastAPI,Routes core
    class Atlas store
```

### Структура репозиторію

```text
MiniAuction-Backend/
├── .github/
│   └── workflows/
│       └── ci.yml                 # GitHub Actions CI
├── app/
│   ├── api/
│   │   └── routes/
│   │       ├── auctions.py        # GET активних аукціонів
│   │       └── health.py          # Health checks
│   ├── core/
│   │   ├── config.py              # Змінні середовища
│   │   └── cloudinary.py          # Налаштування Cloudinary
│   ├── db/
│   │   └── mongodb.py             # Підключення, індекси
│   ├── models/
│   │   ├── common.py              # UUID, UTC, базова модель
│   │   ├── user.py                # Користувач
│   │   ├── auction.py             # Аукціон та зображення
│   │   └── bid.py                 # Ставка
│   ├── repositories/              # Заготовка шару роботи з БД
│   ├── schemas/                   # Заготовка DTO / API-схем
│   ├── services/                  # Заготовка бізнес-логіки
│   └── main.py                    # FastAPI, lifespan, routers
├── tests/
│   └── test_models.py             # Тести валідації моделей
├── .env.example                   # Шаблон налаштувань
├── .python-version                # 3.14.5
├── requirements.txt               # Залежності застосунку
├── requirements-dev.txt           # Залежності для розробки
└── README.md
```

### Моделі даних

| Модель | Головні поля |
|:--|:--|
| **User** | `username`, `email`, `password_hash`, `role`, `is_active` |
| **Auction** | `seller_id`, `title`, `description`, `category`, `images`, `starting_price`, `current_price`, `min_bid_step`, `starts_at`, `ends_at`, `status`, `leader_id`, `winner_id` |
| **Bid** | `auction_id`, `bidder_id`, `amount`, `created_at` |
| **AuctionImage** | `public_id`, `url`, `is_cover`, `sort_order` |

У документах MongoDB використовується **рядковий UUID як `_id`**. Часові значення для аукціонів мають містити часовий пояс і нормалізуються до **UTC**.

**Статуси аукціону:** `draft` → `active` → `finished`; також передбачено `cancelled`. Це перелік можливих статусів моделі, а не вже реалізована система автоматичних переходів.

**Правила валідації:** поточна ціна не може бути меншою за стартову; час завершення має бути пізнішим за час початку; мінімальний крок ставки повинен бути додатним; аукціон підтримує до 10 записів зображень.

## 🧪 Тестування та CI

Локальні перевірки:

```bash
# Тести моделей
python -m pytest tests -q

# Статичний аналіз коду
python -m ruff check app tests

# Перевірка компіляції Python-модулів
python -m compileall -q app
```

У `tests/test_models.py` перевіряються створення аукціону та обмеження на ціну й часові межі. **Ці тести не потребують живої MongoDB**, на відміну від повного запуску API.

Workflow [Backend CI](.github/workflows/ci.yml) виконується під час `push` і `pull_request` до `main` та запускає ті самі перевірки.

## ☁️ Розгортання на Render

Можна розгорнути API як **Web Service** із підключеним GitHub-репозиторієм.

| Налаштування | Значення |
|:--|:--|
| Runtime | Python |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Environment Variables | Значення з `.env.example` (без плейсхолдерів) |

1. Підключіть репозиторій у Render та створіть Python Web Service.
2. Встановіть наведені Build і Start команди.
3. Додайте секрети через **Environment**, а не в Git.
4. Забезпечте мережевий доступ із сервісу Render до MongoDB Atlas.
5. Після розгортання перевірте `/api/v1/health`, `/api/v1/health/db` та `/docs` на URL вашого сервісу.

> [!CAUTION]
> Не відкривайте MongoDB Atlas для всіх IP-адрес без потреби. Якщо обраний спосіб хостингу не дає стабільної вихідної IP-адреси, окремо продумайте безпечну схему мережевого доступу.

## 🗺️ План розвитку

- [x] Створити FastAPI-застосунок та конфігурацію середовища
- [x] Додати моделі користувачів, аукціонів і ставок
- [x] Підключити MongoDB і створити індекси
- [x] Реалізувати health checks та список активних аукціонів
- [x] Додати базові тести та GitHub Actions
- [ ] Реєстрація, вхід і захист маршрутів через JWT
- [ ] CRUD аукціонів із перевіркою прав продавця
- [ ] Завантаження й керування фото через Cloudinary
- [ ] Створення ставок із перевіркою мінімального кроку
- [ ] Атомарне оновлення ціни та історії ставок при конкурентних запитах
- [ ] Визначення лідера, завершення аукціону й фіксація переможця
- [ ] Пошук, фільтрація, сортування та пагінація лотів
- [ ] Оновлення інформації про ставки на frontend (polling або WebSocket)

> **Особливо важливо:** приймання ставки повинно перевіряти активність аукціону, його дедлайн і мінімальну суму **на backend**. Запис ставки та зміна поточної ціни мають бути узгодженими й безпечними за одночасних запитів — перевірки лише на frontend недостатньо.

## 🤝 Участь у розробці

Ідеї, повідомлення про помилки та пропозиції можна залишати в [GitHub Issues](https://github.com/BashukOleksii/MiniAuction-Backend/issues). Перед суттєвими змінами бажано відкрити issue та узгодити підхід.

---

<div align="center">

**MiniAuction Backend** · Built with ⚡ FastAPI & 🍃 MongoDB

[⬆️ Повернутися на початок](#top) · [GitHub Repository](https://github.com/BashukOleksii/MiniAuction-Backend)

</div>
