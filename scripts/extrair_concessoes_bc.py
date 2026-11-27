"""Extrai as concessões ajustadas das tabelas mensais do BC para o painel."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from openpyxl import load_workbook


MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()
CODIGOS = {2: (24442, 24445, 24439), 3: (24440, 24441, 24439),
           4: (24443, 24444, 24442), 5: (24446, 24447, 24445)}
DESTINO = Path(__file__).resolve().parents[1] / "data/bundled/mercado_credito_sgs/concessoes_ajustadas_tabelas.json"


def extrair(arquivo: Path, publicado_em: date, destino: Path) -> None:
    workbook = load_workbook(arquivo, read_only=True, data_only=True)
    meses = {}
    try:
        for tabela, codigos in CODIGOS.items():
            linhas = list(workbook[f"Tab {tabela}"].values)
            if tuple(linhas[6][7:10]) != codigos or not all(
                "sazonalmente ajustadas" in nome.lower() and "R$ bilhões" in nome
                for nome in linhas[3][7:10]
            ):
                raise ValueError(f"Conferir códigos e unidade nas colunas H:J da tabela {tabela}")
            for linha in linhas[7:]:
                periodo = re.fullmatch(r"([a-z]{3})-(\d{4})\*?", str(linha[0]).lower())
                if not periodo:
                    continue
                mes, ano = periodo.groups()
                data_base = f"{ano}-{MESES.index(mes) + 1:02d}"
                valores = meses.setdefault(data_base, {})
                for codigo, valor in zip(codigos, linha[7:10]):
                    if not isinstance(valor, (int, float)) or round(valor, 1) != valor:
                        raise ValueError(f"Montante ausente ou com precisão inesperada: {data_base}, SGS {codigo}")
                    if valores.setdefault(codigo, valor) != valor:
                        raise ValueError(f"Tabelas divergentes: {data_base}, SGS {codigo}")
    finally:
        workbook.close()
    codigos = sorted({c for grupo in CODIGOS.values() for c in grupo})
    if not meses or any(set(v) != set(codigos) for v in meses.values()):
        raise ValueError("Faltam aberturas nas séries de concessões")
    url = ("https://www.bcb.gov.br/content/estatisticas/hist_estatisticasmonetariascredito/"
           f"{publicado_em:%Y%m}_Tabelas_de_estatisticas_monetarias_e_de_credito.xlsx")
    ficha = dict(publicado_em=publicado_em.isoformat(), fonte=url, unidade="R$ bilhões",
                 sha256_xlsx=hashlib.sha256(arquivo.read_bytes()).hexdigest(), codigos_sgs=codigos)
    cabecalho = json.dumps(ficha, ensure_ascii=False, indent=2).removesuffix("\n}")
    registros = [json.dumps([mes, *(valores[c] for c in codigos)]) for mes, valores in sorted(meses.items())]
    destino.write_text(cabecalho + ',\n  "dados": [\n    ' + ",\n    ".join(registros) + "\n  ]\n}\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arquivo", type=Path)
    parser.add_argument("--publicado-em", type=date.fromisoformat, required=True)
    parser.add_argument("--destino", type=Path, default=DESTINO)
    args = parser.parse_args()
    extrair(args.arquivo, args.publicado_em, args.destino)
