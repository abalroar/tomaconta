#!/usr/bin/env python3
"""Valida duplicidade de rótulos no dispatcher de menu do app1.py."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

APP_FILE = Path("app1.py")
CRITICAL_LABELS = [
    "DRE (Ind. e Congl.)",
    "Carteira 4.966",
]

DISPATCH_START = 'if menu == "Sobre":'
MENU_PATTERN = re.compile(r'^(?:if|elif)\s+menu\s*==\s*"([^"]+)"', re.MULTILINE)


def main() -> int:
    if not APP_FILE.exists():
        print(f"ERRO: arquivo não encontrado: {APP_FILE}")
        return 2

    content = APP_FILE.read_text(encoding="utf-8")
    dispatch_start = content.find(DISPATCH_START)
    if dispatch_start < 0:
        print(f"ERRO: início do dispatcher não encontrado: {DISPATCH_START}")
        return 2

    labels = MENU_PATTERN.findall(content[dispatch_start:])
    counts = Counter(labels)

    duplicates = {label: count for label, count in counts.items() if count > 1}
    critical_issues = {
        label: counts.get(label, 0)
        for label in CRITICAL_LABELS
        if counts.get(label, 0) != 1
    }

    if duplicates or critical_issues:
        print("Falha: rótulos duplicados (ou críticos ausentes/duplicados) no dispatcher de menu.")
        if duplicates:
            print("\nDuplicidades encontradas:")
            for label, count in sorted(duplicates.items()):
                print(f"- {label!r}: {count} ocorrência(s)")
        if critical_issues:
            print("\nRótulos críticos com contagem inválida (esperado = 1):")
            for label, count in critical_issues.items():
                print(f"- {label!r}: {count} ocorrência(s)")
        return 1

    print("OK: nenhum rótulo duplicado encontrado no dispatcher de menu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
