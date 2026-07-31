"""
Автоматическая проверка критериев приёмки (этап 7).

Запуск:
  python acceptance_check.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path

# Запрещённые сетевые модули в коде приложения
FORBIDDEN_IMPORTS = {
    "requests",
    "urllib",
    "urllib3",
    "http",
    "httpx",
    "aiohttp",
    "socket",
}


def _check_offline_sources(app_dir: Path) -> None:
    """В исходниках нет сетевых импортов."""
    for py_file in app_dir.glob("*.py"):
        if py_file.name == "acceptance_check.py":
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in FORBIDDEN_IMPORTS, (
                        f"{py_file.name}: запрещённый импорт {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in FORBIDDEN_IMPORTS, (
                    f"{py_file.name}: запрещённый импорт from {node.module}"
                )
    print("OK [1] Офлайн: сетевых импортов нет")


def _check_calc() -> None:
    from database import calc_final_stock

    assert calc_final_stock(10, 5, -2, 1, 0, 0.5) == 11.5
    assert calc_final_stock(0, 0, 0, 0, 0, 0) == 0
    print("OK [2] Расчёт final_stock")


def _check_filter_and_names() -> None:
    from database import Database

    db = Database()
    names = db.load_nomenclature_names()
    assert len(names) >= 1, "Нет номенклатуры (первый запуск: shablon/*.xlsx → каталог в БД)"

    today = date.today().isoformat()
    rows_a = db.get_data("A", today)
    rows_b = db.get_data("B", today)
    assert all(r["warehouse_id"] == "A" for r in rows_a if r.get("id"))
    assert len(rows_a) >= len(names)
    assert len(rows_b) >= len(names)
    print(f"OK [3] Фильтрация / наименования всегда ({len(names)} позиций)")


def _check_backup() -> None:
    from app_paths import save_config
    from archiver import perform_daily_backup

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_file = tmp_path / "inventory.db"
        backups = tmp_path / "backups"
        backups.mkdir()
        db_file.write_bytes(b"demo-db")
        cfg_path = tmp_path / "config.json"
        save_config(
            {
                "paths": {
                    "db": str(db_file),
                    "backups": str(backups),
                    "reports": str(tmp_path / "reports"),
                    "shablon": str(tmp_path / "shablon"),
                },
                "last_backup_date": None,
            },
            cfg_path,
        )
        day1 = date(2026, 1, 10)
        day2 = day1 + timedelta(days=1)
        first = perform_daily_backup(
            db_path=db_file,
            backups_dir=backups,
            today=day1,
            config_path=cfg_path,
        )
        assert first is not None
        second = perform_daily_backup(
            db_path=db_file,
            backups_dir=backups,
            today=day1,
            config_path=cfg_path,
        )
        assert second is None
        third = perform_daily_backup(
            db_path=db_file,
            backups_dir=backups,
            today=day2,
            config_path=cfg_path,
        )
        assert third is not None
        with zipfile.ZipFile(first, "r") as zf:
            assert "inventory.db" in zf.namelist()
    print("OK [4] Архивация: один ZIP в день")


def _check_reports() -> None:
    from database import Database
    from pdf_generator import generate_movements_pdf, generate_stock_pdf

    db = Database()
    today = date.today()
    movements = db.report_movements("A", today, today, detail_by="by_date")
    stock = db.report_stock("A", today)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        p1 = generate_movements_pdf(
            movements,
            warehouse_name="Склад А",
            date_from=today,
            date_to=today,
            detail_by="by_date",
            output_dir=out,
        )
        p2 = generate_stock_pdf(
            stock,
            warehouse_name="Склад А",
            as_of_date=today,
            output_dir=out,
        )
        assert p1.is_file() and p1.stat().st_size > 100
        assert p2.is_file() and p2.stat().st_size > 100
        assert p1.read_bytes()[:4] == b"%PDF"
        assert p2.read_bytes()[:4] == b"%PDF"
    by_item = db.report_movements("A", today, today, detail_by="by_item")
    assert isinstance(by_item, list)
    print("OK [5] Отчёты PDF")


def _check_integrity() -> None:
    from database import Database, calc_final_stock

    db = Database()
    today = date.today().isoformat()
    name = "__acceptance_item__"
    payload = {
        "item_name": name,
        "initial_stock": 3,
        "incoming": 4,
        "move_stock": 0,
        "consumption_1": 1,
        "consumption_2": 0,
        "consumption_3": 0,
        "warehouse_id": "A",
        "operation_date": today,
    }
    row_id = db.upsert_row(payload)
    db2 = Database()
    saved = db2.get_row(row_id)
    assert saved is not None
    assert saved["item_name"] == name
    assert abs(saved["final_stock"] - calc_final_stock(**payload)) < 1e-9
    db2.delete_row(row_id)
    assert db2.get_row(row_id) is None
    print("OK [6] Целостность данных после переподключения")


def _check_ui_smoke() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from main import MainWindow, COL_INCOMING, COL_FINAL
    from database import calc_final_stock

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.table.columnCount() == 8
    assert window.table.rowCount() >= 1
    row = 0
    window.table.item(row, COL_INCOMING).setText("7")
    data = window._read_row(row)
    assert data is not None
    assert abs(float(window.table.item(row, COL_FINAL).text().replace(",", "."))
               - calc_final_stock(**data)) < 1e-9
    window.close()
    print("OK [UI] Главное окно: таблица и авторасчёт")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    app_dir = Path(__file__).resolve().parent
    print("=== Приёмка: Складской учёт ===")
    _check_offline_sources(app_dir)
    _check_calc()
    _check_filter_and_names()
    _check_backup()
    _check_reports()
    _check_integrity()
    _check_ui_smoke()
    print("=== Все проверки пройдены ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
