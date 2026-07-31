# Складской учёт (офлайн)

Десктопное приложение на **Python + SQLite + PyQt6** для учёта товаров на одном листе (аналог Excel). Работает без интернета.

## Возможности

- Учёт по складу (А/Б) и дате, номенклатура всегда на экране
- Авторасчёт «Остаток на конец», валидация чисел, автосохранение
- Диалог парного перемещения между складами
- Ежедневный ZIP-бэкап БД при закрытии
- Отчёты: движение товаров / актуальные остатки → PDF

## Установка для разработки (PowerShell)

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

## Проверка приёмки

```powershell
cd d:\20260725_work\single_sheet\inventory_app
python acceptance_check.py
```

Дополнительно:

```powershell
python database.py
python archiver.py
python pdf_generator.py
```

## Сборка exe (PyInstaller)

```powershell
cd d:\20260725_work\single_sheet\inventory_app
.\build.ps1
```

Результат: `dist\SkladUchet\SkladUchet.exe`  
Папку `dist\SkladUchet` можно копировать на другой ПК **целиком** (нужны `_internal`, `config.json`, `shablon`).

На чистой Windows без установленного Python приложение запускается из этой папки.  
Требование: системный шрифт с кириллицей (обычно есть Arial).

## Структура папок

| Путь | Назначение |
|------|------------|
| `main.py` | Окно приложения |
| `database.py` | SQLite CRUD и отчёты |
| `pdf_generator.py` | PDF (fpdf2) |
| `archiver.py` | Ежедневный ZIP |
| `app_paths.py` | Пути (в exe — рядом с .exe) |
| `config.json` | Склады, пути, дата бэкапа |
| `db/inventory.db` | База данных |
| `backups/` | `backup_YYYY-MM-DD.zip` |
| `reports/` | PDF-отчёты |
| `../shablon/` | Excel-шаблон номенклатуры (колонка B — наименование) |

В сборке exe шаблон лежит в `shablon\` рядом с exe.

## Шаблон номенклатуры

1. Положите `.xlsx` в папку `shablon` (в разработке — `single_sheet\shablon`).
2. Первая строка — заголовок; наименования — со 2-й строки, колонка B.
3. При пустой дате/складе все позиции шаблона показываются всегда; данные из БД подставляются в совпадающие строки.

## Очистка архивов

Папка `backups/` растёт со временем. Периодически удаляйте старые ZIP вручную, например старше 30 дней:

```powershell
cd d:\20260725_work\single_sheet\inventory_app\backups
Get-ChildItem *.zip | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item
```

## Критерии приёмки

| # | Критерий | Статус |
|---|----------|--------|
| 1 | Работа офлайн | `acceptance_check.py` |
| 2 | Мгновенный расчёт остатка | да |
| 3 | Фильтр склад + дата; имена всегда | да |
| 4 | Один ZIP-бэкап в день | да |
| 5 | PDF в `reports/` | да |
| 6 | Данные сохраняются после перезапуска | да |
