"""
Генерация PDF-отчётов (fpdf2), формат A4.
Кириллица через системный шрифт Windows (Arial) — без сети.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

from fpdf import FPDF

from app_paths import ensure_directories, get_paths

# Типичные пути к шрифтам с кириллицей на Windows
_FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path(r"C:\Windows\Fonts\Arial.ttf"),
    Path(r"C:\Windows\Fonts\tahoma.ttf"),
    Path(r"C:\Windows\Fonts\calibri.ttf"),
)


def _find_cyrillic_font() -> Path:
    for path in _FONT_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Не найден системный шрифт с кириллицей (Arial/Tahoma/Calibri). "
        "Установите Arial или укажите путь к .ttf."
    )


def _fmt_num(value: Any) -> str:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if num == int(num):
        return str(int(num))
    return f"{num:.4f}".rstrip("0").rstrip(".")


def _fmt_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).strftime("%d.%m.%Y")
    except ValueError:
        return text


class ReportPDF(FPDF):
    """PDF A4 с таблицей отчёта."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__(orientation="L", unit="mm", format="A4")
        self.report_title = title
        self.report_subtitle = subtitle
        font_path = _find_cyrillic_font()
        self.add_font("ReportFont", "", str(font_path))
        self.set_auto_page_break(auto=True, margin=15)

    def header(self) -> None:
        self.set_font("ReportFont", size=14)
        self.cell(0, 8, self.report_title, new_x="LMARGIN", new_y="NEXT", align="C")
        if self.report_subtitle:
            self.set_font("ReportFont", size=10)
            self.cell(
                0,
                6,
                self.report_subtitle,
                new_x="LMARGIN",
                new_y="NEXT",
                align="C",
            )
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("ReportFont", size=8)
        self.cell(0, 8, f"стр. {self.page_no()}", align="C")

    def draw_table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        col_widths: Sequence[float] | None = None,
        row_kinds: Sequence[str] | None = None,
    ) -> None:
        """Рисует таблицу; при нехватке места переносит на следующую страницу."""
        usable = self.w - self.l_margin - self.r_margin
        if col_widths is None:
            width = usable / max(len(headers), 1)
            col_widths = [width] * len(headers)
        else:
            total = sum(col_widths)
            if total > 0 and abs(total - usable) > 0.5:
                scale = usable / total
                col_widths = [w * scale for w in col_widths]

        self.set_font("ReportFont", size=9)
        line_h = 7

        def draw_header() -> None:
            self.set_fill_color(230, 230, 230)
            for i, head in enumerate(headers):
                self.cell(col_widths[i], line_h, head, border=1, fill=True, align="C")
            self.ln(line_h)

        draw_header()
        for row_index, row in enumerate(rows):
            kind = "detail"
            if row_kinds is not None and row_index < len(row_kinds):
                kind = row_kinds[row_index]

            if self.get_y() + line_h > self.page_break_trigger:
                self.add_page()
                draw_header()

            if kind == "header":
                self.set_fill_color(210, 222, 238)
                fill = True
            elif kind == "subtotal":
                self.set_fill_color(236, 240, 245)
                fill = True
            else:
                fill = False

            for i, cell in enumerate(row):
                align = "R"
                if i == 0:
                    align = "L"
                if headers[0] == "Дата" and i <= 1:
                    align = "L"
                if headers[0] in {"Товар", "Наименование", "Товар / дата"} and i == 0:
                    align = "L"
                self.cell(
                    col_widths[i],
                    line_h,
                    str(cell),
                    border=1,
                    align=align,
                    fill=fill,
                )
            self.ln(line_h)


def generate_movements_pdf(
    rows: list[dict[str, Any]],
    *,
    warehouse_name: str,
    date_from: date | str,
    date_to: date | str,
    detail_by: str = "by_date",
    all_warehouses: bool = False,
    output_dir: Path | None = None,
) -> Path:
    """PDF: движение товаров с детализацией по датам или по товару."""
    paths = ensure_directories()
    out_dir = Path(output_dir) if output_dir else paths["reports"]
    out_dir.mkdir(parents=True, exist_ok=True)

    d_from = _fmt_date(date_from)
    d_to = _fmt_date(date_to)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"report_movements_{stamp}.pdf"

    mode_label = "по датам" if detail_by == "by_date" else "по товару"
    pdf = ReportPDF(
        "Движение товаров",
        f"Склад: {warehouse_name}. Период: {d_from} — {d_to}. Детализация: {mode_label}",
    )
    pdf.add_page()

    if detail_by == "by_item":
        if all_warehouses:
            headers = ["Товар / дата", "Склад", "Приход", "Расход", "Перемещение*", "Итог"]
            col_widths = [90, 35, 30, 30, 40, 30]
        else:
            headers = ["Товар / дата", "Приход", "Расход", "Перемещение*", "Итог"]
            col_widths = [110, 35, 35, 40, 35]
    else:
        if all_warehouses:
            headers = ["Дата", "Склад", "Товар", "Приход", "Расход", "Перемещение*", "Итог"]
            col_widths = [26, 30, 70, 28, 28, 35, 28]
        else:
            headers = ["Дата", "Товар", "Приход", "Расход", "Перемещение*", "Итог"]
            col_widths = [28, 90, 30, 30, 35, 30]

    table_rows: list[list[str]] = []
    row_kinds: list[str] = []
    empty_cells = [""] * (len(headers) - 1)

    for r in rows:
        kind = str(r.get("row_kind") or "detail")
        row_kinds.append(kind)
        wh = str(r.get("warehouse_name") or r.get("warehouse_id") or "")

        if detail_by == "by_item":
            if kind == "header":
                left = str(r.get("group_label") or r.get("item_name") or "")
                table_rows.append([left, *empty_cells])
            elif kind == "subtotal":
                if all_warehouses:
                    table_rows.append(
                        [
                            "Итого",
                            "",
                            _fmt_num(r.get("incoming")),
                            _fmt_num(r.get("consumption")),
                            _fmt_num(r.get("move_stock")),
                            _fmt_num(r.get("total")),
                        ]
                    )
                else:
                    table_rows.append(
                        [
                            "Итого",
                            _fmt_num(r.get("incoming")),
                            _fmt_num(r.get("consumption")),
                            _fmt_num(r.get("move_stock")),
                            _fmt_num(r.get("total")),
                        ]
                    )
            else:
                if all_warehouses:
                    table_rows.append(
                        [
                            _fmt_date(r.get("operation_date")),
                            wh,
                            _fmt_num(r.get("incoming")),
                            _fmt_num(r.get("consumption")),
                            _fmt_num(r.get("move_stock")),
                            _fmt_num(r.get("total")),
                        ]
                    )
                else:
                    table_rows.append(
                        [
                            _fmt_date(r.get("operation_date")),
                            _fmt_num(r.get("incoming")),
                            _fmt_num(r.get("consumption")),
                            _fmt_num(r.get("move_stock")),
                            _fmt_num(r.get("total")),
                        ]
                    )
        else:
            if kind == "header":
                left = f"Дата: {_fmt_date(r.get('group_title') or r.get('operation_date'))}"
                table_rows.append([left, *empty_cells])
            elif kind == "subtotal":
                if all_warehouses:
                    table_rows.append(
                        [
                            "",
                            "",
                            "Итого",
                            _fmt_num(r.get("incoming")),
                            _fmt_num(r.get("consumption")),
                            _fmt_num(r.get("move_stock")),
                            _fmt_num(r.get("total")),
                        ]
                    )
                else:
                    table_rows.append(
                        [
                            "",
                            "Итого",
                            _fmt_num(r.get("incoming")),
                            _fmt_num(r.get("consumption")),
                            _fmt_num(r.get("move_stock")),
                            _fmt_num(r.get("total")),
                        ]
                    )
            else:
                if all_warehouses:
                    table_rows.append(
                        [
                            _fmt_date(r.get("operation_date")),
                            wh,
                            str(r.get("item_name") or ""),
                            _fmt_num(r.get("incoming")),
                            _fmt_num(r.get("consumption")),
                            _fmt_num(r.get("move_stock")),
                            _fmt_num(r.get("total")),
                        ]
                    )
                else:
                    table_rows.append(
                        [
                            _fmt_date(r.get("operation_date")),
                            str(r.get("item_name") or ""),
                            _fmt_num(r.get("incoming")),
                            _fmt_num(r.get("consumption")),
                            _fmt_num(r.get("move_stock")),
                            _fmt_num(r.get("total")),
                        ]
                    )

    if not any(k == "detail" for k in row_kinds):
        empty = ["—", "Нет данных за период"] + ["—"] * (len(headers) - 2)
        table_rows = [empty]
        row_kinds = ["detail"]

    pdf.draw_table(
        headers,
        table_rows,
        col_widths=col_widths,
        row_kinds=row_kinds,
    )
    pdf.set_font("ReportFont", size=8)
    pdf.ln(2)
    pdf.multi_cell(
        0,
        5,
        "* Перемещение указано справочно и не входит в итог. Итог = приход − расход.",
    )
    pdf.output(str(out_path))
    return out_path


def generate_stock_pdf(
    rows: list[dict[str, Any]],
    *,
    warehouse_name: str,
    as_of_date: date | str,
    all_warehouses: bool = False,
    output_dir: Path | None = None,
) -> Path:
    """PDF: актуальные остатки. Возвращает путь к файлу."""
    paths = ensure_directories()
    out_dir = Path(output_dir) if output_dir else paths["reports"]
    out_dir.mkdir(parents=True, exist_ok=True)

    as_of = _fmt_date(as_of_date)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"report_stock_{stamp}.pdf"

    pdf = ReportPDF(
        "Актуальные остатки",
        f"Склад: {warehouse_name}. На дату: {as_of}",
    )
    pdf.add_page()
    if all_warehouses:
        headers = ["Склад", "Наименование", "Остаток"]
        table_rows = [
            [
                str(r.get("warehouse_name") or r.get("warehouse_id") or ""),
                str(r.get("item_name") or ""),
                _fmt_num(r.get("final_stock")),
            ]
            for r in rows
        ]
        col_widths = [40, 160, 40]
    else:
        headers = ["Наименование", "Остаток"]
        table_rows = [
            [str(r.get("item_name") or ""), _fmt_num(r.get("final_stock"))]
            for r in rows
        ]
        col_widths = [200, 40]
    if not table_rows:
        table_rows = [["Нет данных", "—"]] if not all_warehouses else [["—", "Нет данных", "—"]]

    pdf.draw_table(headers, table_rows, col_widths=col_widths)
    pdf.output(str(out_path))
    return out_path


def _demo() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    from database import Database

    db = Database()
    today = date.today()
    movements = db.report_movements("A", today, today, detail_by="by_date")
    stock = db.report_stock("A", today)
    p1 = generate_movements_pdf(
        movements,
        warehouse_name="Склад А",
        date_from=today,
        date_to=today,
        detail_by="by_date",
    )
    p2 = generate_stock_pdf(stock, warehouse_name="Склад А", as_of_date=today)
    print(f"movements rows={len(movements)} -> {p1}")
    print(f"stock rows={len(stock)} -> {p2}")
    assert p1.is_file() and p1.stat().st_size > 0
    assert p2.is_file() and p2.stat().st_size > 0
    by_item = db.report_movements("A", today, today, detail_by="by_item")
    assert any(r.get("row_kind") == "header" for r in by_item) or not any(
        r.get("row_kind") == "detail" for r in by_item
    )
    print("OK: PDF отчёты созданы")


if __name__ == "__main__":
    _demo()
