"""
Gerador de ícones vetoriais (em PhotoImage nativo do Tkinter, sem depender de arquivos externos nem emojis).
Desenha ícones nítidos pixel-a-pixel em Canvas/PhotoImage de 16x16.
"""

import tkinter as tk
from typing import Dict


class VectorIconFactory:
    """Cria e mantém em cache objetos tk.PhotoImage de 16x16 com ícones limpos e profissionais."""

    def __init__(self):
        self._cache: Dict[str, tk.PhotoImage] = {}

    def get(self, name: str, fg: str = "#FFFFFF") -> tk.PhotoImage:
        key = f"{name}_{fg}"
        if key in self._cache:
            return self._cache[key]
        img = tk.PhotoImage(width=16, height=16)
        self._draw_icon(img, name, fg)
        self._cache[key] = img
        return img

    def _rect(self, img: tk.PhotoImage, x1: int, y1: int, x2: int, y2: int, color: str):
        img.put(color, to=(max(0, x1), max(0, y1), min(16, x2), min(16, y2)))

    def _hline(self, img: tk.PhotoImage, x1: int, x2: int, y: int, color: str, thick: int = 1):
        self._rect(img, x1, y, x2, y + thick, color)

    def _vline(self, img: tk.PhotoImage, x: int, y1: int, y2: int, color: str, thick: int = 1):
        self._rect(img, x, y1, x + thick, y2, color)

    def _draw_icon(self, img: tk.PhotoImage, name: str, fg: str):
        if name == "printer":
            # Topo do papel
            self._hline(img, 4, 12, 2, fg, 1)
            self._vline(img, 4, 2, 6, fg, 1)
            self._vline(img, 11, 2, 6, fg, 1)
            # Corpo da impressora
            self._rect(img, 2, 6, 14, 12, fg)
            # Papel saindo embaixo
            self._rect(img, 5, 10, 11, 14, fg)

        elif name == "barcode":
            # Barras verticais de espessuras variadas
            for x, w in [(2, 2), (5, 1), (7, 2), (10, 1), (12, 2)]:
                self._rect(img, x, 2, x + w, 14, fg)

        elif name == "plus":
            self._rect(img, 7, 3, 9, 13, fg)
            self._rect(img, 3, 7, 13, 9, fg)

        elif name == "box":
            # Caixa / Kit
            self._hline(img, 2, 14, 3, fg, 2)
            self._hline(img, 2, 14, 12, fg, 2)
            self._vline(img, 2, 3, 14, fg, 2)
            self._vline(img, 12, 3, 14, fg, 2)
            self._hline(img, 2, 14, 7, fg, 1)
            self._vline(img, 7, 3, 8, fg, 2)

        elif name == "edit":
            # Lápis diagonal
            for i in range(8):
                self._rect(img, 4 + i, 10 - i, 6 + i, 12 - i, fg)
            self._rect(img, 2, 12, 5, 14, fg)

        elif name == "trash":
            # Lixeira
            self._hline(img, 3, 13, 3, fg, 2)
            self._rect(img, 6, 1, 10, 3, fg)
            self._vline(img, 4, 5, 14, fg, 2)
            self._vline(img, 10, 5, 14, fg, 2)
            self._hline(img, 4, 12, 13, fg, 2)
            self._vline(img, 7, 6, 12, fg, 2)

        elif name == "upload":
            # Seta para cima + bandeja
            self._vline(img, 7, 3, 11, fg, 2)
            self._rect(img, 5, 5, 11, 7, fg)
            self._rect(img, 6, 3, 10, 5, fg)
            self._hline(img, 2, 14, 13, fg, 2)

        elif name == "download":
            # Seta para baixo + bandeja
            self._vline(img, 7, 2, 10, fg, 2)
            self._rect(img, 5, 7, 11, 9, fg)
            self._rect(img, 6, 9, 10, 11, fg)
            self._hline(img, 2, 14, 13, fg, 2)

        elif name == "save":
            # Disquete
            self._hline(img, 2, 13, 2, fg, 2)
            self._hline(img, 2, 14, 12, fg, 2)
            self._vline(img, 2, 2, 14, fg, 2)
            self._vline(img, 12, 2, 14, fg, 2)
            self._rect(img, 5, 2, 10, 6, fg)
            self._rect(img, 5, 9, 11, 13, fg)

        elif name == "search":
            # Lupa
            self._hline(img, 4, 10, 3, fg, 2)
            self._hline(img, 4, 10, 9, fg, 2)
            self._vline(img, 3, 4, 9, fg, 2)
            self._vline(img, 9, 4, 9, fg, 2)
            for i in range(4):
                self._rect(img, 9 + i, 9 + i, 11 + i, 11 + i, fg)

        elif name == "refresh":
            self._hline(img, 4, 12, 3, fg, 2)
            self._hline(img, 4, 12, 11, fg, 2)
            self._vline(img, 3, 4, 11, fg, 2)
            self._vline(img, 11, 6, 11, fg, 2)
            self._rect(img, 10, 2, 14, 6, fg)

        elif name == "copy":
            self._hline(img, 2, 10, 2, fg, 2)
            self._vline(img, 2, 2, 10, fg, 2)
            self._hline(img, 5, 14, 5, fg, 2)
            self._hline(img, 5, 14, 13, fg, 2)
            self._vline(img, 5, 5, 14, fg, 2)
            self._vline(img, 12, 5, 14, fg, 2)

        elif name == "check":
            self._rect(img, 3, 8, 5, 10, fg)
            self._rect(img, 5, 10, 7, 12, fg)
            self._rect(img, 7, 8, 9, 10, fg)
            self._rect(img, 9, 6, 11, 8, fg)
            self._rect(img, 11, 4, 13, 6, fg)

        elif name == "uncheck":
            self._hline(img, 3, 13, 3, fg, 2)
            self._hline(img, 3, 13, 11, fg, 2)
            self._vline(img, 3, 3, 13, fg, 2)
            self._vline(img, 11, 3, 13, fg, 2)

        elif name == "prev":
            self._rect(img, 9, 3, 11, 5, fg)
            self._rect(img, 7, 5, 9, 7, fg)
            self._rect(img, 5, 7, 7, 9, fg)
            self._rect(img, 7, 9, 9, 11, fg)
            self._rect(img, 9, 11, 11, 13, fg)

        elif name == "next":
            self._rect(img, 5, 3, 7, 5, fg)
            self._rect(img, 7, 5, 9, 7, fg)
            self._rect(img, 9, 7, 11, 9, fg)
            self._rect(img, 7, 9, 9, 11, fg)
            self._rect(img, 5, 11, 7, 13, fg)

        elif name == "grid":
            for x in (2, 9):
                for y in (2, 9):
                    self._rect(img, x, y, x + 5, y + 5, fg)

        elif name == "tag":
            self._hline(img, 2, 14, 3, fg, 2)
            self._hline(img, 2, 14, 11, fg, 2)
            self._vline(img, 2, 3, 13, fg, 2)
            self._vline(img, 12, 3, 13, fg, 2)
            self._hline(img, 5, 11, 6, fg, 1)
            self._hline(img, 5, 9, 8, fg, 1)

        elif name in ("route", "pin", "map"):
            # Marcador de localização / Rota (Pin superior + trilha inferior)
            self._rect(img, 6, 1, 10, 3, fg)
            self._rect(img, 4, 3, 6, 7, fg)
            self._rect(img, 10, 3, 12, 7, fg)
            self._rect(img, 5, 7, 11, 9, fg)
            self._rect(img, 6, 9, 10, 11, fg)
            self._rect(img, 7, 11, 9, 13, fg)
            self._hline(img, 3, 13, 13, fg, 2)

