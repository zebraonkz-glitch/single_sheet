"""
Работа с конфигурацией и путями приложения.
Корень приложения — каталог, где лежит этот файл (inventory_app/).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = APP_ROOT / "config.json"


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Читает config.json."""
    path = config_path or CONFIG_PATH
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict[str, Any], config_path: Path | None = None) -> None:
    """Сохраняет config.json."""
    path = config_path or CONFIG_PATH
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def resolve_path(relative: str, base: Path | None = None) -> Path:
    """Преобразует путь из конфига в абсолютный относительно APP_ROOT."""
    root = base or APP_ROOT
    path = Path(relative)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def get_paths(config: dict[str, Any] | None = None) -> dict[str, Path]:
    """Возвращает абсолютные пути db / backups / reports / shablon."""
    cfg = config if config is not None else load_config()
    paths_cfg = cfg.get("paths", {})
    return {
        "db": resolve_path(paths_cfg.get("db", "db/inventory.db")),
        "backups": resolve_path(paths_cfg.get("backups", "backups")),
        "reports": resolve_path(paths_cfg.get("reports", "reports")),
        "shablon": resolve_path(paths_cfg.get("shablon", "../shablon")),
    }


def ensure_directories(config: dict[str, Any] | None = None) -> dict[str, Path]:
    """
    Создаёт рабочие каталоги при старте приложения.
    Папка shablon не создаётся — берётся готовый шаблон.
    """
    paths = get_paths(config)
    paths["db"].parent.mkdir(parents=True, exist_ok=True)
    paths["backups"].mkdir(parents=True, exist_ok=True)
    paths["reports"].mkdir(parents=True, exist_ok=True)
    return paths
