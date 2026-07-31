# Складской учёт (офлайн)

Десктопное приложение на Python + SQLite + PyQt6 для учёта товаров на одном листе.

## Этапы 1–6 (текущее состояние)

- Каркас, БД, архиватор
- GUI: учёт с авторасчётом и валидацией
- Отчёты: движение / остатки, экспорт PDF в `reports/`

Далее: этап 7 (сборка и приёмка). См. `../plan.md`.

## Установка (PowerShell)

```powershell
cd d:\20260725_work\single_sheet\inventory_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Запуск

```powershell
cd d:\20260725_work\single_sheet\inventory_app
python main.py
```

## Проверка модулей

```powershell
cd d:\20260725_work\single_sheet\inventory_app
python database.py
python archiver.py
python pdf_generator.py
```

PDF сохраняются в `reports\`.

## Структура

| Путь | Назначение |
|------|------------|
| `main.py` | Окно PyQt6 |
| `database.py` | SQLite CRUD и отчёты |
| `pdf_generator.py` | PDF (fpdf2) |
| `archiver.py` | Ежедневный ZIP |
| `app_paths.py` | Пути |
| `config.json` | Склады, пути |
| `db/` | База |
| `backups/` | Архивы |
| `reports/` | PDF |
| `../shablon/` | Excel-шаблон номенклатуры |
