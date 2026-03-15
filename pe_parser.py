"""
Сигнатура (первые 4 байта) и инспектор структур PE для статус-бара HexNano.
При редактировании байтов внутри PE-заголовка отображается текущее значение поля в десятичном виде.
"""

import struct
from pathlib import Path
from typing import Optional, List, Tuple

# Поля PE: (имя, смещение в файле, размер в байтах)
PE_FIELDS: List[Tuple[str, int, int]] = []


def _read_u16(data: bytes, offset: int) -> Optional[int]:
    if offset + 2 > len(data):
        return None
    return struct.unpack_from("<H", data, offset)[0]


def _read_u32(data: bytes, offset: int) -> Optional[int]:
    if offset + 4 > len(data):
        return None
    return struct.unpack_from("<I", data, offset)[0]


def _build_pe_fields(data: bytes) -> List[Tuple[str, int, int]]:
    """По данным файла строит список (имя_поля, смещение, размер) для PE."""
    out: List[Tuple[str, int, int]] = []
    if len(data) < 64 or data[0:2] != b"MZ":
        return out
    e_lfanew = _read_u32(data, 0x3C)
    if e_lfanew is None or e_lfanew >= len(data) - 4 or data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        return out
    coff = e_lfanew + 4
    size_opt = _read_u16(data, coff + 16)
    if size_opt is None:
        return out
    opt_start = coff + 20
    if opt_start + 24 > len(data):
        return out
    magic = _read_u16(data, opt_start + 0)
    # AddressOfEntryPoint (RVA) — смещение 16 в optional header, 4 байта
    out.append(("AddressOfEntryPoint", opt_start + 16, 4))
    # ImageBase — смещение 28 (PE32) или 24 (PE32+), 4 или 8 байт
    if magic == 0x10B:
        out.append(("ImageBase", opt_start + 28, 4))
    elif magic == 0x20B:
        out.append(("ImageBase", opt_start + 24, 8))
    return out


class PEParser:
    """Первые 4 байта + инспектор полей PE по текущим данным (bytearray)."""

    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self._pe_fields: List[Tuple[str, int, int]] = _build_pe_fields(self.data)

    def get_status_line(self, current_data: Optional[bytearray] = None) -> str:
        """Строка для статус-бара: сигнатура + при необходимости значение поля под курсором."""
        data = current_data if current_data is not None else self.data
        if len(data) == 0:
            return "Сигнатура: (пусто)"
        n = min(4, len(data))
        hex_parts = [f"{data[i]:02X}" for i in range(n)]
        return "Сигнатура: " + " ".join(hex_parts)

    def get_field_at_offset(self, data: bytearray, offset: int) -> Optional[Tuple[str, int]]:
        """
        Если offset попадает в известное поле PE, возвращает (имя_поля, значение_в_десятичном).
        Иначе None.
        """
        for name, field_offset, size in self._pe_fields:
            if field_offset <= offset < field_offset + size:
                if offset + size > len(data):
                    return None
                if size == 4:
                    val = struct.unpack_from("<I", data, field_offset)[0]
                    return (name, val)
                if size == 8:
                    val = struct.unpack_from("<Q", data, field_offset)[0]
                    return (name, val)
                return None
        return None


def create_parser_if_supported(path: Path) -> Optional[PEParser]:
    return PEParser(path)
