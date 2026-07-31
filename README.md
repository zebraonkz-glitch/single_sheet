# single_sheet

Офлайн-десктопное приложение складского учёта (Python + SQLite + PyQt6).

Рабочий код: каталог [`inventory_app/`](inventory_app/). Спецификация: [`project.md`](project.md), план: [`plan.md`](plan.md).

## Быстрый старт (PowerShell)

```powershell
cd d:\20260725_work\single_sheet\inventory_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Приёмка: `python acceptance_check.py`  
Сборка exe: `.\build.ps1`

Подробности — в [`inventory_app/README.md`](inventory_app/README.md).
