"""
Logger com cores para o terminal.
Uso: from src.logger import log
      log.info("PIPELINE", "mensagem")
      log.warn("XLSX", "aviso")
      log.error("EXTRACT", "erro")
      log.success("RELATORIO", "concluido")
"""
from __future__ import annotations

import sys


class _Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Cores do texto
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"


def _supports_color() -> bool:
    """Verifica se o terminal suporta ANSI."""
    if sys.platform == "win32":
        # Windows 10+ suporta ANSI com configuracao
        try:
            import os
            os.system("")  # ativa sequencias ANSI no cmd/PowerShell
            return True
        except Exception:
            return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_COLOR = _supports_color()


def _c(color: str, text: str) -> str:
    """Aplica cor se o terminal suportar."""
    if _COLOR:
        return f"{color}{text}{_Colors.RESET}"
    return text


# Cores por modulo (cada tag tem sua cor)
_MODULE_COLORS = {
    "PIPELINE": _Colors.CYAN,
    "EXTRACT": _Colors.BLUE,
    "RELATORIO": _Colors.MAGENTA,
    "MD": _Colors.GREEN + _Colors.BOLD,
    "PDF": _Colors.RED + _Colors.BOLD,
    "XLSX": _Colors.YELLOW + _Colors.BOLD,
    "RAG": _Colors.GREEN,
    "REVISAO": _Colors.WHITE,
    "PARSE": _Colors.GRAY,
    "REPORT_EXTRACT": _Colors.DIM + _Colors.CYAN,
    "CHAT": _Colors.CYAN,
    "CALLBACK": _Colors.MAGENTA + _Colors.BOLD,
    "OPENROUTER": _Colors.BLUE,
    "SERVER": _Colors.GREEN,
}


def _tag_color(tag: str) -> str:
    return _MODULE_COLORS.get(tag, _Colors.WHITE)


class _Logger:
    """Logger com cores e niveis."""

    def info(self, tag: str, msg: str):
        color = _tag_color(tag)
        tag_str = _c(color, f"[{tag}]")
        print(f"{tag_str} {msg}")

    def warn(self, tag: str, msg: str):
        color = _tag_color(tag)
        tag_str = _c(color, f"[{tag}]")
        warn_str = _c(_Colors.YELLOW + _Colors.BOLD, "AVISO")
        print(f"{tag_str} {warn_str}: {msg}")

    def error(self, tag: str, msg: str):
        color = _tag_color(tag)
        tag_str = _c(color, f"[{tag}]")
        err_str = _c(_Colors.RED + _Colors.BOLD, "ERRO")
        print(f"{tag_str} {err_str}: {msg}", file=sys.stderr)

    def success(self, tag: str, msg: str):
        color = _tag_color(tag)
        tag_str = _c(color, f"[{tag}]")
        ok_str = _c(_Colors.GREEN + _Colors.BOLD, "OK")
        print(f"{tag_str} {ok_str}: {msg}")

    def step(self, tag: str, step_num: str, msg: str):
        """Para logs de pipeline com numero do no."""
        color = _tag_color(tag)
        tag_str = _c(color, f"[{tag}]")
        step_str = _c(_Colors.CYAN + _Colors.BOLD, f"No {step_num}")
        print(f"{tag_str} {step_str} - {msg}")

    def separator(self, tag: str):
        color = _tag_color(tag)
        line = _c(_Colors.DIM, "=" * 60)
        print(f"\n{line}")
        tag_str = _c(color + _Colors.BOLD, f"[{tag}]")
        print(f"{tag_str}")


log = _Logger()
