"""
TUI HEX-редактор: сетка 16 байт, навигация стрелками, ввод 0-9/a-f (полубайт), статус-бар с первыми 4 байтами.
Движок: blessed или ANSI fallback.
"""

import sys
import time
from pathlib import Path
from typing import Optional, Any

from pe_parser import create_parser_if_supported


BYTES_PER_ROW = 16
HEX_WIDTH = 3


class _Key:
    def __init__(self, name: str, code: Optional[int] = None):
        self.name = name
        self.code = code
        # Для blessed: is_sequence = True для стрелок и т.д.; для одиночного символа — False
        self.is_sequence = bool(name and (name.startswith("KEY_") or len(name) > 1))

    def isprintable(self) -> bool:
        return len(self.name) == 1 and self.name.isprintable() if self.name else False

    def lower(self) -> str:
        return (self.name or "").lower()


class ANSITerminal:
    """Fallback: ANSI-коды + чтение клавиш (msvcrt / termios)."""

    def __init__(self):
        self._width = 80
        self._height = 24
        self._reverse = "\033[7m"
        self._normal = "\033[0m"
        self._bold_white_on_blue = "\033[1;37;44m"
        try:
            import shutil
            c = shutil.get_terminal_size()
            self._width = c.columns
            self._height = c.lines
        except Exception:
            pass

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def fullscreen(self):
        return _NullContext()

    def cbreak(self):
        return _NullContext()

    def hidden_cursor(self):
        return _NullContext()

    def clear(self) -> str:
        return "\033[2J\033[H"

    def move_xy(self, x: int, y: int) -> str:
        return f"\033[{y + 1};{x + 1}H"

    def move_yx(self, y: int, x: int) -> str:
        """Переход на (row=y, col=x) для привязки футера к низу экрана."""
        return f"\033[{y + 1};{x + 1}H"

    @property
    def reverse(self) -> str:
        return self._reverse

    @property
    def normal(self) -> str:
        return self._normal

    @property
    def bold_white_on_blue(self) -> str:
        return self._bold_white_on_blue

    @property
    def on_blue(self) -> str:
        return "\033[44;37m"

    @property
    def nibble_highlight(self) -> str:
        return "\033[33;1m"  # bold yellow

    @property
    def yellow_bold(self) -> str:
        return "\033[33;1m"

    @property
    def black_on_yellow(self) -> str:
        return "\033[30;43m"

    @property
    def black_on_white(self) -> str:
        return "\033[30;47m"

    def inkey(self, timeout: Optional[float] = None):
        if sys.platform == "win32":
            try:
                import msvcrt
                import time
                if timeout is not None and timeout > 0:
                    end = time.time() + timeout
                    while time.time() < end:
                        if msvcrt.kbhit():
                            ch = msvcrt.getch()
                            break
                        time.sleep(0.02)
                    else:
                        return _Key("", None)
                elif timeout is not None and timeout == 0:
                    if not msvcrt.kbhit():
                        return _Key("", None)
                    ch = msvcrt.getch()
                else:
                    ch = msvcrt.getch()
                if ch in (b"\x00", b"\xe0"):
                    ch2 = msvcrt.getch()
                    code = ch2[0] if ch2 else 0
                    arrow = {72: "KEY_UP", 80: "KEY_DOWN", 75: "KEY_LEFT", 77: "KEY_RIGHT",
                             73: "KEY_PPAGE", 81: "KEY_NPAGE", 71: "KEY_HOME", 79: "KEY_END"}
                    return _Key(arrow.get(code, ""), code)
                if ch == b"\x13":
                    return _Key("KEY_CTRL_S", 19)
                return _Key(chr(ch[0]) if ch and ch[0] >= 32 else "", ch[0] if ch else None)
            except Exception:
                return _Key("q", ord("q"))
        else:
            try:
                import termios
                import tty
                import select
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    if timeout is not None and timeout == 0:
                        r, _, _ = select.select([fd], [], [], 0)
                        if not r:
                            return _Key("", None)
                    buf = sys.stdin.read(1)
                    if not buf:
                        return _Key("", None)
                    if buf == "\x1b":
                        if sys.stdin in select.select([sys.stdin], [], [], 0.05)[0]:
                            buf += sys.stdin.read(2)
                        if buf == "\x1b[A": return _Key("KEY_UP", None)
                        if buf == "\x1b[B": return _Key("KEY_DOWN", None)
                        if buf == "\x1b[C": return _Key("KEY_RIGHT", None)
                        if buf == "\x1b[D": return _Key("KEY_LEFT", None)
                        if buf == "\x1b[1~": return _Key("KEY_HOME", None)
                        if buf == "\x1b[4~": return _Key("KEY_END", None)
                        if buf == "\x1b[5~": return _Key("KEY_PPAGE", None)
                        if buf == "\x1b[6~": return _Key("KEY_NPAGE", None)
                    if buf == "\x13":
                        return _Key("KEY_CTRL_S", 19)
                    return _Key(buf, ord(buf) if buf else None)
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                return _Key("q", ord("q"))


class _NullContext:
    def __enter__(self):
        return None
    def __exit__(self, *args):
        return False


def _get_terminal() -> Any:
    try:
        from blessed import Terminal
        return Terminal()
    except ImportError:
        return ANSITerminal()


class HexEditor:
    """Консольный HEX-редактор: стрелки — навигация, 0-9/a-f — ввод полубайта в bytearray."""

    def __init__(self, term: Any, filepath: Path):
        self.term = term
        self.filepath = filepath
        self.data = bytearray(filepath.read_bytes())
        self.cursor = 0
        self.editing_high_nibble = True  # True = редактируем левую половинку байта (старший ниббл)
        self.offset_y = 0
        self.buffer: Optional[int] = None  # буфер обмена (один байт для C/V)
        self.dirty: bool = False  # есть несохранённые изменения (для подтверждения выхода)
        self._status_message: Optional[str] = None
        self._status_message_until: float = 0
        self._confirm_exit: bool = False  # показать "Выйти? Y/N"
        self.show_help: bool = True  # показывать подсказки Nano (False — только статус-бар, больше места под байты)
        self.pe_parser: Optional[object] = None
        try:
            self.pe_parser = create_parser_if_supported(filepath)
        except Exception:
            pass
        self._initial_size: int = len(self.data)  # для проверки при сохранении
        self._compute_layout()

    def _compute_layout(self) -> None:
        self.addr_width = 8
        self.hex_start = self.addr_width + 1
        self.hex_bytes_total = BYTES_PER_ROW * HEX_WIDTH
        self.ascii_start = self.hex_start + self.hex_bytes_total + 1

    def _rows_available(self) -> int:
        # Если show_help: 3 строки внизу (статус + 2 подсказки). Иначе только 1 строка (статус) — больше места под байты
        reserve = 4 if self.show_help else 2
        return max(1, self.term.height - reserve)

    def _total_rows(self) -> int:
        return (len(self.data) + BYTES_PER_ROW - 1) // BYTES_PER_ROW

    def _ensure_cursor_visible(self) -> None:
        row = self.cursor // BYTES_PER_ROW
        h = self._rows_available()
        if row < self.offset_y:
            self.offset_y = row
        elif row >= self.offset_y + h:
            self.offset_y = row - h + 1
        self.offset_y = max(0, min(self.offset_y, max(0, self._total_rows() - h)))

    def render_all(self) -> None:
        """Полная перерисовка: скролл, одна очистка экрана, сетка, затем футер (без повторной очистки — без мерцания)."""
        self._ensure_cursor_visible()
        clear = self.term.clear
        out_clear = clear() if callable(clear) else clear
        sys.stdout.write(out_clear)
        self._draw_grid()
        self.draw_footer()
        sys.stdout.flush()

    def _draw_grid(self) -> None:
        """Только сетка байт (без очистки экрана и без футера — футер в draw_footer)."""
        out = []
        h = self._rows_available()
        w = self.term.width
        nrm = getattr(self.term, "normal", "\033[0m")
        cur_style = getattr(self.term, "black_on_yellow", None) or getattr(self.term, "reverse", "\033[7m")
        nib = getattr(self.term, "nibble_highlight", "\033[33;1m")

        for i in range(h):
            row_global = self.offset_y + i
            addr = row_global * BYTES_PER_ROW
            if addr >= len(self.data):
                break
            addr_str = f"{addr:08X}"
            hex_segments = []
            ascii_segments = []
            for col in range(BYTES_PER_ROW):
                current_index = addr + col
                if current_index >= len(self.data):
                    hex_segments.append("  ")
                    ascii_segments.append(" ")
                    continue
                b = self.data[current_index]
                hex_byte = f"{b:02X}"
                ascii_char = chr(b) if 32 <= b < 127 else "."
                if current_index == self.cursor:
                    if self.editing_high_nibble:
                        hex_segments.append(nib + hex_byte[0] + nrm + cur_style + hex_byte[1] + nrm)
                    else:
                        hex_segments.append(cur_style + hex_byte[0] + nrm + nib + hex_byte[1] + nrm)
                    ascii_segments.append(cur_style + ascii_char + nrm)
                else:
                    hex_segments.append(hex_byte)
                    ascii_segments.append(ascii_char)
            hex_str = " ".join(hex_segments)
            ascii_str = "".join(ascii_segments)
            line = addr_str + " " + hex_str + " " + ascii_str
            if len(line) > w:
                line = line[:w]
            out.append(self.term.move_xy(0, i))
            out.append(line)
        sys.stdout.write("".join(str(x) for x in out))

    def draw_footer(self) -> None:
        """Отрисовка футера: статус-бар всегда; подсказки Nano — только если self.show_help. Без очистки экрана (move_yx + текст)."""
        w = self.term.width
        move_yx = getattr(self.term, "move_yx", None)
        move_xy = self.term.move_xy

        def goto(row: int, col: int = 0) -> str:
            if callable(move_yx):
                return move_yx(row, col)
            return move_xy(col, row)

        if self.show_help:
            status_row = self.term.height - 3
            hint_row1 = self.term.height - 2
            hint_row2 = self.term.height - 1
            self._draw_status(status_row, w, goto)
            self._draw_hint_block(hint_row1, hint_row2, w, goto)
        else:
            status_row = self.term.height - 1
            self._draw_status(status_row, w, goto)

    def _draw_status(self, row: int, w: int, goto) -> None:
        """Строка статус-бара: [ Файл ] [ Байт ] [ Ниббл ]. Только move_yx + текст, без очистки."""
        norm = getattr(self.term, "normal", "\033[0m")
        style = getattr(self.term, "bold_white_on_blue", None) or getattr(self.term, "on_blue", None) or getattr(self.term, "reverse", "\033[7m")
        nibble_str = "High" if self.editing_high_nibble else "Low"
        byte_hex = f"0x{self.data[self.cursor]:02X}" if self.data and self.cursor < len(self.data) else "0x??"
        s = f" [ Файл: {self.filepath.name} ]  [ Байт: {byte_hex} ]  [ Ниббл: {nibble_str} ] "
        if self._confirm_exit:
            s += "  Выйти? Y/N "
        elif self._status_message and time.time() < self._status_message_until:
            bright = getattr(self.term, "bold", "\033[1m") or getattr(self.term, "yellow_bold", "\033[33;1m")
            s += "  " + bright + self._status_message + norm
        s = s[: w - 1]
        sys.stdout.write(goto(row) + style + s + norm + "\n")

    def _draw_hint_block(self, row1: int, row2: int, w: int, goto) -> None:
        """Строки 2 и 3 футера: самые нижние две строки экрана, подсказки Nano с префиксом ^. Прилипают к низу при ресайзе."""
        nrm = getattr(self.term, "normal", "\033[0m")
        key_style = getattr(self.term, "bold", "\033[1m") or getattr(self.term, "reverse", "\033[7m")
        col_width = 16
        line1_blocks = [
            ("^Q", "Выход"),
            ("^S", "Сохранить"),
            ("^C", "Копировать"),
        ]
        line2_blocks = [
            ("^G", "Перейти"),
            ("^H", "Помощь"),
            ("^V", "Вставить"),
        ]

        def make_line(blocks: list) -> str:
            parts = []
            for k, txt in blocks:
                block = (k + " " + txt).ljust(col_width)
                parts.append(key_style + block[:2] + nrm + block[2:])
            return "".join(parts)[:w]

        sys.stdout.write(goto(row1) + make_line(line1_blocks) + "\n")
        sys.stdout.write(goto(row2) + make_line(line2_blocks))

    def _show_help(self) -> None:
        msg = [
            "HexNano — стрелки: навигация | 0-9, a-f: ввод HEX (ниббл)",
            "S или Ctrl+S — сохранить | R — перезагрузить с диска",
            "Q — выход | H — справка",
            "",
            "Нажмите любую клавишу...",
        ]
        w = min(60, self.term.width - 4)
        y0, x0 = 2, 2
        sys.stdout.write(self.term.move_xy(x0, y0) + "+" + "-" * (w - 2) + "+")
        for i, line in enumerate(msg):
            sys.stdout.write(self.term.move_xy(x0, y0 + 1 + i) + "|" + (line[:w - 2].ljust(w - 2)) + "|")
        sys.stdout.write(self.term.move_xy(x0, y0 + len(msg) + 1) + "+" + "-" * (w - 2) + "+")
        sys.stdout.flush()
        self.term.inkey()

    def save(self) -> bool:
        """Записать self.data в файл. При успехе — сообщение в статус-баре на 1–2 сек."""
        try:
            with open(self.filepath, "wb") as f:
                f.write(bytes(self.data))
            self._initial_size = len(self.data)
            self.dirty = False
            self._status_message = "[ СОХРАНЕНО ]"
            self._status_message_until = time.time() + 1.0
            return True
        except Exception:
            return False

    def reload(self) -> None:
        """Перезагрузить файл с диска (отмена несохранённых изменений)."""
        self.data = bytearray(self.filepath.read_bytes())
        self._initial_size = len(self.data)
        self.cursor = min(self.cursor, len(self.data) - 1) if self.data else 0
        self.editing_high_nibble = True
        self.dirty = False

    def handle_input(self, char: str) -> bool:
        """
        Обработка ввода 0-9 и a-f. editing_high_nibble True — левая часть байта, False — правая.
        После ввода правой части: editing_high_nibble = True и курсор на один байт вправо.
        """
        if not self.data:
            return False
        char = char.upper()
        if char not in "0123456789ABCDEF":
            return False
        val = int(char, 16)
        idx = self.cursor
        if self.editing_high_nibble:
            self.data[idx] = (val << 4) | (self.data[idx] & 0x0F)
            self.editing_high_nibble = False
        else:
            self.data[idx] = (self.data[idx] & 0xF0) | val
            self.editing_high_nibble = True
            if idx < len(self.data) - 1:
                self.cursor += 1
        return True

    def _move_left(self) -> None:
        if self.editing_high_nibble and self.cursor > 0:
            self.cursor -= 1
            self.editing_high_nibble = False
        else:
            self.editing_high_nibble = True

    def _move_right(self) -> None:
        if not self.editing_high_nibble and self.cursor < len(self.data) - 1:
            self.cursor += 1
            self.editing_high_nibble = True
        else:
            self.editing_high_nibble = False

    def _move_up(self) -> None:
        if self.cursor >= BYTES_PER_ROW:
            self.cursor -= BYTES_PER_ROW
            self.editing_high_nibble = True

    def _move_down(self) -> None:
        if self.cursor + BYTES_PER_ROW < len(self.data):
            self.cursor += BYTES_PER_ROW
            self.editing_high_nibble = True

    def run(self) -> None:
        fullscreen = getattr(self.term, "fullscreen", None)
        ctx_full = fullscreen() if callable(fullscreen) else _NullContext()
        with ctx_full:
            # Критично для blessed: cbreak + hidden_cursor, чтобы ловить стрелки и ввод
            cbreak = getattr(self.term, "cbreak", None)
            hidden = getattr(self.term, "hidden_cursor", None)
            if callable(cbreak) and callable(hidden):
                with cbreak(), hidden():
                    self._run_loop()
            elif callable(cbreak):
                with cbreak():
                    self._run_loop()
            else:
                self._run_loop()

    def _run_loop(self) -> None:
        if not self.data:
            clear = self.term.clear
            sys.stdout.write(clear() if callable(clear) else clear)
            sys.stdout.write(self.term.move_xy(0, 0) + " (пустой файл) ")
            self.draw_footer()
            sys.stdout.flush()
            self.term.inkey()
            return

        while True:
            key = self.term.inkey(timeout=0.1)
            # Пустой ключ (таймаут или пустой ввод)
            if not key or (getattr(key, "name", None) == "" and getattr(key, "code", None) is None):
                continue

            key_name = getattr(key, "name", None) or ""
            key_lower = (key_name.lower() if isinstance(key_name, str) else "") or (
                key.lower() if hasattr(key, "lower") and callable(key.lower) else ""
            )
            if isinstance(key_lower, str) and len(key_lower) != 1:
                key_lower = key_lower[:1] if key_lower else ""
            is_sequence = getattr(key, "is_sequence", True)
            kcode = getattr(key, "code", None)

            # Подтверждение выхода: при несохранённых изменениях ждём Y/N
            if self._confirm_exit:
                if key_lower in ("y", "н"):
                    break
                if key_lower in ("n", "т"):
                    self._confirm_exit = False
                self._ensure_cursor_visible()
                self.render_all()
                continue

            # ========== ПРИОРИТЕТ КОМАНД: системные кнопки ДО проверки на hex (s/ы, q/й, c/с, v/м и др.) ==========
            if key_lower == "q" or key_lower == "й":
                if self.dirty:
                    self._confirm_exit = True
                else:
                    break
                self._ensure_cursor_visible()
                self.render_all()
                continue
            if key_lower == "s" or key_lower == "ы" or kcode == 19:
                if self.save():
                    self._ensure_cursor_visible()
                    self.render_all()
                continue
            if key_lower == "c" or key_lower == "с":
                if self.data:
                    self.buffer = self.data[self.cursor] & 0xFF
                self._ensure_cursor_visible()
                self.render_all()
                continue
            if key_lower == "v" or key_lower == "м":
                if self.buffer is not None and self.data:
                    self.data[self.cursor] = self.buffer & 0xFF
                    self.dirty = True
                self._ensure_cursor_visible()
                self.render_all()
                continue
            if key_lower == "r" or key_lower == "к":
                self.reload()
                self._ensure_cursor_visible()
                self.render_all()
                continue
            if key_lower == "h" or key_lower == "р":
                self._show_help()
                self._ensure_cursor_visible()
                self.render_all()
                continue
            if key_lower == "g" or key_lower == "п":
                self._status_message = "Перейти по адресу (в разработке)"
                self._status_message_until = time.time() + 1.5
                self._ensure_cursor_visible()
                self.render_all()
                continue
            if key_lower in ("ё", "`", "~") or (kcode is not None and kcode in (ord("ё"), ord("`"), ord("~"), 0)):
                self.show_help = not self.show_help
                self._ensure_cursor_visible()
                self.render_all()
                continue
            if key_name in ("KEY_ESCAPE", "escape", "esc") or kcode == 27:
                self._confirm_exit = False
                break

            if is_sequence:
                # Только навигация и спецклавиши
                if key_name in ("KEY_LEFT", "left"):
                    self.cursor = max(0, self.cursor - 1)
                elif key_name in ("KEY_RIGHT", "right"):
                    self.cursor = min(len(self.data) - 1, self.cursor + 1)
                elif key_name in ("KEY_UP", "up"):
                    self.cursor = max(0, self.cursor - 16)
                elif key_name in ("KEY_DOWN", "down"):
                    self.cursor = min(len(self.data) - 1, self.cursor + 16)
                elif key_name == "KEY_PPAGE":
                    self.cursor = max(0, self.cursor - self._rows_available() * BYTES_PER_ROW)
                elif key_name == "KEY_NPAGE":
                    self.cursor = min(len(self.data) - 1, self.cursor + self._rows_available() * BYTES_PER_ROW)
                elif key_name in ("KEY_HOME", "home"):
                    self.cursor = 0
                elif key_name in ("KEY_END", "end"):
                    self.cursor = max(0, len(self.data) - 1)
                elif key_name in ("KEY_ESCAPE", "escape", "esc") or kcode == 27:
                    pass
                self.editing_high_nibble = True

            elif key_lower in "0123456789abcdef":
                # Hex-ввод срабатывает ТОЛЬКО если клавиша не была системной (q/s/c/v/r/h/g/ё уже обработаны выше)
                val = int(key_lower, 16)
                if self.editing_high_nibble:
                    self.data[self.cursor] = (val << 4) | (self.data[self.cursor] & 0x0F)
                    self.editing_high_nibble = False
                else:
                    self.data[self.cursor] = (self.data[self.cursor] & 0xF0) | val
                    self.editing_high_nibble = True
                    self.cursor = min(len(self.data) - 1, self.cursor + 1)
                self.dirty = True

            # Курсор и скролл: обновить offset_y, чтобы курсор не ушёл за край экрана
            self._ensure_cursor_visible()
            self.render_all()
