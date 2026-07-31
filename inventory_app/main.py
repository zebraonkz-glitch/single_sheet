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
from PyQt6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFont,
    QRegularExpressionValidator,
)
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

from app_paths import ensure_directories, load_config, save_config
from archiver import on_app_close
from database import Database, calc_final_stock
from pdf_generator import generate_movements_pdf, generate_stock_pdf

# Индексы колонок таблицы учёта
COL_NAME = 0
COL_INITIAL = 1
COL_INCOMING = 2
COL_MOVE = 3
COL_CONS1 = 4
COL_CONS2 = 5
COL_CONS3 = 6
COL_FINAL = 7

# Служебные данные в ячейке «Наименование»
ROLE_ROW_ID = int(Qt.ItemDataRole.UserRole)
ROLE_ARCHIVED = int(Qt.ItemDataRole.UserRole) + 1

COLUMN_HEADERS = [
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
DETAIL_BY_DATE = "by_date"
DETAIL_BY_ITEM = "by_item"
ALL_WAREHOUSES = "*"

# Число: опциональный минус, цифры, одна точка или запятая
NUMBER_PATTERN = QRegularExpression(r"^-?\d*([.,]\d*)?$")

# Активная ячейка ярче выбранной строки
TABLE_CELL_STYLE = """
QTableWidget {
    gridline-color: #c5c5c5;
    alternate-background-color: #f5f7fa;
    selection-background-color: #dceafb;
    selection-color: #1a1a1a;
}
QTableWidget::item:selected {
    background-color: #dceafb;
    color: #1a1a1a;
}
QTableWidget::item:focus {
    background-color: #1a73e8;
    color: #ffffff;
}
QTableWidget::item:selected:focus {
    background-color: #1a73e8;
    color: #ffffff;
}
"""

ACTIVE_CELL_BG = QColor(26, 115, 232)
ACTIVE_CELL_FG = QColor(255, 255, 255)
ACTIVE_ROW_BG = QColor(220, 234, 251)


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
        self._move_prompt_open = False  # защита от повторного входа в диалог
        self._last_move_prompt: dict[tuple[str, str, str], float] = {}
        self._report_rows: list[dict[str, Any]] = []
        self._report_detail_by = DETAIL_BY_DATE
        self._report_all_warehouses = False
        self._last_pdf_path: Path | None = None
        self._highlight_row = -1
        self._highlight_col = -1

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
        tabs.addTab(self._build_settings_tab(), "Настройки")

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

        header.addSpacing(16)
        self.balance_mode_label = QLabel("")
        self.balance_mode_label.setStyleSheet("color: #1a73e8; font-weight: bold;")
        header.addWidget(self.balance_mode_label)

        header.addStretch()
        layout.addLayout(header)

        self.table = QTableWidget(0, len(COLUMN_HEADERS))
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setStyleSheet(TABLE_CELL_STYLE)
        # Чтобы фокус оставался на ячейке и был виден цвет item:focus
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Валидация числовых колонок (включая остаток на конец)
        self._number_delegate = NumberDelegate(self.table)
        for col in NUMERIC_COLUMNS | {COL_FINAL}:
            self.table.setItemDelegateForColumn(col, self._number_delegate)

        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in range(len(COLUMN_HEADERS)):
            if col != COL_NAME:
                header_view.setSectionResizeMode(
                    col, QHeaderView.ResizeMode.ResizeToContents
                )

        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(self._on_current_cell_changed)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        btn_add = QPushButton("Добавить строку")
        btn_add.clicked.connect(self._add_row)
        buttons.addWidget(btn_add)

        btn_delete = QPushButton("В архив")
        btn_delete.setToolTip("Сделать позицию архивной и переместить в конец списка")
        btn_delete.clicked.connect(self._archive_row)
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
        self.report_warehouse.addItem("Все склады", ALL_WAREHOUSES)
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
        self.report_detail_label = QLabel("Детализация:")
        filters.addWidget(self.report_detail_label)
        self.report_detail = QComboBox()
        self.report_detail.addItem("По датам", DETAIL_BY_DATE)
        self.report_detail.addItem("По товару", DETAIL_BY_ITEM)
        filters.addWidget(self.report_detail)

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

        self.report_table = QTableWidget(0, 0)
        self.report_table.setAlternatingRowColors(True)
        self.report_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.report_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.report_table)

        self._on_report_type_changed()
        return page

    def _build_settings_tab(self) -> QWidget:
        """Вкладка настроек: дата ввода остатков."""
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel("Дата ввода остатков")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        hint = QLabel(
            "Только в указанную дату можно редактировать «Остаток на начало» "
            "и «Остаток на конец».\n"
            "В остальные дни эти поля недоступны для ввода: остаток на начало "
            "берётся с предыдущего дня, остаток на конец считается по формуле."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("Дата ввода остатков:"))
        self.settings_stock_date = QDateEdit()
        self.settings_stock_date.setCalendarPopup(True)
        self.settings_stock_date.setDisplayFormat("dd.MM.yyyy")
        entry = self._stock_entry_date()
        if entry is not None:
            self.settings_stock_date.setDate(
                QDate(entry.year, entry.month, entry.day)
            )
        else:
            self.settings_stock_date.setDate(QDate.currentDate())
        row.addWidget(self.settings_stock_date)
        row.addStretch()
        layout.addLayout(row)

        btn_save = QPushButton("Сохранить настройки")
        btn_save.clicked.connect(self._save_settings)
        layout.addWidget(btn_save)

        self.settings_status = QLabel("")
        layout.addWidget(self.settings_status)
        layout.addStretch()
        return page

    def _stock_entry_date(self) -> date | None:
        """Дата ввода остатков из config.json или None."""
        raw = self.config.get("stock_entry_date")
        if not raw:
            return None
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None

    def _is_stock_entry_day(self) -> bool:
        """Текущая дата учёта совпадает с датой ввода остатков."""
        entry = self._stock_entry_date()
        return entry is not None and entry == self._current_date()

    def _save_settings(self) -> None:
        """Сохраняет дату ввода остатков в config.json."""
        entry = self._qdate_to_date(self.settings_stock_date.date())
        self.config["stock_entry_date"] = entry.isoformat()
        save_config(self.config)
        self.settings_status.setText(
            f"Сохранено. Дата ввода остатков: {entry.strftime('%d.%m.%Y')}"
        )
        QMessageBox.information(
            self,
            "Настройки",
            f"Дата ввода остатков: {entry.strftime('%d.%m.%Y')}\n"
            "Редактирование остатков доступно только в этот день на вкладке «Учёт».",
        )
        self._load_table()

    def _update_balance_mode_hint(self) -> None:
        """Подсказка режима остатков в шапке учёта."""
        entry = self._stock_entry_date()
        if entry is None:
            self.balance_mode_label.setText(
                "Дата ввода остатков не задана (Настройки) — остатки только для чтения"
            )
            self.balance_mode_label.setStyleSheet("color: #b06000; font-weight: bold;")
        elif self._is_stock_entry_day():
            self.balance_mode_label.setText(
                "Режим ввода остатков — можно менять остаток на начало и на конец"
            )
            self.balance_mode_label.setStyleSheet("color: #1a73e8; font-weight: bold;")
        else:
            self.balance_mode_label.setText(
                f"Остатки авто (ввод только {entry.strftime('%d.%m.%Y')})"
            )
            self.balance_mode_label.setStyleSheet("color: #5f6368;")

    def _apply_balance_edit_flags(self) -> None:
        """Включает/выключает редактирование колонок остатков."""
        allow = self._is_stock_entry_day()
        was = self._loading
        self._loading = True
        try:
            for row in range(self.table.rowCount()):
                for col in (COL_INITIAL, COL_FINAL):
                    item = self.table.item(row, col)
                    if item is None:
                        continue
                    flags = item.flags()
                    if allow:
                        item.setFlags(flags | Qt.ItemFlag.ItemIsEditable)
                    else:
                        item.setFlags(flags & ~Qt.ItemFlag.ItemIsEditable)
        finally:
            self._loading = was

    def _qdate_to_date(self, qd: QDate) -> date:
        return date(qd.year(), qd.month(), qd.day())

    def _on_report_type_changed(self, *_args: Any) -> None:
        is_movements = self.report_type.currentData() == REPORT_MOVEMENTS
        self.report_from_label.setVisible(is_movements)
        self.report_date_from.setVisible(is_movements)
        self.report_detail_label.setVisible(is_movements)
        self.report_detail.setVisible(is_movements)
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
        detail_by = str(self.report_detail.currentData() or DETAIL_BY_DATE)
        all_warehouses = warehouse_id == ALL_WAREHOUSES
        try:
            if report_kind == REPORT_MOVEMENTS:
                self._report_rows = self.db.report_movements(
                    warehouse_id,
                    date_from,
                    date_to,
                    detail_by=detail_by,
                )
                # Подставляем читаемые имена складов
                for row in self._report_rows:
                    wid = row.get("warehouse_id")
                    if wid:
                        row["warehouse_name"] = self._warehouse_label(str(wid))

                if detail_by == DETAIL_BY_ITEM:
                    if all_warehouses:
                        headers = [
                            "Товар / дата",
                            "Склад",
                            "Приход",
                            "Расход",
                            "Перемещение*",
                            "Итог",
                        ]
                        keys = [
                            "item_name",
                            "warehouse_name",
                            "incoming",
                            "consumption",
                            "move_stock",
                            "total",
                        ]
                    else:
                        headers = [
                            "Товар / дата",
                            "Приход",
                            "Расход",
                            "Перемещение*",
                            "Итог",
                        ]
                        keys = [
                            "item_name",
                            "incoming",
                            "consumption",
                            "move_stock",
                            "total",
                        ]
                else:
                    if all_warehouses:
                        headers = [
                            "Дата",
                            "Склад",
                            "Товар",
                            "Приход",
                            "Расход",
                            "Перемещение*",
                            "Итог",
                        ]
                        keys = [
                            "operation_date",
                            "warehouse_name",
                            "item_name",
                            "incoming",
                            "consumption",
                            "move_stock",
                            "total",
                        ]
                    else:
                        headers = [
                            "Дата",
                            "Товар",
                            "Приход",
                            "Расход",
                            "Перемещение*",
                            "Итог",
                        ]
                        keys = [
                            "operation_date",
                            "item_name",
                            "incoming",
                            "consumption",
                            "move_stock",
                            "total",
                        ]
            else:
                self._report_rows = self.db.report_stock(warehouse_id, date_to)
                for row in self._report_rows:
                    wid = row.get("warehouse_id")
                    if wid:
                        row["warehouse_name"] = self._warehouse_label(str(wid))
                if all_warehouses:
                    headers = ["Склад", "Наименование", "Остаток"]
                    keys = ["warehouse_name", "item_name", "final_stock"]
                else:
                    headers = ["Наименование", "Остаток"]
                    keys = ["item_name", "final_stock"]
                detail_by = ""
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Отчёт", str(exc))
            return

        self._report_detail_by = detail_by
        self._report_all_warehouses = all_warehouses
        self.report_table.clear()
        self.report_table.setColumnCount(len(headers))
        self.report_table.setHorizontalHeaderLabels(headers)
        self.report_table.setRowCount(len(self._report_rows))

        bold = QFont()
        bold.setBold(True)
        header_bg = QColor(220, 230, 242)
        subtotal_bg = QColor(236, 240, 245)

        for r, data in enumerate(self._report_rows):
            kind = data.get("row_kind", "detail")
            for c, key in enumerate(keys):
                value = data.get(key)
                if kind == "header":
                    if c == 0:
                        text = str(data.get("group_label") or value or "")
                        if detail_by == DETAIL_BY_DATE and key == "operation_date":
                            text = f"Дата: {self._fmt_report_date(data.get('group_title'))}"
                    else:
                        text = ""
                elif key == "operation_date":
                    if kind == "subtotal":
                        text = ""
                    else:
                        text = self._fmt_report_date(value)
                elif key == "item_name":
                    if kind == "detail" and detail_by == DETAIL_BY_ITEM:
                        text = self._fmt_report_date(data.get("operation_date"))
                    else:
                        text = str(value or "")
                elif key == "warehouse_name":
                    if kind in {"header", "subtotal"}:
                        text = ""
                    else:
                        text = str(value or "")
                elif value is None:
                    text = ""
                else:
                    text = _fmt_number(value)

                item = QTableWidgetItem(text)
                if (
                    key
                    not in {
                        "item_name",
                        "operation_date",
                        "warehouse_name",
                    }
                    and text != ""
                ):
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                if kind == "header":
                    item.setFont(bold)
                    item.setBackground(header_bg)
                elif kind == "subtotal":
                    item.setFont(bold)
                    item.setBackground(subtotal_bg)
                self.report_table.setItem(r, c, item)

        header = self.report_table.horizontalHeader()
        # Растягиваем колонку с наименованием / товаром
        stretch_col = 0
        for idx, key in enumerate(keys):
            if key == "item_name":
                stretch_col = idx
                break
        header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)

        detail_count = sum(
            1
            for row in self._report_rows
            if row.get("row_kind", "detail") == "detail"
            or (
                report_kind == REPORT_STOCK
                and row.get("item_name")
            )
        )
        if report_kind == REPORT_STOCK:
            detail_count = len(self._report_rows)

        status = f"Строк данных: {detail_count}"
        if report_kind == REPORT_MOVEMENTS:
            mode_label = (
                "по датам" if detail_by == DETAIL_BY_DATE else "по товару"
            )
            status += (
                f". Детализация: {mode_label}. "
                "*Перемещение — справочно, в итог не входит (итог = приход − расход)."
            )
        self.report_status.setText(status)

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

        warehouse_id = str(self.report_warehouse.currentData())
        warehouse_name = self._warehouse_name(warehouse_id)
        date_from = self._qdate_to_date(self.report_date_from.date())
        date_to = self._qdate_to_date(self.report_date_to.date())

        try:
            if self.report_type.currentData() == REPORT_MOVEMENTS:
                has_data = any(
                    r.get("row_kind") == "detail" for r in self._report_rows
                )
                if not has_data:
                    answer = QMessageBox.question(
                        self,
                        "PDF",
                        "Нет движений за период. Всё равно создать PDF?",
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        return
                path = generate_movements_pdf(
                    self._report_rows,
                    warehouse_name=warehouse_name,
                    date_from=date_from,
                    date_to=date_to,
                    detail_by=str(self._report_detail_by or DETAIL_BY_DATE),
                    all_warehouses=bool(self._report_all_warehouses),
                )
            else:
                path = generate_stock_pdf(
                    self._report_rows,
                    warehouse_name=warehouse_name,
                    as_of_date=date_to,
                    all_warehouses=bool(self._report_all_warehouses),
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
        if str(warehouse_id) == ALL_WAREHOUSES:
            return "Все склады"
        for wh in self.config.get("warehouses", []):
            if str(wh.get("id")) == str(warehouse_id):
                return str(wh.get("name", warehouse_id))
        return warehouse_id

    def _warehouse_label(self, warehouse_id: str | None) -> str:
        """Краткое имя склада для строки отчёта."""
        if not warehouse_id:
            return ""
        return self._warehouse_name(str(warehouse_id))

    def _on_filter_changed(self, *_args: Any) -> None:
        self._last_move_prompt.clear()
        self._load_table()

    def _load_table(self) -> None:
        """Заполняет таблицу данными БД (и каталогом номенклатуры) для склада и даты."""
        self._loading = True
        try:
            warehouse_id = self._current_warehouse_id()
            op_date = self._current_date()
            rows = self.db.get_data(warehouse_id, op_date)

            # Вне даты ввода остатков: начало с прошлого дня, конец по формуле
            if not self._is_stock_entry_day():
                prev_map = self.db.get_previous_final_map(warehouse_id, op_date)
                for data in rows:
                    name = str(data.get("item_name") or "")
                    data["initial_stock"] = float(prev_map.get(name, 0.0))
                    data["final_stock"] = calc_final_stock(**data)

            self.table.setRowCount(0)
            self.table.setRowCount(len(rows))
            for r, data in enumerate(rows):
                self._write_row(r, data)
            self._apply_balance_edit_flags()
            self._update_balance_mode_hint()
        finally:
            self._loading = False
            current = self.table.currentRow()
            if current >= 0:
                self._apply_row_highlight(current)
            elif self.table.rowCount() > 0:
                self.table.setCurrentCell(0, COL_NAME)

    def _write_row(self, row: int, data: dict[str, Any]) -> None:
        """Пишет словарь операции в строку таблицы."""
        archived = bool(data.get("is_archived"))
        name_text = str(data.get("item_name") or "")
        name_item = QTableWidgetItem(name_text)
        row_id = data.get("id")
        if row_id is not None:
            name_item.setData(ROLE_ROW_ID, int(row_id))
        name_item.setData(ROLE_ARCHIVED, archived)
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
        final_item.setTextAlignment(
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        )
        self.table.setItem(row, COL_FINAL, final_item)
        self._apply_final_style(row, float(final))
        self._apply_archived_row_style(row, archived)
        # Флаги редактирования остатков выставит _apply_balance_edit_flags

    def _apply_archived_row_style(self, row: int, archived: bool) -> None:
        """Визуально выделяет архивные строки (серый текст)."""
        gray = QColor(120, 120, 120)
        black = QColor(0, 0, 0)
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item is None:
                continue
            if archived:
                item.setForeground(gray)
            elif col != COL_FINAL:
                item.setForeground(black)
            # COL_FINAL цвет восстановит _apply_final_style / подсветка
        if not archived:
            final_item = self.table.item(row, COL_FINAL)
            if final_item is not None:
                try:
                    value = float((final_item.text() or "0").replace(",", "."))
                except ValueError:
                    value = 0.0
                self._apply_final_style(row, value)

    def _read_row(self, row: int) -> dict[str, Any] | None:
        """Читает строку таблицы в словарь для БД. None — если нет наименования."""
        name_item = self.table.item(row, COL_NAME)
        name = (name_item.text() if name_item else "").strip()
        if not name:
            return None

        row_id = None
        if name_item is not None:
            stored = name_item.data(ROLE_ROW_ID)
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

        final_item = self.table.item(row, COL_FINAL)
        if self._is_stock_entry_day() and final_item is not None:
            # В день ввода остатков конечный остаток может быть задан вручную
            parsed_final = _parse_number(final_item.text())
            data["final_stock"] = (
                0.0 if parsed_final is None else parsed_final
            )
        else:
            data["final_stock"] = calc_final_stock(**data)
        return data

    def _apply_final_style(self, row: int, final_value: float) -> None:
        """Красный текст при отрицательном остатке на конец."""
        item = self.table.item(row, COL_FINAL)
        if item is None:
            return
        # Активная ячейка — свой цвет текста (белый на синем)
        if row == self.table.currentRow() and self.table.currentColumn() == COL_FINAL:
            item.setForeground(ACTIVE_CELL_FG)
            return
        if final_value < 0:
            item.setForeground(QColor(180, 0, 0))
        else:
            item.setForeground(QColor(0, 0, 0))

    def _row_is_archived(self, row: int) -> bool:
        name_item = self.table.item(row, COL_NAME)
        if name_item is None:
            return False
        return bool(name_item.data(ROLE_ARCHIVED))

    def _restore_cell_foreground(self, row: int, col: int, item: QTableWidgetItem) -> None:
        """Восстанавливает цвет текста после снятия подсветки."""
        if self._row_is_archived(row):
            item.setForeground(QColor(120, 120, 120))
            return
        if col == COL_FINAL:
            try:
                value = float((item.text() or "0").replace(",", "."))
            except ValueError:
                value = 0.0
            if value < 0:
                item.setForeground(QColor(180, 0, 0))
            else:
                item.setForeground(QColor(0, 0, 0))
        else:
            item.setForeground(QColor(0, 0, 0))

    def _apply_row_highlight(self, row: int) -> None:
        """
        Подсветка: вся активная строка — светло-синяя,
        текущая ячейка — насыщенный синий.
        Не должна порождать itemChanged → диалоги (блок через _loading).
        """
        if row < 0 or row >= self.table.rowCount():
            return
        was_loading = self._loading
        self._loading = True
        try:
            is_active_row = row == self.table.currentRow()
            active_col = self.table.currentColumn()
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is None:
                    continue
                if is_active_row and col == active_col:
                    item.setBackground(ACTIVE_CELL_BG)
                    item.setForeground(ACTIVE_CELL_FG)
                elif is_active_row:
                    item.setBackground(ACTIVE_ROW_BG)
                    self._restore_cell_foreground(row, col, item)
                else:
                    item.setBackground(QBrush())
                    self._restore_cell_foreground(row, col, item)
        finally:
            self._loading = was_loading

    def _on_current_cell_changed(
        self,
        current_row: int,
        current_col: int,
        previous_row: int,
        previous_col: int,
    ) -> None:
        """Смена активной ячейки — обновить выделение."""
        self._highlight_row = current_row
        self._highlight_col = current_col
        if self._loading:
            return
        for row in {previous_row, current_row}:
            if row >= 0:
                self._apply_row_highlight(row)

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
        if row == self.table.currentRow():
            self._apply_row_highlight(row)
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
            name_item = self.table.item(row, COL_NAME)
            if name_item is None:
                name_item = QTableWidgetItem()
                self.table.setItem(row, COL_NAME, name_item)
            name_item.setData(ROLE_ROW_ID, row_id)
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

        if col == COL_NAME:
            # Имя — только автосохранение ниже
            pass
        elif col == COL_FINAL:
            if not self._is_stock_entry_day():
                return
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
            self._apply_final_style(row, parsed)
            if row == self.table.currentRow():
                self._apply_row_highlight(row)
            self._autosave_row(row)
            return

        # Остаток на начало: вне дня ввода — не принимаем правки
        if col == COL_INITIAL and not self._is_stock_entry_day():
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

            # При изменении начала/движений конец пересчитываем по формуле
            self._update_final_cell(row)

            if col == COL_MOVE and self._move_prompt_armed and not self._move_prompt_open:
                name_item = self.table.item(row, COL_NAME)
                item_name = (name_item.text() if name_item else "").strip()
                prompt_key = (
                    self._current_warehouse_id(),
                    self._current_date().isoformat(),
                    item_name or f"row:{row}",
                )
                if parsed == 0:
                    self._last_move_prompt.pop(prompt_key, None)
                elif self._last_move_prompt.get(prompt_key) != parsed:
                    self._last_move_prompt[prompt_key] = parsed
                    self._move_prompt_open = True
                    try:
                        self._offer_pair_move(row, parsed)
                    finally:
                        self._move_prompt_open = False

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
        other_rows = self.db.get_data(other_id, op_date, fill_nomenclature=False)
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
            self._apply_balance_edit_flags()
        finally:
            self._loading = False
        self.table.setCurrentCell(row, COL_NAME)
        self.table.editItem(self.table.item(row, COL_NAME))

    def _archive_row(self) -> None:
        """Делает позицию архивной и перемещает в конец списка (без удаления данных)."""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Архив", "Выберите строку.")
            return

        name_item = self.table.item(row, COL_NAME)
        item_name = (name_item.text() if name_item else "").strip()
        if not item_name:
            # Пустая новая строка — просто убрать с экрана
            self.table.removeRow(row)
            return

        already = False
        if name_item is not None:
            already = bool(name_item.data(ROLE_ARCHIVED))
        if already:
            QMessageBox.information(
                self,
                "Архив",
                f"«{item_name}» уже в архиве (в конце списка).",
            )
            return

        answer = QMessageBox.question(
            self,
            "Архив",
            f"Переместить «{item_name}» в архив (в конец списка)?\n"
            "Данные по движениям сохранятся.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.db.archive_nomenclature_item(item_name)
        self._load_table()
        # Курсор на архивную строку в конце
        for r in range(self.table.rowCount() - 1, -1, -1):
            cell = self.table.item(r, COL_NAME)
            if cell and cell.text().strip() == item_name:
                self.table.setCurrentCell(r, COL_NAME)
                self.table.scrollToItem(cell)
                break

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

                name_item = self.table.item(row, COL_NAME)
                if name_item is None:
                    name_item = QTableWidgetItem(data["item_name"])
                    self.table.setItem(row, COL_NAME, name_item)
                name_item.setData(ROLE_ROW_ID, row_id)

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
