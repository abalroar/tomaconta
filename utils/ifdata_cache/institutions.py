"""Catálogo canônico de instituições sem dependência de alias local."""

from __future__ import annotations

import csv
import copy
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import requests

from utils.ifdata_extractor import parece_codigo_instituicao, resolver_nome_instituicao


CONGLOMERADOS_API_URL = "https://www3.bcb.gov.br/informes/rest/conglomerados"
PLACEHOLDER_IF_PATTERN = re.compile(r"^\[IF\s+([A-Za-z0-9]+)\]$", re.IGNORECASE)

_GENERIC_TOKENS = {
    "A",
    "ANONIMA",
    "BANCO",
    "BANK",
    "BCO",
    "BM",
    "CONGLOMERADO",
    "D",
    "DA",
    "DAS",
    "DE",
    "DO",
    "DOS",
    "FINANCEIRA",
    "GRUPO",
    "HOLDING",
    "INSTITUICAO",
    "MULTIPLO",
    "OF",
    "PAGAMENTO",
    "PRUDENCIAL",
    "S",
    "SA",
    "SOCIEDADE",
}


def normalize_institution_name(nome: str | None) -> str:
    """Normaliza nome oficial para chave estável de matching."""
    if nome is None:
        return ""

    texto = str(nome).strip().upper()
    texto = "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caractere) != "Mn"
    )
    texto = re.sub(r"[^A-Z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _significant_institution_tokens(nome: str | None) -> Tuple[str, ...]:
    """Retorna tokens significativos para canonicalização nominal auditável."""
    texto = normalize_institution_name(nome)
    if not texto:
        return ()

    texto = re.sub(r"\bBCO\b", "BANCO", texto)
    texto = re.sub(r"\bS A\b", "SA", texto)
    tokens = [token for token in texto.split() if token and token not in _GENERIC_TOKENS]
    return tuple(tokens)


def _project_root(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return base_dir.resolve()
    return Path(__file__).resolve().parents[2]


def _parse_conglomerados_csv_text(texto: str) -> List[dict]:
    blocos = re.split(r"(?=Conglomerado)", texto, flags=re.IGNORECASE)
    resultados: List[dict] = []
    for bloco in blocos:
        bloco_limpo = " ".join(bloco.split())
        if not bloco_limpo:
            continue

        cod_match = re.search(r"CDIGO\D*(\d{4,8})", bloco_limpo, flags=re.IGNORECASE)
        nome_match = re.search(r"NOME\s*(.*?)\s*TIPO", bloco_limpo, flags=re.IGNORECASE)
        if not cod_match:
            continue

        codigo = int(cod_match.group(1))
        nome = nome_match.group(1).strip(" -") if nome_match else "SEM NOME"
        participacoes = []

        for part in re.finditer(
            r"CNPJ\D*([0-9]{8,14})\s*(.*?)\s*(LIDER|PARTICIPANTE)",
            bloco_limpo,
            flags=re.IGNORECASE,
        ):
            cnpj = part.group(1).zfill(14)
            nome_inst = re.sub(r"\s+", " ", part.group(2)).strip(" -")
            condicao = normalize_institution_name(part.group(3))
            participacoes.append({"cnpj": cnpj, "nome": nome_inst, "condicao": condicao})

        resultados.append({"codigo": codigo, "nome": nome, "participacoes": participacoes})
    return resultados


def _load_conglomerados_local_csv(base_dir: Path) -> List[dict]:
    caminho = base_dir / "conglomerados.csv"
    if not caminho.exists():
        return []
    texto = caminho.read_text(encoding="utf-8", errors="ignore")
    return _parse_conglomerados_csv_text(texto)


def _load_conglomerados_api() -> List[dict]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0",
    }
    for metodo in ("GET", "POST"):
        try:
            resposta = requests.request(metodo, CONGLOMERADOS_API_URL, timeout=40, headers=headers)
            if resposta.status_code in {400, 405}:
                continue
            resposta.raise_for_status()
            payload = json.loads(resposta.text)
            dados_api = payload.get("content", []) if isinstance(payload, dict) else payload
            if isinstance(dados_api, list) and dados_api:
                return dados_api
        except Exception:
            continue
    return []


def _load_conglomerados_bloprudencial_fallback(base_dir: Path) -> List[dict]:
    candidatos = sorted(base_dir.glob("*BLOPRUDENCIAL*.CSV"), reverse=True)
    if not candidatos:
        return []

    conglomerados: Dict[str, dict] = {}
    for caminho in candidatos:
        try:
            with caminho.open("r", encoding="latin1", errors="ignore", newline="") as fp:
                leitor = csv.reader(fp, delimiter=";")
                for partes in leitor:
                    if len(partes) < 7:
                        continue
                    linha = ";".join(partes)
                    if not linha or linha.startswith("Balancete") or linha.startswith("Data de geracao") or linha.startswith("Fonte:"):
                        continue
                    if linha.startswith("#"):
                        continue

                    cnpj = re.sub(r"\D", "", partes[2]).zfill(14)
                    nome_inst = partes[4].strip()
                    cod_congl = partes[5].strip()
                    nome_congl = partes[6].strip()
                    if not cod_congl or not nome_congl:
                        continue

                    codigo = re.sub(r"\D", "", cod_congl)
                    if not codigo:
                        continue

                    item = conglomerados.setdefault(
                        codigo,
                        {
                            "codigo": int(codigo),
                            "nome": nome_congl,
                            "participacoes": [],
                        },
                    )
                    if cnpj and nome_inst:
                        registro = {"cnpj": cnpj, "nome": nome_inst, "condicao": "PARTICIPANTE"}
                        if registro not in item["participacoes"]:
                            item["participacoes"].append(registro)
        except Exception:
            continue

    resultado = sorted(conglomerados.values(), key=lambda x: x.get("codigo", 0))
    for item in resultado:
        if item.get("participacoes"):
            item["participacoes"][0]["condicao"] = "LIDER"
    return resultado


def load_conglomerados_catalog(base_dir: Path | None = None) -> List[dict]:
    """Carrega catálogo oficial de conglomerados."""
    root = _project_root(base_dir)
    return copy.deepcopy(_load_conglomerados_catalog_cached(str(root)))


@lru_cache(maxsize=8)
def _load_conglomerados_catalog_cached(root_str: str) -> List[dict]:
    root = Path(root_str)
    dados = _load_conglomerados_local_csv(root)
    if dados:
        return dados

    dados = _load_conglomerados_bloprudencial_fallback(root)
    if dados:
        return dados

    return _load_conglomerados_api()


def build_institution_to_conglomerate_map(base_dir: Path | None = None) -> Dict[str, str]:
    """Mapa nome normalizado -> nome canônico do conglomerado."""
    root = _project_root(base_dir)
    return dict(_build_institution_to_conglomerate_map_cached(str(root)))


@lru_cache(maxsize=8)
def _build_institution_to_conglomerate_map_cached(root_str: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in _load_conglomerados_catalog_cached(root_str):
        nome_conglomerado = str(item.get("nome", "")).strip()
        if not nome_conglomerado:
            continue
        chave_congl = normalize_institution_name(nome_conglomerado)
        if chave_congl:
            mapping[chave_congl] = nome_conglomerado

        for participacao in item.get("participacoes", []) or []:
            nome_participante = str(participacao.get("nome", "")).strip()
            chave_participante = normalize_institution_name(nome_participante)
            if chave_participante and chave_participante not in mapping:
                mapping[chave_participante] = nome_conglomerado
    return mapping


def canonicalize_institution_name(
    nome: str | None,
    catalog_map: Dict[str, str] | None = None,
    base_dir: Path | None = None,
) -> str:
    """Resolve um nome de instituição para o nome oficial do conglomerado."""
    if nome is None:
        return ""

    bruto = str(nome).strip()
    if not bruto:
        return ""

    catalog = catalog_map if catalog_map is not None else build_institution_to_conglomerate_map(base_dir)
    chave = normalize_institution_name(bruto)
    resolved = catalog.get(chave)
    if resolved:
        return resolved

    tokens_brutos = _significant_institution_tokens(bruto)
    if tokens_brutos:
        tokens_set = set(tokens_brutos)
        candidatos_subconjunto = {
            nome_canonico
            for chave_catalogo, nome_canonico in catalog.items()
            if tokens_set.issubset(set(_significant_institution_tokens(chave_catalogo)))
        }
        if len(candidatos_subconjunto) == 1:
            return next(iter(candidatos_subconjunto))

    return bruto


def canonicalize_institution_series(
    nomes: Iterable[str],
    catalog_map: Dict[str, str] | None = None,
    base_dir: Path | None = None,
) -> List[str]:
    """Resolve uma sequência de nomes para nomes canônicos."""
    catalog = catalog_map if catalog_map is not None else build_institution_to_conglomerate_map(base_dir)
    return [canonicalize_institution_name(nome, catalog_map=catalog, base_dir=base_dir) for nome in nomes]


def is_placeholder_institution_name(nome: str | None) -> bool:
    texto = str(nome or "").strip()
    if not texto:
        return False
    return bool(PLACEHOLDER_IF_PATTERN.fullmatch(texto))


def normalize_institution_code(codinst: object) -> str:
    """Normaliza CodInst sem destruir prefixos usados pelo IFData."""
    if codinst is None or pd.isna(codinst):
        return ""
    if isinstance(codinst, str):
        return codinst.strip()
    texto = str(codinst).strip()
    if not texto:
        return ""
    try:
        numero = float(texto)
        if numero.is_integer():
            return str(int(numero))
    except (TypeError, ValueError):
        pass
    return texto


def _institution_period_sort_key(periodo: object) -> tuple[int, int, str]:
    texto = str(periodo or "").strip()
    if "/" in texto:
        parte, ano = (item.strip() for item in texto.split("/", 1))
        if parte.isdigit() and ano.isdigit():
            valor = int(parte)
            mes = valor * 3 if 1 <= valor <= 4 else valor
            return int(ano), mes, texto
    digitos = re.sub(r"\D", "", texto)
    if len(digitos) >= 6:
        return int(digitos[:4]), int(digitos[4:6]), texto
    return 0, 0, texto


def stabilize_institution_names_by_code(
    df: pd.DataFrame | None,
    *,
    code_column: str = "CodInst",
    name_column: str = "Instituição",
    period_column: str = "Período",
) -> pd.DataFrame:
    """Aplica o nome oficial válido mais recente a todo o histórico do CodInst.

    O cadastro do IFData é temporal e pode mudar o nome de uma instituição. Os
    relatórios analíticos precisam manter essa informação como rótulo, mas nunca
    como identidade; por isso a escolha é feita por código e período.
    """
    if df is None or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if code_column not in df.columns or name_column not in df.columns:
        return df.copy()

    out = df.copy()
    out[code_column] = out[code_column].map(normalize_institution_code)
    nomes = out[name_column].astype(str).str.strip()
    validos = ~nomes.map(is_placeholder_institution_name) & ~nomes.map(parece_codigo_instituicao)
    candidatos = out.loc[validos, [code_column, name_column]].copy()
    candidatos = candidatos[candidatos[code_column].astype(bool)]
    if candidatos.empty:
        return out

    if period_column in out.columns:
        candidatos["_period_sort"] = out.loc[candidatos.index, period_column].map(_institution_period_sort_key)
        candidatos = candidatos.sort_values("_period_sort", kind="stable")

    mapa = (
        candidatos.drop_duplicates(subset=[code_column], keep="last")
        .set_index(code_column)[name_column]
        .astype(str)
        .str.strip()
        .to_dict()
    )
    nomes_estaveis = out[code_column].map(mapa)
    out[name_column] = nomes_estaveis.where(nomes_estaveis.notna(), nomes)
    return out


def build_code_to_name_map(
    *frames: pd.DataFrame | None,
    code_columns: Iterable[str] = ("CodInst", "COD_INST", "cod_inst", "CODINST"),
    name_columns: Iterable[str] = ("Instituição", "NomeInstituicao", "NomeInstituição", "NOME_INSTITUICAO"),
) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    code_cols = list(code_columns)
    name_cols = list(name_columns)

    for frame in frames:
        if frame is None or frame.empty:
            continue
        code_col = next((col for col in code_cols if col in frame.columns), None)
        name_col = next((col for col in name_cols if col in frame.columns), None)
        if not code_col or not name_col:
            continue
        base = frame[[code_col, name_col]].dropna(subset=[code_col]).copy()
        if base.empty:
            continue
        for _, row in base.iterrows():
            code_val = row.get(code_col)
            name_val = str(row.get(name_col) or "").strip()
            if not name_val:
                continue
            if is_placeholder_institution_name(name_val) or parece_codigo_instituicao(name_val):
                continue
            code_key = normalize_institution_code(code_val)
            if code_key and code_key not in mapping:
                mapping[code_key] = name_val
    return mapping


def canonicalize_institution_dataframe(
    df: pd.DataFrame | None,
    *,
    catalog_map: Dict[str, str] | None = None,
    base_dir: Path | None = None,
    name_column: str = "Instituição",
    extra_frames: Iterable[pd.DataFrame | None] = (),
) -> pd.DataFrame:
    if df is None or df.empty or name_column not in df.columns:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    catalog = catalog_map if catalog_map is not None else build_institution_to_conglomerate_map(base_dir)
    out = df.copy()
    code_to_name = build_code_to_name_map(out, *list(extra_frames))
    code_columns = [col for col in ("CodInst", "COD_INST", "cod_inst", "CODINST") if col in out.columns]

    def _resolve_name(row: pd.Series) -> str:
        raw_name = str(row.get(name_column) or "").strip()
        code_key = ""
        for code_col in code_columns:
            code_val = row.get(code_col)
            if pd.isna(code_val):
                continue
            code_key = normalize_institution_code(code_val)
            if code_key:
                break

        nome_base = raw_name
        if (is_placeholder_institution_name(raw_name) or parece_codigo_instituicao(raw_name)) and code_key:
            nome_base = code_to_name.get(code_key) or resolver_nome_instituicao(code_key, raw_name)

        return canonicalize_institution_name(nome_base, catalog_map=catalog, base_dir=base_dir)

    out[name_column] = out.apply(_resolve_name, axis=1)
    return out


def canonicalize_institution_history(
    df: pd.DataFrame | None,
    *,
    catalog_map: Dict[str, str] | None = None,
    base_dir: Path | None = None,
    name_column: str = "Instituição",
    code_column: str = "CodInst",
    period_column: str = "Período",
    raw_name_column: str = "InstituiçãoRaw",
) -> pd.DataFrame:
    """Unifica rótulos históricos sem usar o nome textual como identidade.

    O IFData pode publicar a mesma instituição com nomes diferentes ao longo do
    tempo e, em períodos antigos, sem ``CodInst``. A rotina combina as duas
    evidências disponíveis: estabiliza nomes por código em um frame auxiliar e
    resolve as variantes nominais pelo catálogo oficial. O nome recebido da
    fonte é preservado para auditoria em ``raw_name_column``.

    A canonicalização é feita apenas para nomes únicos, evitando o custo de uma
    resolução linha a linha. Se duas variantes passarem a ocupar a mesma chave
    instituição/período, a linha já canônica e mais completa é escolhida de
    forma determinística; o número de colisões fica registrado em ``DataFrame.attrs``.
    """
    if df is None or df.empty or name_column not in df.columns:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    out = df.copy()
    if period_column not in out.columns:
        period_column = next(
            (candidate for candidate in ("Período", "Periodo") if candidate in out.columns),
            period_column,
        )
    source_order = pd.Series(range(len(out)), index=out.index, dtype="int64")
    raw_names = out[name_column].fillna("").astype(str).str.strip()
    if raw_name_column not in out.columns:
        out[raw_name_column] = raw_names

    names_for_resolution = raw_names
    if code_column in out.columns:
        auxiliary_columns = [code_column, name_column]
        if period_column in out.columns:
            auxiliary_columns.append(period_column)
        stabilized = stabilize_institution_names_by_code(
            out[auxiliary_columns],
            code_column=code_column,
            name_column=name_column,
            period_column=period_column,
        )
        names_for_resolution = stabilized[name_column].fillna("").astype(str).str.strip()

    catalog = catalog_map if catalog_map is not None else build_institution_to_conglomerate_map(base_dir)
    unique_names = [name for name in names_for_resolution.unique().tolist() if name]
    canonical_by_name = {
        name: canonicalize_institution_name(name, catalog_map=catalog, base_dir=base_dir)
        for name in unique_names
    }
    canonical_names = names_for_resolution.map(canonical_by_name).fillna(names_for_resolution).astype(str).str.strip()
    out[name_column] = canonical_names.where(canonical_names.astype(bool), raw_names)

    out.attrs["institution_identity_collision_count"] = 0
    out.attrs["institution_identity_collision_keys"] = []
    if period_column not in out.columns:
        return out

    period_values = out[period_column].fillna("").astype(str).str.strip()
    valid_keys = out[name_column].astype(str).str.strip().astype(bool) & period_values.astype(bool)
    duplicate_mask = valid_keys & out.duplicated(subset=[name_column, period_column], keep=False)
    if not duplicate_mask.any():
        return out

    duplicate_rows = out.loc[duplicate_mask].copy()
    value_columns = [
        column
        for column in out.columns
        if column not in {name_column, period_column, raw_name_column}
    ]
    if value_columns:
        conflicting_groups = (
            duplicate_rows.groupby([name_column, period_column], dropna=False)[value_columns]
            .nunique(dropna=True)
            .gt(1)
            .any(axis=1)
        )
        conflict_keys = [tuple(key) for key in conflicting_groups[conflicting_groups].index.tolist()]
    else:
        conflict_keys = []

    duplicate_rows["_identity_source_order"] = source_order.loc[duplicate_rows.index]
    duplicate_rows["_identity_canonical_exact"] = (
        duplicate_rows[raw_name_column].map(normalize_institution_name)
        == duplicate_rows[name_column].map(normalize_institution_name)
    )
    duplicate_rows["_identity_non_null_score"] = duplicate_rows[value_columns].notna().sum(axis=1)
    preferred_rows = (
        duplicate_rows.sort_values(
            [
                name_column,
                period_column,
                "_identity_canonical_exact",
                "_identity_non_null_score",
                "_identity_source_order",
            ],
            ascending=[True, True, False, False, True],
            kind="stable",
        )
        .drop_duplicates(subset=[name_column, period_column], keep="first")
    )

    untouched_rows = out.loc[~duplicate_mask].copy()
    untouched_rows["_identity_source_order"] = source_order.loc[untouched_rows.index]
    out = (
        pd.concat([untouched_rows, preferred_rows], ignore_index=True, sort=False)
        .sort_values("_identity_source_order", kind="stable")
        .drop(
            columns=[
                "_identity_source_order",
                "_identity_canonical_exact",
                "_identity_non_null_score",
            ],
            errors="ignore",
        )
        .reset_index(drop=True)
    )
    out.attrs["institution_identity_collision_count"] = int(
        duplicate_rows.groupby([name_column, period_column], dropna=False).ngroups
    )
    out.attrs["institution_identity_collision_keys"] = conflict_keys
    return out
