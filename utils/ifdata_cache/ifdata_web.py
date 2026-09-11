"""Leitura dos arquivos públicos que alimentam o site IF.data (2025+).

Backend explícito para manutenção da API Olinda. Usa os valores brutos do
BCB, em R$ / decimal, antes da formatação em milhares e percentuais do site.
Não executa JavaScript nem aplica as imputações visuais do site.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re

import pandas as pd
import requests

BASE_URL = "https://www3.bcb.gov.br/ifdata/rest"
SELECTORS = {1: 1009, 3: 1006}
REPORTS = {
    1: "Resumo", 2: "Ativo", 3: "Passivo", 4: "Demonstração de Resultado",
    5: "Informações de Capital",
    11: "Carteira de crédito ativa Pessoa Física - modalidade e prazo de vencimento",
    13: "Carteira de crédito ativa Pessoa Jurídica - modalidade e prazo de vencimento",
    16: "Carteira de crédito ativa - por carteiras de instrumentos financeiros",
}


def _leaves(columns):
    for column in columns:
        if column.get("sc"):
            yield from _leaves(column["sc"])
        else:
            yield column


class IFDataWeb:
    def __init__(self, periodo: str, root: Path):
        if not re.fullmatch(r"202[5-9](03|06|09|12)|2030(03|06|09|12)", str(periodo)):
            raise ValueError("Backend IF.data web suporta trimestres de 2025 a 2030")
        self.periodo = str(periodo)
        self.root = Path(root) / self.periodo
        self.root.mkdir(parents=True, exist_ok=True)
        self.sources = {}
        catalog = self._read("relatorios2025a2030.json", f"{BASE_URL}/relatorios2025a2030")
        matches = [item for item in catalog if str(item.get("dt")) == self.periodo]
        if len(matches) != 1:
            raise ValueError(f"Competência {periodo} não publicada no catálogo IF.data")
        self.catalog = matches[0]
        self.files = {Path(item["f"]).name: item for item in self.catalog["files"]}
        self.info = {item["id"]: item for item in self._file(f"info{periodo}.json")}
        self._cadastros = {}
        self._areas = {}

    def _read(self, name, url, params=None):
        path = self.root / name
        if not path.exists():
            response = requests.get(url, params=params, timeout=(15, 90))
            response.raise_for_status()
            response.json()  # Não persistir páginas de erro como fonte.
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_bytes(response.content)
            temp.replace(path)
        content = path.read_bytes()
        payload = json.loads(content)
        self.sources[name] = {
            "url": requests.Request("GET", url, params=params).prepare().url,
            "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
        }
        (self.root / "sources.json").write_text(json.dumps({
            "periodo": self.periodo, "source": "ifdata_web", "unit": "R$; ratios in decimal",
            "verified_at_utc": datetime.now(timezone.utc).isoformat(), "files": self.sources,
        }, ensure_ascii=False, indent=2) + "\n")
        return payload

    def _file(self, name):
        if name not in self.files:
            raise ValueError(f"Arquivo obrigatório ausente do catálogo: {name}")
        return self._read(name, f"{BASE_URL}/arquivos", {"nomeArquivo": self.files[name]["f"]})

    def cadastro(self, tipo):
        selector = SELECTORS[tipo]
        if selector not in self._cadastros:
            rows = self._file(f"cadastro{self.periodo}_{selector}.json")
            if not rows or any(str(row["c1"]) != self.periodo for row in rows):
                raise ValueError("Cadastro vazio ou com competência divergente")
            for row in rows:
                # Arquivos anteriores a jun/26 codificam o conglomerado sem C.
                # c34=4 identifica o perímetro prudencial; c0 preserva a chave
                # interna de leitura dos valores e nunca é substituído.
                if row.get("c34") == "4" and re.fullmatch(r"0\d{7}", row["c33"]):
                    row["c33"] = "C" + row["c33"][1:]
            codes = [row["c33"] for row in rows]
            if len(set(codes)) != len(codes) or any(not re.fullmatch(r"(?:\d{8}|C\d{7})", code) for code in codes):
                raise ValueError("CodInst ausente, duplicado ou inválido no cadastro IF.data")
            self._cadastros[selector] = rows
        return self._cadastros[selector]

    def cadastro_frame(self):
        rows = [{"CodInst": row["c33"], "NomeInstituicao": row["c2"]}
                for tipo in SELECTORS for row in self.cadastro(tipo)]
        data = pd.DataFrame(rows).drop_duplicates()
        if data["CodInst"].duplicated().any():
            raise ValueError("Nomes conflitantes entre cadastros IF.data para o mesmo CodInst")
        return data

    def _area(self, number):
        if number not in self._areas:
            payload = self._file(f"dados{self.periodo}_{number}.json")
            if payload.get("id") != number:
                raise ValueError("Área IF.data diferente da solicitada")
            values = {}
            for entity in payload["values"]:
                for cell in entity["v"]:
                    key = (str(entity["e"]), int(cell["i"]))
                    if key in values:
                        raise ValueError("Chave entidade/conta duplicada no arquivo IF.data")
                    values[key] = cell["v"]
            self._areas[number] = values
        return self._areas[number]

    def valores(self, relatorio: int, tipo: int):
        name, selector = REPORTS[relatorio], SELECTORS[tipo]
        reports = [item["trel"] for item in self.catalog["files"]
                   if item.get("trel", {}).get("n") == name
                   and {"id": selector} in item["trel"].get("s", [])]
        if len(reports) != 1 or reports[0].get("fx"):
            raise ValueError("Relatório/perímetro ausente, ambíguo ou com filtro não suportado")
        rows = []
        for column in _leaves(reports[0]["c"]):
            info = self.info[column["ifd"]]
            if info.get("ty") != 1 or info["td"] not in (1, 3):
                continue
            # O cadastro marca alguns rótulos textuais (ex.: conglomerado) como
            # numéricos. Apenas as contagens de agências/postos são medidas.
            if info["td"] == 1 and info["lid"] not in (16, 17):
                continue
            values = self._area(info["a"]) if info["td"] == 3 else None
            for entity in self.cadastro(tipo):
                value = (values.get((entity["c0"], info["lid"])) if values is not None
                         else entity.get(f"c{info['lid']}"))
                # Omitir célula ausente impede o pivot histórico de convertê-la em zero.
                if value is None or value == "":
                    continue
                number = float(value)
                rows.append({
                    "TipoInstituicao": tipo, "CodInst": entity["c33"], "AnoMes": self.periodo,
                    "NomeRelatorio": name, "NumeroRelatorio": str(relatorio), "Grupo": None,
                    "Conta": str(info["lid"]), "NomeColuna": info["n"],
                    "DescricaoColuna": info["d"], "Saldo": number,
                })
        data = pd.DataFrame(rows)
        if data.empty or data.duplicated(["CodInst", "Conta", "NomeColuna"]).any():
            raise ValueError("Relatório IF.data vazio ou com contas duplicadas")
        return data


@lru_cache(maxsize=1)
def get_web_source(periodo: str):
    root = Path(os.getenv("TOMACONTA_IFDATA_WEB_DIR") or
                Path(__file__).resolve().parents[2] / "data/cache/bcb_ifdata_web")
    return IFDataWeb(periodo, root)
