# HexNano

Профессиональный консольный HEX-редактор на Python с TUI на базе **blessed** (кроссплатформенно; при отсутствии blessed используется режим ANSI).

## Установка

```bash
pip install -r requirements.txt
```

Для добавления в PATH и создания `hexnano.bat` (Windows):

```bash
python hexnano.py install
```

Команда `install` также проверяет наличие `blessed` и при необходимости пытается установить его через `pip install blessed`. В папке со скриптом создаётся `hexnano.bat` с содержимым:

```bat
@echo off
python "%~dp0hexnano.py" %*
```

После добавления папки в PATH можно вызывать: `hexnano file.exe` или `hexnano.bat file.exe`.

## Использование

### CLI

| Команда | Описание |
|--------|----------|
| `hexnano install` | Добавить папку в PATH, создать hexnano.bat, проверить/установить blessed |
| `hexnano help` | Список команд |
| `hexnano new .exe` | Создать файл с минимальным PE (MZ, PE, пустая таблица секций) |
| `hexnano new .obj` | Создать минимальный COFF/OBJ |
| `hexnano <файл>` | Открыть файл в HEX-редакторе |

Важно: команда **new** — только если первый аргумент ровно `new`, второй — расширение (`.exe` или `.obj`). Иначе первый аргумент считается путём к файлу.

### TUI (в редакторе)

- **Стрелки** — навигация по байтам
- **0–9, A–F** — ввод HEX (полубайт под курсором)
- **Ctrl+S** — сохранить
- **Q** — выход
- **H** — справка

Сетка: 16 байт в строке; слева адреса (00000000), в центре HEX, справа ASCII. Подсветка текущего байта, прокрутка для больших файлов.

### PE/OBJ и статус-бар

При открытии `.exe` или `.obj` в статус-баре отображаются: смещение PE-сигнатуры, **Arch: x86** / **Arch: x64** (по полю Machine в COFF), Entry Point, ImageBase и др.

## Структура проекта

- `hexnano.py` — точка входа: CLI (install, help, new), запуск TUI (blessed или ANSI)
- `editor.py` — класс `HexEditor`, движок TUI (blessed или ANSI fallback)
- `pe_parser.py` — класс `PEParser`: разбор PE/COFF, определение архитектуры
- `requirements.txt` — зависимость `blessed`
- `hexnano.bat` — создаётся при `install` (Windows)
