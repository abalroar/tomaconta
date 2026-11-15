"""python -m utils.peer_adquirentes atualizar | conferir | exportar [pasta]"""
from __future__ import annotations

import sys
from pathlib import Path

from . import ifdata


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "atualizar"
    if cmd == "atualizar":
        r = ifdata.atualizar()
        ifdata.gravar_situacao(r)
        print(f"último período: {r['ultimo_periodo']} | novas: {r['linhas_novas']} | reapresentadas: {r['reapresentadas']}"
              f" | falhas: {len(r['falhas'])} | alertas: {len(r['alertas'])}")
        return 1 if r["falhas"] else 0
    if cmd == "conferir":
        from .calculo import Peer
        p = Peer(ifdata.visao(ifdata.carregar_base()))
        pend = [c for c in p.conferencias() if c["status"] == "diferença"]
        for c in pend:
            print(c)
        print(f"{len(pend)} pendência(s)")
        return 1 if pend else 0
    if cmd == "exportar":
        from . import vistas, exportar
        pasta = Path(argv[1]) if len(argv) > 1 else Path("outputs/peer_adquirentes")
        pasta.mkdir(parents=True, exist_ok=True)
        d = vistas.Dados.carregar()
        for v in (vistas.comparativo(d), vistas.evolucao(d), *[vistas.por_instituicao(d, k) for k in vistas.C.ORDEM]):
            (pasta / f"{v.chave}.xlsx").write_bytes(exportar.para_excel(v))  # noqa: E501
            (pasta / f"{v.chave}.pptx").write_bytes(exportar.para_pptx(v))
            print("gravado", pasta / v.chave)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
