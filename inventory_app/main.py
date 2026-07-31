"""
Точка входа и главное окно складского учёта (PyQt6).

Вкладки «Учёт» / «Отчёты», авторасчёт, валидация, PDF, closeEvent.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QDate, QRegularExpression, QUrl, Qt
from PyQt6.QtGui import QCloseEvent, QColor, QDesktopServices, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_paths import ensure_directories, load_config
from archiver import on_app_close
from database import Database, calc_final_stock
from pdf_generator import generate_movements_pdf, generate_stock_pdf

# Индексы колонок таблицы учёта
COL_ID = 0
COL_NAME = 1
COL_INITIAL = 2
COL_INCOMING = 3
COL_MOVE = 4
COL_CONS1 = 5
COL_CONS2 = 6
COL_CONS3 = 7
COL_FINAL = 8

COLUMN_HEADERS = [
    "№",
    "Наименование",
    "Остаток на начало",
    "Приход",
    "Перемещение",
    "Расход 1",
    "Расход 2",
    "Расход 3",
    "Остаток на конец",
]

NUMERIC_COL_TO_FIELD = {
    COL_INITIAL: "initial_stock",
    COL_INCOMING: "incoming",
    COL_MOVE: "move_stock",
    COL_CONS1: "consumption_1",
    COL_CONS2: "consumption_2",
    COL_CONS3: "consumption_3",
}

NUMERIC_COLUMNS = set(NUMERIC_COL_TO_FIELD.keys())

REPORT_MOVEMENTS = "movements"
REPORT_STOCK = "stock"

# Число: опциональный минус, цифры, одна точка или запятая
NUMBER_PATTERN = QRegularExpression(r"^-?\d*([.,]\d*)?$")


def _fmt_number(value: Any) -> str:
    """Форматирует число для ячейки (без лишних нулей)."""
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if num == int(num):
        return str(int(num))
    return f"{num:.4f}".rstrip("0").rstrip(".")


def _parse_number(text: str) -> float | None:
    """Парсит число из текста ячейки. None — если некорректно."""
    raw = (text or "").replace(",", ".").strip()
    if raw in {"", "-", ".", "-."}:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return None


class NumberDelegate(QStyledItemDelegate):
    """Разрешает ввод только чисел (с минусом и десятичным разделителем)."""

    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: Any,
    ) -> QWidget:
        editor = QLineEdit(parent)
        editor.setValidator(QRegularExpressionValidator(NUMBER_PATTERN, editor))
        editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        return editor

    def setModelData(self, editor: QWidget, model: Any, index: Any) -> None:
        if isinstance(editor, QLineEdit):
            value = _parse_number(editor.text())
            if value is None:
                return  # оставляем старое значение
            model.setData(index, _fmt_number(value), Qt.ItemDataRole.EditRole)
        else:
            super().setModelData(editor, model, index)


class MainWindow(QMainWindow):
    """Главное окно: учёт по складу/дате и заготовка вкладки отчётов."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Складской учёт")
        self.resize(1100, 700)

        self.config = load_config()
        ensure_directories(self.config)
        self.db = Database()

        self._loading = False  # блокировка реакций при программном заполнении
        self._move_prompt_armed = True  # диалог перемещения только после правки пользователя
        self._report_rows: list[dict[str, Any]] = []
        self._last_pdf_path: Path | None = None

        self._build_ui()
        self._load_table()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        tabs.addTab(self._build_inventory_tab(), "Учёт")
        tabs.addTab(self._build_reports_tab(), "Отчёты")

    def _build_inventory_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        header = QHBoxLayout()
        header.addWidget(QLabel("Склад:"))

        self.warehouse_combo = QComboBox()
        for wh in self.config.get("warehouses", []):
            self.warehouse_combo.addItem(wh.get("name", wh["id"]), wh["id"])
        self.warehouse_combo.currentIndexChanged.connect(self._on_filter_changed)
        header.addWidget(self.warehouse_combo)

        header.addSpacing(16)
        header.addWidget(QLabel("Дата:"))

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.dateChanged.connect(self._on_filter_changed)
        header.addWidget(self.date_edit)

        header.addStretch()
        layout.addLayout(header)

        self.table = QTableWidget(0, len(COLUMN_HEADERS))
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        # Валидация числовых колонок
        self._number_delegate = NumberDelegate(self.table)
        for col in NUMERIC_COLUMNS:
            self.table.setItemDelegateForColumn(col, self._number_delegate)

        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in range(len(COLUMN_HEADERS)):
            if col != COL_NAME:
                header_view.setSectionResizeMode(
                    col, QHeaderView.ResizeMode.ResizeToContents
                )

        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        btn_add = QPushButton("Добавить строку")
        btn_add.clicked.connect(self._add_row)
        buttons.addWidget(btn_add)

        btn_delete = QPushButton("Удалить строку")
        btn_delete.clicked.connect(self._delete_row)
        buttons.addWidget(btn_delete)

        buttons.addStretch()

        btn_save = QPushButton("Сохранить всё")
        btn_save.clicked.connect(self._save_all)
        buttons.addWidget(btn_save)

        layout.addLayout(buttons)
        return page

    def _build_reports_tab(self) -> QWidget:
        """Вкладка отчётов: фильтры, превью, PDF."""
        page = QWidget()
        layout = QVBoxLayout(page)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Склад:"))
        self.report_warehouse = QComboBox()
        for wh in self.config.get("warehouses", []):
            self.report_warehouse.addItem(wh.get("name", wh["id"]), wh["id"])
        filters.addWidget(self.report_warehouse)

        filters.addSpacing(12)
        filters.addWidget(QLabel("Отчёт:"))
        self.report_type = QComboBox()
        self.report_type.addItem("Движение товаров", REPORT_MOVEMENTS)
        self.report_type.addItem("Актуальные остатки", REPORT_STOCK)
        self.report_type.currentIndexChanged.connect(self._on_report_type_changed)
        filters.addWidget(self.report_type)

        filters.addSpacing(12)
        self.report_from_label = QLabel("Дата от:")
        filters.addWidget(self.report_from_label)
        self.report_date_from = QDateEdit()
        self.report_date_from.setCalendarPopup(True)
        self.report_date_from.setDisplayFormat("dd.MM.yyyy")
        self.report_date_from.setDate(QDate.currentDate())
        filters.addWidget(self.report_date_from)

        self.report_to_label = QLabel("Дата до:")
        filters.addWidget(self.report_to_label)
        self.report_date_to = QDateEdit()
        self.report_date_to.setCalendarPopup(True)
        self.report_date_to.setDisplayFormat("dd.MM.yyyy")
        self.report_date_to.setDate(QDate.currentDate())
        filters.addWidget(self.report_date_to)

        filters.addStretch()
        layout.addLayout(filters)

        self.report_table = QTableWidget(0, 0)
        self.report_table.setAlternatingRowColors(True)
        self.report_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.report_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.report_table)

        buttons = QHBoxLayout()
        btn_show = QPushButton("Сформировать")
        btn_show.clicked.connect(self._build_report_preview)
        buttons.addWidget(btn_show)

        btn_pdf = QPushButton("Сформировать PDF")
        btn_pdf.clicked.connect(self._export_report_pdf)
        buttons.addWidget(btn_pdf)

        btn_print = QPushButton("Печать…")
        btn_print.setToolTip("Открыть последний PDF для печати в системной программе")
        btn_print.clicked.connect(self._print_last_report)
        buttons.addWidget(btn_print)

        buttons.addStretch()
        self.report_status = QLabel("")
        buttons.addWidget(self.report_status)
        layout.addLayout(buttons)

        self._on_report_type_changed()
        return page

    def _qdate_to_date(self, qd: QDate) -> date:
        return date(qd.year(), qd.month(), qd.day())

    def _on_report_type_changed(self, *_args: Any) -> None:
        is_movements = self.report_type.currentData() == REPORT_MOVEMENTS
        self.report_from_label.setVisible(is_movements)
        self.report_date_from.setVisible(is_movements)
        self.report_to_label.setText("Дата до:" if is_movements else "На дату:")

    def _build_report_preview(self) -> None:
        """Загружает данные отчёта в таблицу превью."""
        warehouse_id = str(self.report_warehouse.currentData())
        date_from = self._qdate_to_date(self.report_date_from.date())
        date_to = self._qdate_to_date(self.report_date_to.date())
        if date_from > date_to:
            QMessageBox.warning(self, "Отчёт", "Дата «от» не может быть позже даты «до».")
            return

        report_kind = self.report_type.currentData()
        try:
            if report_kind == REPORT_MOVEMENTS:
                self._report_rows = self.db.report_movements(
                    warehouse_id, date_from, date_to
                )
                headers = [
                    "Дата",
                    "Товар",
                    "Приход",
                    "Расход",
                    "Перемещение",
                    "Итог",
                ]
                keys = [
                    "operation_date",
                    "item_name",
                    "incoming",
                    "consumption",
                    "move_stock",
                    "final_stock",
                ]
            else:
                self._report_rows = self.db.report_stock(warehouse_id, date_to)
                headers = ["Наименование", "Остаток"]
                keys = ["item_name", "final_stock"]
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Отчёт", str(exc))
            return

        self.report_table.clear()
        self.report_table.setColumnCount(len(headers))
        self.report_table.setHorizontalHeaderLabels(headers)
        self.report_table.setRowCount(len(self._report_rows))

        for r, data in enumerate(self._report_rows):
            for c, key in enumerate(keys):
                value = data.get(key)
                if key == "operation_date":
                    text = self._fmt_report_date(value)
                elif key == "item_name":
                    text = str(value or "")
                else:
                    text = _fmt_number(value)
                item = QTableWidgetItem(text)
                if key != "item_name" and key != "operation_date":
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                self.report_table.setItem(r, c, item)

        header = self.report_table.horizontalHeader()
        if report_kind == REPORT_STOCK:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        self.report_status.setText(f"Строк: {len(self._report_rows)}")

    def _fmt_report_date(self, value: Any) -> str:
        text = str(value or "")[:10]
        try:
            return date.fromisoformat(text).strftime("%d.%m.%Y")
        except ValueError:
            return text

    def _export_report_pdf(self) -> None:
        """Формирует PDF текущего отчёта в папку reports/."""
        # Обновляем данные перед экспортом
        self._build_report_preview()
        if self.report_type.currentData() == REPORT_MOVEMENTS and not self._report_rows:
            answer = QMessageBox.question(
                self,
                "PDF",
                "Нет движений за период. Всё равно создать PDF?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        warehouse_id = str(self.report_warehouse.currentData())
        warehouse_name = self._warehouse_name(warehouse_id)
        date_from = self._qdate_to_date(self.report_date_from.date())
        date_to = self._qdate_to_date(self.report_date_to.date())

        try:
            if self.report_type.currentData() == REPORT_MOVEMENTS:
                path = generate_movements_pdf(
                    self._report_rows,
                    warehouse_name=warehouse_name,
                    date_from=date_from,
                    date_to=date_to,
                )
            else:
                path = generate_stock_pdf(
                    self._report_rows,
                    warehouse_name=warehouse_name,
                    as_of_date=date_to,
                )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "PDF", str(exc))
            return

        self._last_pdf_path = path
        self.report_status.setText(f"PDF: {path.name}")
        answer = QMessageBox.information(
            self,
            "PDF",
            f"Файл сохранён:\n{path}\n\nОткрыть?",
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Close,
            QMessageBox.StandardButton.Open,
        )
        if answer == QMessageBox.StandardButton.Open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _print_last_report(self) -> None:
        """Открывает последний PDF — печать через системный просмотрщик."""
        if self._last_pdf_path is None or not self._last_pdf_path.is_file():
            QMessageBox.information(
                self,
                "Печать",
                "Сначала сформируйте PDF-отчёт.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_pdf_path)))

    # ------------------------------------------------------------------
    # Фильтры и загрузка
    # ------------------------------------------------------------------

    def _current_warehouse_id(self) -> str:
        return str(self.warehouse_combo.currentData())

    def _current_date(self) -> date:
        qd = self.date_edit.date()
        return date(qd.year(), qd.month(), qd.day())

    def _warehouse_name(self, warehouse_id: str) -> str:
        for wh in self.config.get("warehouses", []):
            if str(wh.get("id")) == str(warehouse_id):
                return str(wh.get("name", warehouse_id))
        return warehouse_id

    def _on_filter_changed(self, *_args: Any) -> None:
        self._load_table()

    def _load_table(self) -> None:
        """Заполняет таблицу данными БД (или шаблоном) для склада и даты."""
        self._loading = True
        try:
            rows = self.db.get_data(
                self._current_warehouse_id(),
                self._current_date(),
            )
            self.table.setRowCount(0)
            self.table.setRowCount(len(rows))
            for r, data in enumerate(rows):
                self._write_row(r, data)
        finally:
            self._loading = False

    def _write_row(self, row: int, data: dict[str, Any]) -> None:
        """Пишет словарь операции в строку таблицы."""
        row_id = data.get("id")
        id_text = "" if row_id is None else str(row_id)
        id_item = QTableWidgetItem(id_text)
        id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if row_id is not None:
            id_item.setData(Qt.ItemDataRole.UserRole, int(row_id))
        self.table.setItem(row, COL_ID, id_item)

        name_item = QTableWidgetItem(str(data.get("item_name") or ""))
        self.table.setItem(row, COL_NAME, name_item)

        for col, field in NUMERIC_COL_TO_FIELD.items():
            item = QTableWidgetItem(_fmt_number(data.get(field, 0)))
            item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            )
            self.table.setItem(row, col, item)

        final = data.get("final_stock")
        if final is None:
            final = calc_final_stock(**data)
        final_item = QTableWidgetItem(_fmt_number(final))
        final_item.setFlags(final_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        final_item.setTextAlignment(
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        )
        self.table.setItem(row, COL_FINAL, final_item)
        self._apply_final_style(row, float(final))

    def _read_row(self, row: int) -> dict[str, Any] | None:
        """Читает строку таблицы в словарь для БД. None — если нет наименования."""
        name_item = self.table.item(row, COL_NAME)
        name = (name_item.text() if name_item else "").strip()
        if not name:
            return None

        id_item = self.table.item(row, COL_ID)
        row_id = None
        if id_item is not None:
            stored = id_item.data(Qt.ItemDataRole.UserRole)
            if stored is not None:
                row_id = int(stored)

        data: dict[str, Any] = {
            "id": row_id,
            "item_name": name,
            "warehouse_id": self._current_warehouse_id(),
            "operation_date": self._current_date().isoformat(),
        }
        for col, field in NUMERIC_COL_TO_FIELD.items():
            item = self.table.item(row, col)
            parsed = _parse_number(item.text() if item else "0")
            data[field] = 0.0 if parsed is None else parsed
        data["final_stock"] = calc_final_stock(**data)
        return data

    def _apply_final_style(self, row: int, final_value: float) -> None:
        """Красный текст при отрицательном остатке на конец."""
        item = self.table.item(row, COL_FINAL)
        if item is None:
            return
        if final_value < 0:
            item.setForeground(QColor(180, 0, 0))
        else:
            item.setForeground(QColor(0, 0, 0))

    def _update_final_cell(self, row: int) -> float:
        """Пересчитывает и показывает «Остаток на конец» для строки."""
        data = self._read_row(row)
        if data is None:
            # Даже без имени считаем по числам
            values = {}
            for col, field in NUMERIC_COL_TO_FIELD.items():
                item = self.table.item(row, col)
                parsed = _parse_number(item.text() if item else "0")
                values[field] = 0.0 if parsed is None else parsed
            final = calc_final_stock(**values)
        else:
            final = float(data["final_stock"])

        self._loading = True
        try:
            item = self.table.item(row, COL_FINAL)
            if item is None:
                item = QTableWidgetItem()
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                )
                self.table.setItem(row, COL_FINAL, item)
            item.setText(_fmt_number(final))
            self._apply_final_style(row, final)
        finally:
            self._loading = False
        return final

    def _autosave_row(self, row: int) -> None:
        """Сохраняет строку в БД (upsert) и обновляет №."""
        data = self._read_row(row)
        if data is None:
            return
        try:
            row_id = self.db.upsert_row(data)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", str(exc))
            return

        self._loading = True
        try:
            id_item = self.table.item(row, COL_ID)
            if id_item is None:
                id_item = QTableWidgetItem()
                id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, COL_ID, id_item)
            id_item.setText(str(row_id))
            id_item.setData(Qt.ItemDataRole.UserRole, row_id)
        finally:
            self._loading = False

    # ------------------------------------------------------------------
    # itemChanged
    # ------------------------------------------------------------------

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item is None:
            return

        row = item.row()
        col = item.column()

        # id и final не редактируются; имя — только автосохранение
        if col == COL_ID or col == COL_FINAL:
            return

        if col in NUMERIC_COLUMNS:
            parsed = _parse_number(item.text())
            if parsed is None:
                self._loading = True
                try:
                    item.setText("0")
                finally:
                    self._loading = False
                parsed = 0.0
            else:
                formatted = _fmt_number(parsed)
                if item.text() != formatted:
                    self._loading = True
                    try:
                        item.setText(formatted)
                    finally:
                        self._loading = False

            self._update_final_cell(row)

            # Диалог парного перемещения
            if col == COL_MOVE and self._move_prompt_armed and parsed != 0:
                self._offer_pair_move(row, parsed)

        # Автосохранение при любом осмысленном изменении строки с наименованием
        self._autosave_row(row)

    def _offer_pair_move(self, row: int, move_value: float) -> None:
        """Предлагает создать зеркальную запись на другом складе."""
        name_item = self.table.item(row, COL_NAME)
        item_name = (name_item.text() if name_item else "").strip()
        if not item_name:
            return

        other_id = self.db.get_other_warehouse_id(self._current_warehouse_id())
        if not other_id:
            return

        other_name = self._warehouse_name(other_id)
        sign_hint = f"+{abs(move_value)}" if move_value < 0 else f"-{abs(move_value)}"
        answer = QMessageBox.question(
            self,
            "Перемещение между складами",
            (
                f"Вы указали перемещение {_fmt_number(move_value)} ед. для «{item_name}».\n"
                f"Создать на «{other_name}» запись с перемещением {sign_hint}?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        op_date = self._current_date().isoformat()
        # Берём уже существующую строку на другом складе (если есть) одним запросом
        other_rows = self.db.get_data(other_id, op_date, fill_from_template=False)
        existing = next(
            (r for r in other_rows if r.get("item_name") == item_name),
            None,
        )

        if existing:
            pair = dict(existing)
            pair["move_stock"] = -move_value
        else:
            prev_map = self.db.get_previous_final_map(other_id, op_date)
            pair = {
                "id": None,
                "item_name": item_name,
                "initial_stock": prev_map.get(item_name, 0.0),
                "incoming": 0.0,
                "move_stock": -move_value,
                "consumption_1": 0.0,
                "consumption_2": 0.0,
                "consumption_3": 0.0,
                "warehouse_id": other_id,
                "operation_date": op_date,
            }
        pair["final_stock"] = calc_final_stock(**pair)

        try:
            self.db.upsert_row(pair)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать парную запись:\n{exc}")

    # ------------------------------------------------------------------
    # Кнопки
    # ------------------------------------------------------------------

    def _add_row(self) -> None:
        """Добавляет пустую строку в конец таблицы."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        empty = {
            "id": None,
            "item_name": "",
            "initial_stock": 0,
            "incoming": 0,
            "move_stock": 0,
            "consumption_1": 0,
            "consumption_2": 0,
            "consumption_3": 0,
            "final_stock": 0,
        }
        self._loading = True
        try:
            self._write_row(row, empty)
        finally:
            self._loading = False
        self.table.setCurrentCell(row, COL_NAME)
        self.table.editItem(self.table.item(row, COL_NAME))

    def _delete_row(self) -> None:
        """Удаляет выбранную строку из таблицы и из БД (если уже сохранена)."""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Удаление", "Выберите строку для удаления.")
            return

        id_item = self.table.item(row, COL_ID)
        row_id = id_item.data(Qt.ItemDataRole.UserRole) if id_item else None
        name_item = self.table.item(row, COL_NAME)
        name = name_item.text() if name_item else f"строка {row + 1}"

        answer = QMessageBox.question(
            self,
            "Удаление",
            f"Удалить «{name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if row_id is not None:
            self.db.delete_row(int(row_id))
        self.table.removeRow(row)

    def _save_all(self) -> None:
        """Сохраняет все заполненные строки текущей таблицы в БД."""
        payload: list[dict[str, Any]] = []
        for row in range(self.table.rowCount()):
            data = self._read_row(row)
            if data is not None:
                payload.append(data)

        if not payload:
            QMessageBox.warning(self, "Сохранение", "Нет строк для сохранения.")
            return

        try:
            ids = self.db.save_rows(payload)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", str(exc))
            return

        self._loading = True
        try:
            saved_idx = 0
            for row in range(self.table.rowCount()):
                if self._read_row(row) is None:
                    continue
                row_id = ids[saved_idx]
                data = payload[saved_idx]
                saved_idx += 1

                id_item = self.table.item(row, COL_ID)
                if id_item is None:
                    id_item = QTableWidgetItem()
                    id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, COL_ID, id_item)
                id_item.setText(str(row_id))
                id_item.setData(Qt.ItemDataRole.UserRole, row_id)

                final_item = self.table.item(row, COL_FINAL)
                if final_item is not None:
                    final_item.setText(_fmt_number(data["final_stock"]))
                    self._apply_final_style(row, float(data["final_stock"]))
        finally:
            self._loading = False

        QMessageBox.information(
            self,
            "Сохранение",
            f"Сохранено строк: {len(ids)}",
        )

    # ------------------------------------------------------------------
    # Закрытие
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        """При закрытии окна — ежедневный ZIP-бэкап БД."""
        try:
            on_app_close()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Архивация",
                f"Не удалось создать резервную копию:\n{exc}",
            )
        event.accept()


def main() -> int:
    ensure_directories()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
