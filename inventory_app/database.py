"""
Модуль работы с SQLite: схема, CRUD, фильтры, шаблон номенклатуры.

Правило для пустой выборки: строки из шаблона возвращаются в памяти
без INSERT (id=None) до первого редактирования/сохранения.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app_paths import ensure_directories, get_paths, load_config

# Числовые поля строки операции (кроме id и названий)
NUMERIC_FIELDS = (
    "initial_stock",
    "incoming",
    "move_stock",
    "consumption_1",
    "consumption_2",
    "consumption_3",
    "final_stock",
)

ROW_FIELDS = (
    "id",
    "item_name",
    *NUMERIC_FIELDS,
    "warehouse_id",
    "operation_date",
)


def calc_final_stock(
    initial_stock: float = 0,
    incoming: float = 0,
    move_stock: float = 0,
    consumption_1: float = 0,
    consumption_2: float = 0,
    consumption_3: float = 0,
    **_: Any,
) -> float:
    """
    Остаток на конец =
    остаток на начало + приход + перемещение - (расход1 + расход2 + расход3).
    """
    return (
        float(initial_stock or 0)
        + float(incoming or 0)
        + float(move_stock or 0)
        - (
            float(consumption_1 or 0)
            + float(consumption_2 or 0)
            + float(consumption_3 or 0)
        )
    )


def _normalize_date(value: date | datetime | str) -> str:
    """Приводит дату к строке YYYY-MM-DD для SQLite."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _empty_template_row(
    item_name: str,
    warehouse_id: str,
    operation_date: str,
) -> dict[str, Any]:
    """Черновик строки из шаблона (ещё не в БД)."""
    row = {
        "id": None,
        "item_name": item_name,
        "initial_stock": 0.0,
        "incoming": 0.0,
        "move_stock": 0.0,
        "consumption_1": 0.0,
        "consumption_2": 0.0,
        "consumption_3": 0.0,
        "final_stock": 0.0,
        "warehouse_id": warehouse_id,
        "operation_date": operation_date,
    }
    row["final_stock"] = calc_final_stock(**row)
    return row


class Database:
    """Обёртка над SQLite для учёта операций по складам."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        shablon_dir: Path | str | None = None,
    ) -> None:
        config = load_config()
        paths = ensure_directories(config)

        self.db_path = Path(db_path) if db_path else paths["db"]
        self.shablon_dir = Path(shablon_dir) if shablon_dir else paths["shablon"]
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        """Открывает соединение с поддержкой Row и внешних ключей."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        """Создаёт таблицу operations и индекс, если их ещё нет."""
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_name TEXT NOT NULL,
                    initial_stock REAL DEFAULT 0,
                    incoming REAL DEFAULT 0,
                    move_stock REAL DEFAULT 0,
                    consumption_1 REAL DEFAULT 0,
                    consumption_2 REAL DEFAULT 0,
                    consumption_3 REAL DEFAULT 0,
                    final_stock REAL DEFAULT 0,
                    warehouse_id TEXT NOT NULL,
                    operation_date DATE NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_warehouse_date
                ON operations(warehouse_id, operation_date)
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Шаблон номенклатуры
    # ------------------------------------------------------------------

    def load_template_item_names(self) -> list[str]:
        """
        Читает наименования из xlsx в папке shablon.
        Ожидаемые колонки: A=№, B=наименование (как в Excel-шаблоне).
        """
        from openpyxl import load_workbook

        if not self.shablon_dir.exists():
            return []

        xlsx_files = sorted(self.shablon_dir.glob("*.xlsx"))
        # Игнорируем временные файлы Excel (~$...)
        xlsx_files = [p for p in xlsx_files if not p.name.startswith("~$")]
        if not xlsx_files:
            return []

        workbook = load_workbook(xlsx_files[0], data_only=True, read_only=True)
        try:
            sheet = workbook.active
            names: list[str] = []
            seen: set[str] = set()
            for row in sheet.iter_rows(min_row=2, max_col=2, values_only=True):
                raw = row[1] if row else None
                if raw is None:
                    continue
                name = str(raw).strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                names.append(name)
            return names
        finally:
            workbook.close()

    def load_nomenclature_names(self) -> list[str]:
        """
        Полный список наименований для отображения.
        Приоритет: Excel-шаблон; если пуст — уникальные имена из БД.
        """
        names = self.load_template_item_names()
        if names:
            return names

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT item_name, MIN(id) AS first_id
                FROM operations
                GROUP BY item_name
                ORDER BY first_id
                """
            ).fetchall()
        return [str(r["item_name"]) for r in rows]

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    def get_data(
        self,
        warehouse_id: str,
        operation_date: date | datetime | str,
        *,
        fill_from_template: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Возвращает строки за склад и дату.

        При fill_from_template=True наименования показываются всегда
        (шаблон или номенклатура из БД): сохранённые строки подставляются,
        остальные — черновики (id=None) с initial_stock с предыдущего дня.
        Позиции вне списка номенклатуры (добавленные вручную) — в конце.
        """
        op_date = _normalize_date(operation_date)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    item_name,
                    initial_stock,
                    incoming,
                    move_stock,
                    consumption_1,
                    consumption_2,
                    consumption_3,
                    final_stock,
                    warehouse_id,
                    operation_date
                FROM operations
                WHERE warehouse_id = ? AND operation_date = ?
                ORDER BY id
                """,
                (warehouse_id, op_date),
            ).fetchall()

        db_rows = [_row_to_dict(r) for r in rows]
        if not fill_from_template:
            return db_rows  # type: ignore[return-value]

        by_name: dict[str, dict[str, Any]] = {}
        for row in db_rows:
            if row is None:
                continue
            by_name[str(row["item_name"])] = row

        nomenclature = self.load_nomenclature_names()
        prev_map = self.get_previous_final_map(warehouse_id, op_date)

        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        for name in nomenclature:
            seen.add(name)
            if name in by_name:
                result.append(by_name[name])
                continue
            draft = _empty_template_row(name, warehouse_id, op_date)
            if name in prev_map:
                draft["initial_stock"] = prev_map[name]
                draft["final_stock"] = calc_final_stock(**draft)
            result.append(draft)

        # Ручные позиции, которых нет в шаблоне
        for row in db_rows:
            if row is None:
                continue
            name = str(row["item_name"])
            if name not in seen:
                result.append(row)

        return result

    def get_previous_final_map(
        self,
        warehouse_id: str,
        operation_date: date | datetime | str,
    ) -> dict[str, float]:
        """
        Остатки на конец за ближайший предыдущий день по складу.
        Один запрос: item_name -> final_stock.
        """
        op_date = _normalize_date(operation_date)
        with self.connect() as conn:
            prev = conn.execute(
                """
                SELECT MAX(operation_date) AS prev_date
                FROM operations
                WHERE warehouse_id = ? AND operation_date < ?
                """,
                (warehouse_id, op_date),
            ).fetchone()
            if not prev or not prev["prev_date"]:
                return {}

            rows = conn.execute(
                """
                SELECT item_name, final_stock
                FROM operations
                WHERE warehouse_id = ? AND operation_date = ?
                """,
                (warehouse_id, prev["prev_date"]),
            ).fetchall()

        return {
            str(r["item_name"]): float(r["final_stock"] or 0)
            for r in rows
        }

    def get_other_warehouse_id(self, warehouse_id: str) -> str | None:
        """Второй склад из config (A <-> B)."""
        config = load_config()
        ids = [str(w["id"]) for w in config.get("warehouses", [])]
        others = [wid for wid in ids if wid != str(warehouse_id)]
        return others[0] if others else None

    def get_row(self, row_id: int) -> dict[str, Any] | None:
        """Возвращает одну строку по id."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM operations WHERE id = ?",
                (row_id,),
            ).fetchone()
        return _row_to_dict(row)

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    def save_row(self, data: dict[str, Any]) -> int:
        """
        INSERT или UPDATE одной строки.
        final_stock пересчитывается в Python перед записью.
        Возвращает id записи.
        """
        payload = self._prepare_payload(data)
        row_id = payload.get("id")

        with self.connect() as conn:
            if row_id:
                conn.execute(
                    """
                    UPDATE operations SET
                        item_name = ?,
                        initial_stock = ?,
                        incoming = ?,
                        move_stock = ?,
                        consumption_1 = ?,
                        consumption_2 = ?,
                        consumption_3 = ?,
                        final_stock = ?,
                        warehouse_id = ?,
                        operation_date = ?
                    WHERE id = ?
                    """,
                    (
                        payload["item_name"],
                        payload["initial_stock"],
                        payload["incoming"],
                        payload["move_stock"],
                        payload["consumption_1"],
                        payload["consumption_2"],
                        payload["consumption_3"],
                        payload["final_stock"],
                        payload["warehouse_id"],
                        payload["operation_date"],
                        row_id,
                    ),
                )
                conn.commit()
                return int(row_id)

            cursor = conn.execute(
                """
                INSERT INTO operations (
                    item_name,
                    initial_stock,
                    incoming,
                    move_stock,
                    consumption_1,
                    consumption_2,
                    consumption_3,
                    final_stock,
                    warehouse_id,
                    operation_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["item_name"],
                    payload["initial_stock"],
                    payload["incoming"],
                    payload["move_stock"],
                    payload["consumption_1"],
                    payload["consumption_2"],
                    payload["consumption_3"],
                    payload["final_stock"],
                    payload["warehouse_id"],
                    payload["operation_date"],
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def upsert_row(self, data: dict[str, Any]) -> int:
        """
        Сохраняет строку: по id, иначе ищет по (item_name, warehouse, date).
        Удобно для автосохранения черновиков из шаблона.
        """
        payload = self._prepare_payload(data)
        row_id = payload.get("id")
        if row_id:
            return self.save_row(payload)

        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM operations
                WHERE item_name = ? AND warehouse_id = ? AND operation_date = ?
                """,
                (
                    payload["item_name"],
                    payload["warehouse_id"],
                    payload["operation_date"],
                ),
            ).fetchone()

        if existing:
            payload["id"] = existing["id"]
        return self.save_row(payload)

    def save_rows(self, rows: list[dict[str, Any]]) -> list[int]:
        """Пакетное сохранение в одной транзакции BEGIN/COMMIT."""
        ids: list[int] = []
        with self.connect() as conn:
            conn.execute("BEGIN")
            try:
                for data in rows:
                    payload = self._prepare_payload(data)
                    row_id = payload.get("id")
                    if row_id:
                        conn.execute(
                            """
                            UPDATE operations SET
                                item_name = ?,
                                initial_stock = ?,
                                incoming = ?,
                                move_stock = ?,
                                consumption_1 = ?,
                                consumption_2 = ?,
                                consumption_3 = ?,
                                final_stock = ?,
                                warehouse_id = ?,
                                operation_date = ?
                            WHERE id = ?
                            """,
                            (
                                payload["item_name"],
                                payload["initial_stock"],
                                payload["incoming"],
                                payload["move_stock"],
                                payload["consumption_1"],
                                payload["consumption_2"],
                                payload["consumption_3"],
                                payload["final_stock"],
                                payload["warehouse_id"],
                                payload["operation_date"],
                                row_id,
                            ),
                        )
                        ids.append(int(row_id))
                    else:
                        existing = conn.execute(
                            """
                            SELECT id FROM operations
                            WHERE item_name = ?
                              AND warehouse_id = ?
                              AND operation_date = ?
                            """,
                            (
                                payload["item_name"],
                                payload["warehouse_id"],
                                payload["operation_date"],
                            ),
                        ).fetchone()
                        if existing:
                            conn.execute(
                                """
                                UPDATE operations SET
                                    item_name = ?,
                                    initial_stock = ?,
                                    incoming = ?,
                                    move_stock = ?,
                                    consumption_1 = ?,
                                    consumption_2 = ?,
                                    consumption_3 = ?,
                                    final_stock = ?,
                                    warehouse_id = ?,
                                    operation_date = ?
                                WHERE id = ?
                                """,
                                (
                                    payload["item_name"],
                                    payload["initial_stock"],
                                    payload["incoming"],
                                    payload["move_stock"],
                                    payload["consumption_1"],
                                    payload["consumption_2"],
                                    payload["consumption_3"],
                                    payload["final_stock"],
                                    payload["warehouse_id"],
                                    payload["operation_date"],
                                    existing["id"],
                                ),
                            )
                            ids.append(int(existing["id"]))
                        else:
                            cursor = conn.execute(
                                """
                                INSERT INTO operations (
                                    item_name,
                                    initial_stock,
                                    incoming,
                                    move_stock,
                                    consumption_1,
                                    consumption_2,
                                    consumption_3,
                                    final_stock,
                                    warehouse_id,
                                    operation_date
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    payload["item_name"],
                                    payload["initial_stock"],
                                    payload["incoming"],
                                    payload["move_stock"],
                                    payload["consumption_1"],
                                    payload["consumption_2"],
                                    payload["consumption_3"],
                                    payload["final_stock"],
                                    payload["warehouse_id"],
                                    payload["operation_date"],
                                ),
                            )
                            ids.append(int(cursor.lastrowid))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return ids

    def delete_row(self, row_id: int) -> bool:
        """Удаляет строку по id. True — если строка была удалена."""
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM operations WHERE id = ?",
                (row_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Отчёты
    # ------------------------------------------------------------------

    def report_movements(
        self,
        warehouse_id: str,
        date_from: date | datetime | str,
        date_to: date | datetime | str,
    ) -> list[dict[str, Any]]:
        """
        Движение товаров за период (один SQL-запрос).
        Поля: operation_date, item_name, incoming, consumption, move_stock, final_stock.
        """
        d_from = _normalize_date(date_from)
        d_to = _normalize_date(date_to)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    operation_date AS operation_date,
                    item_name AS item_name,
                    incoming AS incoming,
                    (consumption_1 + consumption_2 + consumption_3) AS consumption,
                    move_stock AS move_stock,
                    final_stock AS final_stock
                FROM operations
                WHERE warehouse_id = ?
                  AND operation_date >= ?
                  AND operation_date <= ?
                ORDER BY operation_date, item_name, id
                """,
                (warehouse_id, d_from, d_to),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]  # type: ignore[misc]

    def report_stock(
        self,
        warehouse_id: str,
        as_of_date: date | datetime | str,
    ) -> list[dict[str, Any]]:
        """
        Актуальные остатки на дату.
        Все наименования номенклатуры + final_stock (из БД или черновик).
        """
        rows = self.get_data(warehouse_id, as_of_date, fill_from_template=True)
        return [
            {
                "item_name": r["item_name"],
                "final_stock": float(r.get("final_stock") or 0),
                "initial_stock": float(r.get("initial_stock") or 0),
                "incoming": float(r.get("incoming") or 0),
                "move_stock": float(r.get("move_stock") or 0),
                "consumption": (
                    float(r.get("consumption_1") or 0)
                    + float(r.get("consumption_2") or 0)
                    + float(r.get("consumption_3") or 0)
                ),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Вспомогательные
    # ------------------------------------------------------------------

    def _prepare_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        """Нормализует поля и считает final_stock."""
        if not data.get("item_name"):
            raise ValueError("Поле item_name обязательно")
        if not data.get("warehouse_id"):
            raise ValueError("Поле warehouse_id обязательно")
        if not data.get("operation_date"):
            raise ValueError("Поле operation_date обязательно")

        payload: dict[str, Any] = {
            "id": data.get("id"),
            "item_name": str(data["item_name"]).strip(),
            "warehouse_id": str(data["warehouse_id"]).strip(),
            "operation_date": _normalize_date(data["operation_date"]),
        }
        for field in NUMERIC_FIELDS:
            if field == "final_stock":
                continue
            payload[field] = float(data.get(field) or 0)

        payload["final_stock"] = calc_final_stock(**payload)
        return payload


def _demo() -> None:
    """Простая проверка CRUD из командной строки."""
    import sys

    sys.stdout.reconfigure(encoding="utf-8")

    db = Database()
    print(f"DB: {db.db_path}")
    print(f"Shablon: {db.shablon_dir}")

    names = db.load_nomenclature_names()
    print(f"Позиций в номенклатуре: {len(names)}")
    if names:
        print(f"Первая: {names[0]}")

    today = date.today().isoformat()
    rows = db.get_data("A", today)
    print(f"get_data(A, {today}): {len(rows)} строк (шаблон + БД)")
    assert len(rows) >= len(names), "Наименования должны отображаться всегда"

    sample = {
        "item_name": names[0] if names else "Тестовый товар",
        "initial_stock": 10,
        "incoming": 5,
        "move_stock": -2,
        "consumption_1": 1,
        "consumption_2": 0,
        "consumption_3": 0.5,
        "warehouse_id": "A",
        "operation_date": today,
    }
    row_id = db.upsert_row(sample)
    saved = db.get_row(row_id)
    print(f"upsert id={row_id}, final_stock={saved['final_stock']}")

    expected = calc_final_stock(**sample)
    assert abs(saved["final_stock"] - expected) < 1e-9, "Неверный final_stock"

    deleted = db.delete_row(row_id)
    print(f"delete_row: {deleted}")
    print("OK: CRUD проверен")


if __name__ == "__main__":
    _demo()
