"""
Ежедневная архивация SQLite-базы в ZIP.

При каждом закрытии приложения пишется backup_YYYY-MM-DD.zip
с актуальным состоянием БД. Если файл за сегодня уже есть — перезаписывается.
Хранится не более MAX_BACKUPS последних копий (по разным датам).
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

# Максимум ежедневных ZIP в папке backups
MAX_BACKUPS = 7


def backup_zip_name(backup_date: date | None = None) -> str:
    """Имя архива для указанной даты."""
    day = backup_date or date.today()
    return f"backup_{day.isoformat()}.zip"


def backup_exists(backups_dir: Path, backup_date: date | None = None) -> bool:
    """Проверяет наличие ZIP за указанную дату в папке backups."""
    return (Path(backups_dir) / backup_zip_name(backup_date)).is_file()


def list_backup_zips(backups_dir: Path | str) -> list[Path]:
    """Список backup_*.zip, от новых к старым (по дате в имени)."""
    folder = Path(backups_dir)
    if not folder.is_dir():
        return []

    def sort_key(path: Path) -> tuple:
        name = path.stem  # backup_YYYY-MM-DD
        if name.startswith("backup_") and len(name) >= 17:
            try:
                return (0, date.fromisoformat(name[7:17]), path.name)
            except ValueError:
                pass
        return (1, date.min, path.name)

    zips = [p for p in folder.glob("backup_*.zip") if p.is_file()]
    return sorted(zips, key=sort_key, reverse=True)


def prune_old_backups(
    backups_dir: Path | str,
    *,
    keep: int = MAX_BACKUPS,
) -> list[Path]:
    """
    Удаляет старые ZIP, оставляя не более keep самых новых.
    Возвращает список удалённых путей.
    """
    if keep < 1:
        keep = 1
    zips = list_backup_zips(backups_dir)
    removed: list[Path] = []
    for old in zips[keep:]:
        try:
            old.unlink(missing_ok=True)
            removed.append(old)
        except OSError:
            continue
    return removed


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
    Пишет ZIP с актуальной копией БД за указанный день (по умолчанию — сегодня).

    Если backup_YYYY-MM-DD.zip уже есть — файл перезаписывается свежим снимком.
    После записи оставляет не больше MAX_BACKUPS файлов.
    Возвращает путь к ZIP или None, если БД ещё нет.

    Параметр last_backup_date сохранён для совместимости вызовов (не влияет на запись).
    """
    _ = last_backup_date  # больше не блокирует повторную запись в тот же день

    cfg_path = config_path or CONFIG_PATH
    config = load_config(cfg_path) if cfg_path.exists() else {}
    paths = ensure_directories(config) if config else get_paths()

    db = Path(db_path) if db_path else paths["db"]
    backups = Path(backups_dir) if backups_dir else paths["backups"]
    backups.mkdir(parents=True, exist_ok=True)

    day = today or date.today()
    zip_path = backups / backup_zip_name(day)

    if not db.is_file():
        prune_old_backups(backups)
        return None

    # mode "w" перезаписывает существующий ZIP актуальным содержимым БД
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(db, arcname="inventory.db")

    if update_config and cfg_path.exists():
        config["last_backup_date"] = day.isoformat()
        save_config(config, cfg_path)

    prune_old_backups(backups)
    return zip_path


def on_app_close(
    db_path: Path | str | None = None,
    backups_dir: Path | str | None = None,
) -> Path | None:
    """
    Вызов из closeEvent главного окна.
    Всегда обновляет сегодняшний бэкап актуальным состоянием БД.
    """
    return perform_daily_backup(db_path=db_path, backups_dir=backups_dir)


def _demo() -> None:
    """Проверка: повтор в тот же день перезаписывает ZIP свежими данными."""
    import sys
    import tempfile

    sys.stdout.reconfigure(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_file = tmp_path / "inventory.db"
        backups = tmp_path / "backups"
        backups.mkdir()
        db_file.write_bytes(b"SQLite content v1")

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
        with zipfile.ZipFile(first, "r") as zf:
            assert zf.read("inventory.db") == b"SQLite content v1"
        print(f"1-й вызов ({day1}): создан {first.name}")

        # Изменили БД и закрыли снова в тот же день — ZIP перезаписан
        db_file.write_bytes(b"SQLite content v2 FRESH")
        second = perform_daily_backup(
            db_path=db_file,
            backups_dir=backups,
            today=day1,
            config_path=cfg_path,
        )
        assert second is not None and second == first
        with zipfile.ZipFile(second, "r") as zf:
            assert zf.read("inventory.db") == b"SQLite content v2 FRESH"
        print(f"2-й вызов ({day1}): перезаписан актуальными данными")

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

        for i in range(1, 10):
            (backups / f"backup_2026-06-{i:02d}.zip").write_bytes(b"PK\x03\x04fake")
        removed = prune_old_backups(backups, keep=MAX_BACKUPS)
        left = list_backup_zips(backups)
        assert len(left) == MAX_BACKUPS, left
        assert len(removed) >= 1
        print(f"prune: удалено {len(removed)}, осталось {len(left)}")

        updated = load_config(cfg_path)
        assert updated["last_backup_date"] == "2026-08-01"
        print(f"last_backup_date в конфиге: {updated['last_backup_date']}")
        print("OK: архиватор проверен")

    real = perform_daily_backup()
    if real:
        print(f"Рабочий бэкап обновлён: {real}")
    else:
        print("Рабочий бэкап: БД отсутствует — пропуск")


if __name__ == "__main__":
    _demo()
