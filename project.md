Project: Складской учет (Python + SQLite, Offline)
1. Описание проекта
Десктопное приложение для учета товаров на одном листе (аналог Excel). Приложение полностью работает офлайн (без доступа к интернету). Данные хранятся в локальной SQLite базе. Реализована ежедневная архивация при закрытии приложения. Есть вкладка отчетов с возможностью печати/экспорта в PDF.

Цель: Заменить ручное ведение Excel-файлов на надежное десктопное решение с историей и архивацией.

2. Стек технологий
Язык: Python 3.10+
GUI: PyQt6 (для создания полноценного десктопного окна, вкладок, таблиц и диалогов).
База данных: SQLite (файл inventory.db в папке с программой).
Работа с таблицами: QTableWidget (максимально приближен к интерфейсу Excel).
Генерация PDF: fpdf2 (для создания печатных форм отчетов).
Архивация: zipfile + datetime (автоматическое создание ZIP-архивов БД каждый день).
Хранение конфигов: JSON (настройки приложения, список складов).
3. Структура данных (Data Model)
3.1. Модель строки таблицы (Table Row)
Каждая строка — это запись движения товара за конкретную дату на конкретном складе.

№	Колонка (UI)	Поле (DB)	Тип данных	Описание
1	Порядковый №	id	Integer (PK, Auto)	Уникальный ID записи
2	Наименование	item_name	Text	Название товара
3	Остаток на начало	initial_stock	Real	Количество на начало дня
4	Приход	incoming	Real	Поступление товара
5	Перемещение	move_stock	Real	Перемещение между складами (+ приход, - расход)
6	Расход 1	consumption_1	Real	Тип расхода 1 (например, производство)
7	Расход 2	consumption_2	Real	Тип расхода 2 (например, брак)
8	Расход 3	consumption_3	Real	Тип расхода 3 (например, прочее)
9	Остаток на конец	final_stock	Calculated	Рассчитывается формулой
Логика перемещений:
Так как складов всего два (Склад А и Склад Б), перемещение работает по принципу баланса:

Если на Складе А значение move_stock = -10, значит товар уехал.
На Складе Б в этот же день для этого товара должно появиться значение +10.
Примечание: В интерфейсе пользователь вводит значение перемещения. Приложение должно предлагать создать парную запись на другом складе (опционально, либо пользователь делает это вручную).
Формула расчета:
??
??
??
??
??
=
??
??
??
??
??
??
??
+
??
??
??
??
??
??
??
??
+
??
??
??
??
?
(
??
??
??
??
1
+
??
??
??
??
2
+
??
??
??
??
3
)
Final=Initial+Incoming+Move?(Cons 
1
?
 +Cons 
2
?
 +Cons 
3
?
 )

4. Функциональные требования
4.1. Основной экран (Main Sheet)
Шапка:
Выпадающий список (ComboBox): Выбор склада (Склад А, Склад Б).
Выбор даты (DatePicker): Дата отчета/ввода данных.
Таблица (QTableWidget):
Все наименования должны быть на экране, не зависимо от движений. Шаблон и первоначальная номенклатура в файле в папке shablon 
9 колонок согласно структуре выше.
Редактируемые ячейки (пользователь вводит числа).
Авторасчет: При изменении любой цифры в строке (кроме ID и Названия) колонка "Остаток на конец" пересчитывается мгновенно.
Валидация: Ячейки принимают только числа. Отрицательные остатки подсвечиваются красным цветом.
Управление данными:
Кнопка "Добавить строку".
Кнопка "Удалить строку".
Сохранение данных в БД происходит при изменении ячейки (или по кнопке "Сохранить все").
4.2. Вкладка "Отчеты" (Reports Tab)
Фильтры: Период (Дата от - Дата до), Склад.
Виды отчетов:
Движение товаров: Таблица операций (дата, товар, приход, расход, итог).
Актуальные остатки: Список товаров с текущим final_stock на выбранную дату.
Печать и Экспорт:
Кнопка "Сформировать PDF".
Приложение генерирует PDF файл с таблицей отчета.
Файл сохраняется в папку reports/ рядом с программой.
Опционально: вызов системной печати.
4.3. Требования к работе без интернета
Приложение не делает никаких HTTP запросов.
Все данные хранятся локально в файле inventory.db.
При запуске приложение проверяет наличие БД, если нет — создает новую.
4.4. Архивация (Daily Backup)
При закрытии приложения (событие closeEvent):
Проверяется дата последней архивации.
Если текущая дата отличается от даты последней архивации -> создается ZIP-архив.
В архив кладется копия файла inventory.db.
Имя архива: backup_YYYY-MM-DD.zip.
Архив сохраняется в папку backups/.
5. Структура проекта (File Structure)
text
/inventory_app
?
??? main.py                 # Точка входа, инициализация окна
??? database.py             # Логика подключения к SQLite, CRUD операции
??? archiver.py             # Логика создания ZIP-архивов
??? pdf_generator.py        # Логика генерации PDF отчетов
??? config.json             # Список складов, настройки путей
?
??? /db
?   ??? inventory.db        # Основная база данных
?
??? /backups                # Папка для архивов БД (создается автоматически)
?   ??? backup_2023-10-25.zip
?   ??? backup_2023-10-26.zip
?
??? /reports                # Папка для сгенерированных PDF отчетов
    ??? report_2023-10-25.pdf
    ??? ...
6. План разработки (Roadmap)
Этап 1: База и Архиватор
Создать скрипт database.py: подключение к SQLite, создание таблицы operations, методы get_data, save_row, delete_row.
Создать скрипт archiver.py: функция проверки даты и создания ZIP архива. Подключить вызов этой функции в событие закрытия окна.
Этап 2: Интерфейс (Main Window)
Создать main.py с использованием PyQt6.
Верстка главного окна: QTabWidget (вкладки "Учет" и "Отчеты").
Реализация шапки: QComboBox (склады), QDateEdit (дата).
Реализация таблицы QTableWidget с 9 колонками.
Этап 3: Логика таблицы
Привязка события itemChanged к ячейкам таблицы.
Написание функции расчета final_stock.
Логика фильтрации: при выборе склада и даты таблица очищается и заполняется данными из БД только за эту дату и для этого склада.
Этап 4: Отчеты и PDF
Верстка вкладки "Отчеты": поля выбора периода, кнопка "Сгенерировать".
SQL-запросы для агрегации данных (суммы по товарам).
Интеграция библиотеки fpdf2: создание шаблона страницы, вывод таблицы в PDF, сохранение файла.
Этап 5: Финальная сборка и тестирование
Проверка работы без интернета.
Тестирование архивации (закрыть/открыть несколько раз с разными датами).
Проверка валидации ввода (буквы вместо цифр).
Сборка в исполняемый файл (PyInstaller).
7. Примеры SQL и логики
SQL Схема таблицы
sql
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    initial_stock REAL DEFAULT 0,
    incoming REAL DEFAULT 0,
    move_stock REAL DEFAULT 0,
    consumption_1 REAL DEFAULT 0,
    consumption_2 REAL DEFAULT 0,
    consumption_3 REAL DEFAULT 0,
    final_stock REAL GENERATED ALWAYS AS (initial_stock + incoming + move_stock - (consumption_1 + consumption_2 + consumption_3)) STORED,
    warehouse_id TEXT NOT NULL, -- 'A' or 'B'
    operation_date DATE NOT NULL
);
CREATE INDEX idx_warehouse_date ON operations(warehouse_id, operation_date);
(Примечание: Если версия SQLite старая и не поддерживает GENERATED, расчет делается в Python).

Логика архивации (псевдокод)
python
def on_close():
    today = datetime.now().date()
    last_backup_date = load_last_backup_date() # из JSON или проверки имени файла
    
    if today != last_backup_date:
        zip_filename = f"backups/backup_{today}.zip"
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            zipf.write("db/inventory.db", arcname="inventory.db")
        save_last_backup_date(today)
    app.quit()
8. Промты для Cursor AI (для ускорения разработки)
Используй эти промты в Cursor, чтобы быстро получить код:

Для базы данных:

"Write a Python module 'database.py' using sqlite3. Create a table 'operations' with columns: id, item_name, initial_stock, incoming, move_stock, consumption_1, consumption_2, consumption_3, warehouse_id, operation_date. Include functions to get data filtered by date and warehouse, and to insert/update rows."

Для логики расчета и таблицы PyQt:

"Create a PyQt6 class 'InventoryTable' that inherits from QTableWidget. It should have 9 columns matching the inventory schema. Implement logic so that when any numeric cell is changed, the 'final_stock' column (index 8) is recalculated immediately using the formula: Initial + Incoming + Move - (Cons1+Cons2+Cons3). Handle negative results by coloring the cell red."

Для архивации:

"Write a function 'perform_daily_backup' in Python using the zipfile module. It should check if a backup for today already exists. If not, create a zip file named 'backup_YYYY-MM-DD.zip' containing the database file. Call this function when the PyQt application window is about to close."

Для генерации PDF:

"Using the library 'fpdf2', write a function that takes a list of dictionaries (report data) and generates a PDF file. The PDF should have a title, a table with headers matching the report columns, and be formatted for A4 paper. Save the file to the 'reports' folder."

9. Критерии приемки (Acceptance Criteria)
Офлайн: Приложение запускается и работает без подключения к сети.
Расчет: Изменение любого числа в строке мгновенно меняет значение в колонке "Остаток на конец".
Фильтрация: При выборе "Склад А" и даты "01.11.2023" в таблице отображаются только эти данные.
Архивация: При закрытии программы в папке backups появляется новый ZIP-файл с сегодняшней датой, если его еще не было.
Отчеты: Кнопка "Сформировать отчет" создает валидный PDF файл в папке reports, который открывается в любом просмотрщике.
Целостность: Данные не теряются при перезагрузке приложения.
10. Риски и решения
Риск	Решение
Повреждение файла БД при сбое питания	Использовать транзакции SQLite (BEGIN, COMMIT). Регулярная архивация минимизирует потерю данных.
Пользователь введет текст вместо числа	Валидировать ввод в QTableWidget через сигналы или делегаты. Разрешать ввод только цифр и точки.
Большой размер архива со временем	Добавить в README инструкцию: "Папку backups нужно периодически чистить вручную". Либо добавить скрипт очистки старых архивов (>30 дней).
Несоответствие перемещений между складами	Добавить всплывающее окно-предупреждение: "Вы указали перемещение -10 ед. Хотите автоматически создать приход +10 ед. на другом складе?"
Сохрани этот текст как project.md в корне твоего проекта. Это полная спецификация для разработки приложения на Python.