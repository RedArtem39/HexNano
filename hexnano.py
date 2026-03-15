#!/usr/bin/env python3
"""
HexNano — профессиональный консольный HEX-редактор.
Точка входа: CLI (install, help, new) и запуск TUI-редактора.
TUI: blessed (или fallback на ANSI).
"""

import sys
import platform
import subprocess
from pathlib import Path

PROG = "hexnano"
SCRIPT_DIR = Path(__file__).resolve().parent


def _ensure_blessed() -> bool:
    """Проверить наличие blessed; при необходимости попытаться установить. Возвращает True, если доступен."""
    try:
        import blessed  # noqa: F401
        return True
    except ImportError:
        pass
    print("Библиотека 'blessed' не найдена. Попытка установки: pip install blessed ...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "blessed"],
            check=True,
            capture_output=True,
            text=True,
        )
        import blessed  # noqa: F401
        return True
    except (subprocess.CalledProcessError, ImportError):
        print("Установить вручную: pip install blessed")
        return False


def cmd_install():
    """Добавить путь к скрипту в PATH и создать hexnano.bat (Windows). Проверить/установить blessed."""
    path_value = str(SCRIPT_DIR.resolve())
    system = platform.system()

    # hexnano.bat — всегда в той же папке, где лежит hexnano.py
    bat_path = SCRIPT_DIR / "hexnano.bat"
    bat_content = "@echo off\n@python \"%~dp0hexnano.py\" %*\n"
    bat_path.write_text(bat_content, encoding="utf-8")
    print(f"Создан файл: {bat_path}")

    if system == "Windows":
        # Добавить путь в пользовательский PATH через реестр (winreg)
        try:
            import winreg
            env_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                "Environment",
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE,
            )
            try:
                path_str, reg_type = winreg.QueryValueEx(env_key, "Path")
            except FileNotFoundError:
                path_str = ""
                reg_type = winreg.REG_EXPAND_SZ
            paths = [p.strip() for p in path_str.split(";") if p.strip()]
            if path_value not in paths:
                paths.append(path_value)
                new_path = ";".join(paths)
                winreg.SetValueEx(env_key, "Path", 0, reg_type, new_path)
                print("PATH обновлен через реестр. Чтобы изменения вступили в силу, ПОЛНОСТЬЮ ЗАКРОЙ ВСЕ ОКНА POWERSHELL И ОТКРОЙ НОВОЕ.")
            else:
                print("Путь уже есть в PATH.")
            winreg.CloseKey(env_key)
        except Exception as e:
            print(f"Ошибка записи в реестр: {e}")
    else:
        # Linux/macOS — создать обёртку и добавить в PATH
        rc = Path.home() / ".bashrc"
        line = f'\nexport PATH="$PATH:{path_value}"\n'
        if rc.exists() and line.strip() in rc.read_text():
            print("Путь уже есть в .bashrc")
        else:
            with open(rc, "a", encoding="utf-8") as f:
                f.write(line)
            print(f"Добавлено в {rc}: {path_value}")
        print("Выполните: source ~/.bashrc   или перезапустите терминал.")

    # Проверить/установить blessed для TUI
    if _ensure_blessed():
        print("blessed: установлен, TUI будет доступен.")
    else:
        print("TUI будет работать в режиме ANSI (без blessed).")


def cmd_help():
    """Вывести список команд."""
    text = f"""
HexNano — консольный HEX-редактор

Использование:
  hexnano install          Добавить в PATH и создать hexnano.bat (Windows)
  hexnano help             Показать эту справку
  hexnano new .exe         Создать файл с минимальным PE (MZ, PE, пустая таблица секций)
  hexnano new .obj         Создать минимальный COFF/OBJ
  hexnano <файл>           Открыть файл в HEX-редакторе

TUI: стрелки — навигация | 0-9, A-F — ввод HEX | Ctrl+S — сохранить | Q — выход | H — справка
"""
    print(text.strip())


def create_minimal_pe(path: Path) -> None:
    """Создать файл с минимальным PE: MZ + PE Signature + COFF (пустая таблица секций)."""
    # MZ header (64 байта; e_lfanew — смещение PE)
    mz = bytearray(64)
    mz[0:2] = b"MZ"
    mz[0x3C:0x40] = (64).to_bytes(4, "little")

    # PE Signature + COFF (20 байт), NumberOfSections = 0
    pe_sig = b"PE\x00\x00"
    coff = bytearray(20)
    coff[0:2] = (0x014C).to_bytes(2, "little")   # Machine: i386
    coff[2:4] = (0).to_bytes(2, "little")        # NumberOfSections = 0 (пустая таблица секций)
    coff[16:18] = (0xE0).to_bytes(2, "little")  # SizeOfOptionalHeader = 224

    optional = bytearray(224)
    optional[0:2] = (0x10B).to_bytes(2, "little")
    optional[16:20] = (0x1000).to_bytes(4, "little")
    optional[28:32] = (0x400000).to_bytes(4, "little")
    optional[60:64] = (0x1000).to_bytes(4, "little")
    optional[64:68] = (0x200).to_bytes(4, "little")

    with open(path, "wb") as f:
        f.write(mz)
        f.write(pe_sig)
        f.write(coff)
        f.write(optional)
    print(f"Создан файл с минимальным PE: {path}")


def create_minimal_obj(path: Path) -> None:
    """Создать минимальный COFF .obj."""
    header = bytearray(20)
    header[0:2] = (0x8664).to_bytes(2, "little")
    header[2:4] = (1).to_bytes(2, "little")
    header[4:8] = (0).to_bytes(4, "little")
    header[8:12] = (0).to_bytes(4, "little")
    header[12:16] = (0).to_bytes(4, "little")
    header[16:18] = (0).to_bytes(2, "little")
    header[18:20] = (0x104).to_bytes(2, "little")
    with open(path, "wb") as f:
        f.write(header)
    print(f"Создан минимальный OBJ: {path}")


def cmd_new(ext: str) -> None:
    """Создать новый файл. ext — второй аргумент после 'new' (например .exe или .obj)."""
    ext = ext.strip().lower()
    if not ext.startswith("."):
        ext = "." + ext
    if ext == ".exe":
        create_minimal_pe(SCRIPT_DIR / "new.exe")
    elif ext == ".obj":
        create_minimal_obj(SCRIPT_DIR / "new.obj")
    else:
        print("Поддерживаются только: new .exe  или  new .obj")
        sys.exit(1)


def main():
    args = sys.argv[1:]

    if not args:
        cmd_help()
        return

    first = args[0].strip().lower()

    # Чёткое разделение: только если первый аргумент ровно "new" — это команда new, второй — расширение
    if first == "new":
        if len(args) < 2:
            print("Укажите расширение: new .exe  или  new .obj")
            sys.exit(1)
        cmd_new(args[1])
        return

    if first == "install":
        cmd_install()
        return

    if first in ("help", "-h", "--help"):
        cmd_help()
        return

    # Иначе первый аргумент — путь к файлу для редактирования
    filepath = Path(args[0])
    if not filepath.is_absolute():
        filepath = Path.cwd() / filepath

    if not filepath.exists():
        print(f"Файл не найден: {filepath}")
        sys.exit(1)

    # TUI: blessed или ANSI fallback (добавляем папку скрипта в path для импорта editor)
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from editor import _get_terminal, HexEditor
    except ImportError as e:
        print(f"Ошибка импорта редактора: {e}")
        sys.exit(1)

    term = _get_terminal()
    editor = HexEditor(term, filepath)
    editor.run()


if __name__ == "__main__":
    main()
