"""
Работа с конфигурацией и путями приложения.

Корень:
- в режиме разработки — каталог inventory_app/;
- в собранном exe (PyInstaller) — папка рядом с .exe
  (туда кладутся config.json, db/, backups/, reports/, shablon/).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def get_app_root() -> Path:
    """Каталог приложения (данные и конфиг)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_ROOT = get_app_root()
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
    root = base or get_app_root()
    path = Path(relative)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def get_paths(config: dict[str, Any] | None = None) -> dict[str, Path]:
    """Возвращает абсолютные пути db / backups / reports / shablon."""
    cfg = config if config is not None else load_config()
    paths_cfg = cfg.get("paths", {})
    # В сборке shablon лежит рядом с exe; в разработке — ../shablon
    default_shablon = "shablon" if getattr(sys, "frozen", False) else "../shablon"
    return {
        "db": resolve_path(paths_cfg.get("db", "db/inventory.db")),
        "backups": resolve_path(paths_cfg.get("backups", "backups")),
        "reports": resolve_path(paths_cfg.get("reports", "reports")),
        "shablon": resolve_path(paths_cfg.get("shablon", default_shablon)),
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
