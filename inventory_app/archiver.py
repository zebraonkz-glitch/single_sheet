"""
Ежедневная архивация SQLite-базы в ZIP.

Правило: не чаще одного архива в календарный день.
Имя файла: backup_YYYY-MM-DD.zip
Внутри ZIP — копия inventory.db.
"""

from __future__ import annotations

import zipfile
from datetime import date, datetime
from pathlib import Path

from app_paths import (
    CONFIG_PATH,
    ensure_directories,
    get_paths,
    load_config,
    save_config,
)


def backup_zip_name(backup_date: date | None = None) -> str:
    """Имя архива для указанной даты."""
    day = backup_date or date.today()
    return f"backup_{day.isoformat()}.zip"


def backup_exists(backups_dir: Path, backup_date: date | None = None) -> bool:
    """Проверяет наличие ZIP за указанную дату в папке backups."""
    return (Path(backups_dir) / backup_zip_name(backup_date)).is_file()


def _normalize_date(value: date | datetime | str | None) -> date | None:
    """Приводит значение из конфига к date."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def perform_daily_backup(
    db_path: Path | str | None = None,
    backups_dir: Path | str | None = None,
    last_backup_date: date | datetime | str | None = None,
    *,
    today: date | None = None,
    config_path: Path | None = None,
    update_config: bool = True,
) -> Path | None:
    """
    Создаёт ZIP с копией БД, если за сегодня архива ещё нет.

    Проверки:
    1) last_backup_date из аргумента / config.json совпадает с сегодня — пропуск
    2) файл backup_YYYY-MM-DD.zip уже есть — пропуск (дата в конфиге синхронизируется)

    Возвращает путь к созданному ZIP или None, если архивация не нужна / БД нет.
    """
    cfg_path = config_path or CONFIG_PATH
    config = load_config(cfg_path) if cfg_path.exists() else {}
    paths = ensure_directories(config) if config else get_paths()

    db = Path(db_path) if db_path else paths["db"]
    backups = Path(backups_dir) if backups_dir else paths["backups"]
    backups.mkdir(parents=True, exist_ok=True)

    day = today or date.today()
    last = _normalize_date(
        last_backup_date
        if last_backup_date is not None
        else config.get("last_backup_date")
    )

    # Уже архивировали сегодня (по конфигу)
    if last == day:
        return None

    zip_path = backups / backup_zip_name(day)

    # Архив за сегодня уже лежит в папке — не дублируем
    if zip_path.is_file():
        if update_config and cfg_path.exists():
            config["last_backup_date"] = day.isoformat()
            save_config(config, cfg_path)
        return None

    if not db.is_file():
        # Нечего архивировать — БД ещё не создана
        return None

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(db, arcname="inventory.db")

    if update_config and cfg_path.exists():
        config["last_backup_date"] = day.isoformat()
        save_config(config, cfg_path)

    return zip_path


def on_app_close(
    db_path: Path | str | None = None,
    backups_dir: Path | str | None = None,
) -> Path | None:
    """
    Вызов из closeEvent главного окна (этап 4).
    Обёртка над perform_daily_backup с путями из config.json.
    """
    return perform_daily_backup(db_path=db_path, backups_dir=backups_dir)


def _demo() -> None:
    """Проверка: два вызова подряд → один ZIP; повтор во второй день → новый."""
    import sys
    import tempfile

    sys.stdout.reconfigure(encoding="utf-8")

    # Изолированный тест в temp, чтобы не трогать рабочий config/backups
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_file = tmp_path / "inventory.db"
        backups = tmp_path / "backups"
        backups.mkdir()
        db_file.write_bytes(b"SQLite demo content")

        cfg = {
            "paths": {
                "db": str(db_file),
                "backups": str(backups),
                "reports": str(tmp_path / "reports"),
                "shablon": str(tmp_path / "shablon"),
            },
            "last_backup_date": None,
        }
        cfg_path = tmp_path / "config.json"
        save_config(cfg, cfg_path)

        day1 = date(2026, 7, 31)
        day2 = date(2026, 8, 1)

        first = perform_daily_backup(
            db_path=db_file,
            backups_dir=backups,
            today=day1,
            config_path=cfg_path,
        )
        assert first is not None and first.name == "backup_2026-07-31.zip"
        print(f"1-й вызов ({day1}): создан {first.name}")

        second = perform_daily_backup(
            db_path=db_file,
            backups_dir=backups,
            today=day1,
            config_path=cfg_path,
        )
        assert second is None
        print(f"2-й вызов ({day1}): пропуск (уже есть)")

        third = perform_daily_backup(
            db_path=db_file,
            backups_dir=backups,
            today=day2,
            config_path=cfg_path,
        )
        assert third is not None and third.name == "backup_2026-08-01.zip"
        print(f"3-й вызов ({day2}): создан {third.name}")

        zips = sorted(p.name for p in backups.glob("backup_*.zip"))
        assert zips == ["backup_2026-07-31.zip", "backup_2026-08-01.zip"]

        # Проверяем содержимое ZIP
        with zipfile.ZipFile(first, "r") as zf:
            assert "inventory.db" in zf.namelist()
            assert zf.read("inventory.db") == b"SQLite demo content"

        updated = load_config(cfg_path)
        assert updated["last_backup_date"] == "2026-08-01"
        print(f"last_backup_date в конфиге: {updated['last_backup_date']}")
        print("OK: архиватор проверен")

    # Дополнительно: реальный бэкап рабочей БД (если есть)
    real = perform_daily_backup()
    if real:
        print(f"Рабочий бэкап создан: {real}")
    else:
        print("Рабочий бэкап за сегодня уже есть или БД отсутствует — пропуск")


if __name__ == "__main__":
    _demo()
