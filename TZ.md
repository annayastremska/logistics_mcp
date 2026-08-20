# ТЗ — Import Sourcing Advisor

## 1. Проблема і мета

Агент відповідає на макро-питання закупівель: **«звідки вигідніше й безпечніше завозити товарну групу X в Україну»**. Працює виключно на відкритих даних (нуль внутрішньої інформації компанії).

Вхід користувача: товарна група (HS-код або назва), цільовий обсяг, опційно — країни-кандидати.
Вихід: ранжований список країн-джерел з розкладкою landed cost, прапорцями ризику, поясненням кожного фактора і трейсом MCP-викликів.

## 2. Стек

| Компонент | Рішення |
|---|---|
| Агентний фреймворк | LangGraph (LangChain), MCP-клієнт — `langchain-mcp-adapters` |
| Модель | OpenRouter (`ChatOpenAI` з `base_url=https://openrouter.ai/api/v1`) |
| Існуючий MCP | Microsoft Playwright MCP (`npx @playwright/mcp@latest`) |
| Кастомний MCP | Python, офіційний `mcp` SDK, транспорт stdio, ім'я `trade-sourcing-mcp` |
| Веб-інтерфейс | FastAPI + одна HTML-сторінка (без збірки), SSE для стріму трейсу |

Три процеси, стартуються окремо: кастомний MCP-сервер, Playwright MCP, веб-застосунок з агентом.

## 3. Джерела даних

| Джерело | Endpoint | Що беремо | Авторизація |
|---|---|---|---|
| UN Comtrade preview | `comtradeapi.un.org/public/v1/preview/C/{A,M}/HS` | імпорт України: HS × партнер × період, кг + USD | немає |
| World Bank | `api.worldbank.org/v2` | LPI + 4 субіндекси, контейнерообіг портів | немає |
| WITS TRAINS | `wits.worldbank.org/API/V1/SDMX/V21/...` | ставка ввізного мита MFN по HS6 | немає |
| Довідники Comtrade | `comtradeapi.un.org/files/v1/app/reference/*` | Reporters, partnerAreas, H6 (HS2022) | немає, кладемо в репо |
| Держмитслужба | сторінка новин місячного товарообігу | свіжий місячний показник (2026) | немає, тільки через Playwright |

Ліміти, які кодуємо: Comtrade — token bucket 1 req/s, retry на 429 з backoff, 500 записів на запит; WITS — обов'язковий `User-Agent: Mozilla/5.0`, таймаут 45 с, кеш; дедуплікація рядків Comtrade по вимірах митного режиму.

## 4. Кастомні MCP-тули

### 4.1 `validate_sourcing_brief`
Валідує запит перед витратою квоти API.
- **In:** `hs_code` (str, 2/4/6 цифр) або `product_query` (str, ≥3 симв.), `target_volume_kg` (number > 0), `candidate_countries` (list[ISO3], ≤10, опц.), `year` (int 2015–поточний).
- **Out:** `status`, `normalized_brief` (розкодований HS + офіційна назва з H6, коди країн Comtrade, доступний рік), `warnings[]`, `errors[]`.
- **Логіка:** перевірка існування HS у HS2022, розв'язання назви товару в код, перевірка доступності року для України, нормалізація ISO3 → numeric code.

### 4.2 `get_import_flows` — primary data source
- **In:** `hs_code` (4 або 6 цифр), `year` (int), `partners` (list, опц.), `flow_direction` (`import` \| `mirror_export`), `top_n` (1–50, default 10).
- **Out:** `rows[]` (`partner_iso3`, `partner_name`, `net_weight_kg`, `value_usd`, `unit_price_usd_per_kg`, `share_of_total_pct`), `total_value_usd`, `data_year`, `source` (`live` \| `fixture`), `notes[]`.
- **Логіка:** запит до Comtrade, дедуплікація, join з довідниками, розрахунок ціни за кг і часток, відсікання агрегатних партнерів (World).
- **Помилки:** `RATE_LIMITED`, `NO_DATA_FOR_PERIOD` (успішний пустий результат, не помилка), `UPSTREAM_UNAVAILABLE`.

### 4.3 `estimate_landed_cost`
- **In:** `hs_code` (6 цифр), `origin_iso3`, `volume_kg`, `transport_mode` (`sea` \| `road` \| `rail` \| `air`), `unit_price_usd_per_kg` (опц., інакше беремо з flows).
- **Out:** `breakdown` (`goods_cost`, `duty_amount`, `duty_rate_pct`, `duty_basis` = `MFN`, `transport_cost_estimated`, `total_landed_cost`, `cost_per_kg`), `assumptions[]`, `confidence`, `fta_preference_possible` (bool).
- **Логіка:** MFN-ставка з WITS + модель транспорту (відстань × коефіцієнт режиму) + мито на CIF-базі. Усі змодельовані складові явно позначені як `estimated`.

### 4.4 `rank_sourcing_countries`
- **In:** `hs_code`, `year`, `candidates` (list[ISO3], 2–10), `weights` (об'єкт: `price`, `logistics`, `duty`, `stability`; сума = 1, є default), `transport_mode`.
- **Out:** `ranking[]` (`iso3`, `score` 0–100, `factor_contributions` по кожному фактору, `rank`), `weights_used`, `excluded[]` з причинами.
- **Логіка:** min-max нормалізація факторів, композитний скор, повне розкриття внеску кожного фактора.

### 4.5 `assess_supply_concentration_risk`
- **In:** `hs_code`, `years` (2–5 років), `top_partner_threshold_pct` (default 40).
- **Out:** `hhi` (індекс концентрації), `top_partner`, `top_partner_share_pct`, `yoy_volatility_pct`, `mirror_gap_pct`, `flags[]` (`HIGH_CONCENTRATION`, `VOLATILE_SUPPLY`, `MIRROR_DISCREPANCY`, `SINGLE_SOURCE`), `interpretation`.
- **Логіка:** HHI по частках партнерів, волатильність по роках, порівняння звітності України з дзеркальними даними партнерів.

Розподіл за вимогою: `get_import_flows` — retrieval (1 з 3); `validate_sourcing_brief`, `estimate_landed_cost`, `rank_sourcing_countries`, `assess_supply_concentration_risk` — не retrieval (4, потрібно ≥2).

## 5. Агентний флоу

1. Playwright MCP відкриває сторінку митниці, знімає свіжий місячний товарообіг → визначає recency-контекст і прапорець «дані Comtrade відстають на N місяців».
2. `validate_sourcing_brief` — нормалізує запит; при `status=error` флоу зупиняється з поясненням.
3. `get_import_flows` — фактичні потоки, топ країн-джерел.
4. **Рішення агента:** якщо частка топ-партнера > порогу або є прапорець ризику → `assess_supply_concentration_risk` і розширення списку кандидатів за межі поточних постачальників.
5. `estimate_landed_cost` по кожному кандидату.
6. `rank_sourcing_countries` — фінальний скор; ваги коригуються залежно від того, що виявив крок 4.
7. Аутпут: рекомендація + розкладка + ризики + трейс.

Зворотний зв'язок реальний: результат кроку 1 змінює recency-оцінку, результат кроку 4 змінює і набір кандидатів, і ваги в кроці 6.

## 6. Веб-інтерфейс

Одна сторінка: форма запиту → таблиця ранжування з розкладкою по факторах → блок ризиків → **панель трейсу**: кожен MCP-виклик з назвою сервера, тулу, аргументами, часом і джерелом (`live`/`fixture`). Панель трейсу закриває пункти захисту про дискавері обох з'єднань і походження значень.

Кнопка `Demo: trigger failure` — примусово ламає Playwright-крок (неправильний URL) для демонстрації фейлу.

## 7. Фікстури й offline-режим

- Записуємо реальні відповіді всіх трьох API в `fixtures/` (JSON as-is, без редагування).
- `REPLAY=1` — читання з фікстур; шлях парсингу й обробки **той самий**, підміняється лише транспортний шар.
- Кеш живих відповідей у `.cache/` (в .gitignore), TTL 24 год.
- Заборонено: гілки, що повертають готову відповідь.

## 8. Структура репозиторію

```
README.md                  # prereqs, install, окремі команди старту
TZ.md
docs/tool-contracts.md     # Part C: контракти 5 кастомних тулів + Playwright
docs/design-rationale.md   # Part C/6: обґрунтування, trade-offs, обмеження
docs/demo-checklist.md     # сценарій захисту, 9 пунктів
mcp_server/                # кастомний MCP-сервер
  server.py  tools/  sources/  models.py
agent/                     # LangGraph-граф + MCP-клієнт
  graph.py  mcp_config.py
web/                       # FastAPI + index.html
data/reference/            # H6.json, Reporters.json, partnerAreas.json
fixtures/                  # записані відповіді API
.env.example               # OPENROUTER_API_KEY=
```

## 9. Обмеження (документуємо явно)

- Транспортна складова змодельована, не з реальних тарифів.
- Мито — MFN; преференції FTA (DCFTA з ЄС) не враховані, лише прапорець.
- Comtrade річні дані відстають ~на рік; 2025 Україною ще не відзвітовано.
- LPI зафіксований на 2022.
- Ціна за кг тільки на HS4/HS6 — на HS2 вага в джерелі нульова.
- Рекомендація — макро-скринінг напрямків, не заміна тендерного процесу.

## 10. Definition of Done

- [ ] Кастомний MCP-сервер стартує окремою командою, віддає 5 тулів зі схемами
- [ ] Агент дискаверить обидва з'єднання, видно в UI
- [ ] Повний флоу проходить на живих даних
- [ ] Той самий флоу проходить з `REPLAY=1`
- [ ] Фейл Playwright відтворюється кнопкою і коректно повідомляється
- [ ] Невалідний вхід (неіснуючий HS) дає структуровану помилку, не трейсбек
- [ ] Заповнені docs/ (контракти, rationale, чекліст)
- [ ] У репо немає секретів, є `.env.example`
