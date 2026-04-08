from __future__ import annotations

import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests


BCB_INFORMES_BASE_URL = "https://www3.bcb.gov.br/informes/rest"
PESSOAS_JURIDICAS_URL = f"{BCB_INFORMES_BASE_URL}/pessoasJuridicas"
BALANCO_DOWNLOAD_URL = f"{BCB_INFORMES_BASE_URL}/balanco//download"

CDSFN_BLOCKS = {
    "BalancoPatrimonial": {"sigla": "BP", "label": "Balanço Patrimonial"},
    "DemonstracaoDoResultado": {"sigla": "DRE", "label": "Demonstração do Resultado"},
    "DemonstracaoDoResultadoAbrangente": {"sigla": "DRA", "label": "Demonstração do Resultado Abrangente"},
    "DemonstracaoDosFluxosDeCaixa": {"sigla": "DFC", "label": "Demonstração dos Fluxos de Caixa"},
    "DemonstracaoDasMutacoesDoPatrimonioLiquido": {"sigla": "DMPL", "label": "Demonstração das Mutações do Patrimônio Líquido"},
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TomaConta/1.0; +https://github.com/matheusjprates/tomaconta)",
    "Referer": "https://www3.bcb.gov.br/informes/",
}

REQUIRED_TOP_LEVEL_KEYS = ("@cnpj", "@codigoDocumento", "@dataBase")
REQUIRED_ACCOUNT_KEYS = ("@nivel", "@descricao", "@contaPai")
CSV_REQUIRED_COLUMNS = ("CNPJ", "NOME DA INSTITUICAO")


def _safe_response_json(response: Any, contexto: str) -> dict[str, Any]:
    try:
        return response.json()
    except Exception as exc:
        try:
            return json.loads(response.text)
        except Exception as json_exc:
            raise ValueError(f"{contexto}: resposta não é JSON válido.") from json_exc


def _digits_only(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_text(value: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    texto = texto.strip().upper()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def _normalize_instituicoes(rows: list[dict[str, Any]]) -> pd.DataFrame:
    normalized: list[dict[str, Any]] = []
    vistos: set[tuple[str, str, str]] = set()

    for item in rows:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nome") or "").strip()
        cnpj = _digits_only(item.get("cnpj"))
        id_bacen = str(item.get("idBacen") or "").strip()
        if not nome and not cnpj:
            continue
        chave = (nome, cnpj, id_bacen)
        if chave in vistos:
            continue
        vistos.add(chave)
        label = nome or cnpj
        if nome and cnpj:
            label = f"{nome} ({cnpj})"
        normalized.append(
            {
                "nome": nome,
                "cnpj": cnpj,
                "id_bacen": id_bacen,
                "label": label,
                "raw": item,
            }
        )

    if not normalized:
        raise ValueError("API de instituições retornou lista vazia ou sem campos utilizáveis (nome/cnpj).")

    return pd.DataFrame(normalized).sort_values(["nome", "cnpj", "id_bacen"], na_position="last").reset_index(drop=True)


def load_instituicoes_csv_cdsfn(path: str | Path) -> pd.DataFrame:
    caminho = Path(path)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de instituições não encontrado: {caminho}")

    df = pd.read_csv(caminho, sep=";", encoding="latin1", skiprows=7, dtype=str)
    if len(df.columns) and str(df.columns[-1]).startswith("Unnamed"):
        df = df.iloc[:, :-1]

    faltantes = [col for col in CSV_REQUIRED_COLUMNS if col not in df.columns]
    if faltantes:
        raise ValueError(f"CSV de instituições sem colunas obrigatórias: {', '.join(faltantes)}.")

    for col in df.columns:
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["cnpj"] = df["CNPJ"].map(_digits_only).str.zfill(8)
    df["nome"] = df["NOME DA INSTITUICAO"].astype(str).str.strip()
    df["municipio"] = df.get("MUNICIPIO", "").astype(str).str.strip() if "MUNICIPIO" in df.columns else ""
    df["uf"] = df.get("UF", "").astype(str).str.strip() if "UF" in df.columns else ""
    df["situacao"] = df.get("SITUAÇÃO", "").astype(str).str.strip() if "SITUAÇÃO" in df.columns else ""

    df = df[(df["cnpj"].str.len() == 8) & (df["nome"] != "")]
    if df.empty:
        raise ValueError("CSV de instituições não contém linhas válidas com CNPJ raiz e nome.")

    df = df.drop_duplicates(subset=["cnpj", "nome"], keep="first").copy()
    df["label"] = df.apply(
        lambda row: f"{row['nome']} ({row['cnpj']})" if row["cnpj"] else row["nome"],
        axis=1,
    )
    return df.sort_values(["nome", "cnpj"], na_position="last").reset_index(drop=True)


def _normalize_reference_dates(payload: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, str]]:
    datas_raw = payload.get("datasBaseReferencia") or []
    if datas_raw and not isinstance(datas_raw, list):
        raise ValueError("Campo 'datasBaseReferencia' inválido: esperado lista.")

    datas: list[dict[str, str]] = []
    mapping: dict[str, str] = {}
    for idx, item in enumerate(datas_raw):
        if not isinstance(item, dict):
            raise ValueError(f"datasBaseReferencia[{idx}] inválido: esperado objeto.")
        dt_id = str(item.get("@id") or "").strip()
        dt_data = str(item.get("@data") or "").strip()
        if not dt_id:
            raise ValueError(f"datasBaseReferencia[{idx}] sem '@id'.")
        datas.append({"id": dt_id, "data": dt_data})
        mapping[dt_id] = dt_data or dt_id
    return datas, mapping


def _level_sort_key(nivel: Any) -> tuple[int, ...]:
    texto = str(nivel or "").strip()
    if not texto:
        return (10**9,)
    partes = []
    for parte in texto.split("."):
        try:
            partes.append(int(parte))
        except ValueError:
            partes.append(10**6)
    return tuple(partes)


def _reference_sort_key(ref: str) -> tuple[int, int, str]:
    texto = str(ref or "").strip().upper()
    match = re.search(r"([A-Z])?(\d{2})(\d{4})$", texto)
    if not match:
        return (0, 0, texto)
    prefixo, mes, ano = match.groups()
    return (int(ano), int(mes), prefixo or "")


def _reference_prefix(ref: str) -> str:
    texto = str(ref or "").strip().upper()
    if not texto:
        return ""
    if texto[0].isalpha():
        return texto[0]
    return ""


def _reference_display_label(ref: str) -> str:
    texto = str(ref or "").strip().upper()
    match = re.search(r"([A-Z])?(\d{2})(\d{4})$", texto)
    if not match:
        return texto
    prefixo, mes, ano = match.groups()
    mapa_mes = {
        "01": "jan",
        "02": "fev",
        "03": "mar",
        "04": "abr",
        "05": "mai",
        "06": "jun",
        "07": "jul",
        "08": "ago",
        "09": "set",
        "10": "out",
        "11": "nov",
        "12": "dez",
    }
    mes_txt = mapa_mes.get(mes, mes)
    if prefixo:
        return f"{prefixo} {mes_txt}/{ano[-2:]}"
    return f"{mes_txt}/{ano[-2:]}"


def _build_parent_map(df_long: pd.DataFrame) -> dict[str, str]:
    base = (
        df_long[["nivel", "conta_pai"]]
        .drop_duplicates()
        .fillna("")
    )
    return {str(row["nivel"]).strip(): str(row["conta_pai"]).strip() for _, row in base.iterrows()}


def _build_description_map(df_long: pd.DataFrame) -> dict[str, str]:
    base = (
        df_long[["nivel", "descricao"]]
        .drop_duplicates()
        .fillna("")
    )
    return {str(row["nivel"]).strip(): str(row["descricao"]).strip() for _, row in base.iterrows()}


def _ancestor_chain(nivel: str, parent_map: dict[str, str]) -> list[str]:
    chain = [nivel]
    current = parent_map.get(nivel, "")
    seen = {nivel}
    while current and current not in seen:
        chain.append(current)
        seen.add(current)
        current = parent_map.get(current, "")
    return chain


def _compute_depth(nivel: str, parent_map: dict[str, str]) -> int:
    cadeia = _ancestor_chain(nivel, parent_map)
    chain_depth = max(0, len(cadeia) - 1)
    dot_depth = max(0, len(str(nivel or "").split(".")) - 1)
    return max(chain_depth, dot_depth)


def _resolve_balance_section(nivel: str, parent_map: dict[str, str], desc_map: dict[str, str]) -> str:
    texts = [_normalize_text(desc_map.get(item, "")) for item in _ancestor_chain(nivel, parent_map)]
    if any("PATRIMON" in texto for texto in texts):
        return "Patrimônio líquido"
    if any("PASSIVO" in texto for texto in texts):
        return "Passivo"
    if any("ATIVO" in texto for texto in texts):
        return "Ativo"
    return "Outras contas"


def list_reference_periods_cdsfn(payload: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = extract_metadata_cdsfn(payload)
    refs = []
    vistos: set[str] = set()
    for item in metadata.get("datas_base_referencia", []):
        raw = str(item.get("data") or item.get("id") or "").strip()
        if not raw or raw in vistos:
            continue
        vistos.add(raw)
        refs.append(
            {
                "id": str(item.get("id") or "").strip(),
                "raw": raw,
                "prefixo": _reference_prefix(raw),
                "label": _reference_display_label(raw),
                "sort_key": _reference_sort_key(raw),
            }
        )
    refs = sorted(refs, key=lambda item: item["sort_key"], reverse=True)
    return refs


def build_hierarchy_frame_cdsfn(df_long: pd.DataFrame, block_key: str) -> tuple[pd.DataFrame, list[str]]:
    if df_long.empty:
        return pd.DataFrame(), []

    base_cols = ["demonstracao", "nivel", "descricao", "conta_pai", "conta_id", "ordem_conta"]
    df_wide = pivot_wide_cdsfn(df_long)
    value_columns = [col for col in df_wide.columns if col not in base_cols]

    meta = df_long[base_cols].drop_duplicates().copy()
    parent_map = _build_parent_map(df_long)
    desc_map = _build_description_map(df_long)
    child_levels = {parent for parent in parent_map.values() if parent}

    meta["depth"] = meta["nivel"].astype(str).map(lambda nivel: _compute_depth(nivel, parent_map))
    meta["has_children"] = meta["nivel"].astype(str).isin(child_levels)
    meta["section"] = (
        meta["nivel"].astype(str).map(lambda nivel: _resolve_balance_section(nivel, parent_map, desc_map))
        if block_key == "BalancoPatrimonial"
        else "Demonstração"
    )
    meta["_sort_key"] = meta["nivel"].astype(str).map(_level_sort_key)

    merged = meta.merge(df_wide, on=base_cols, how="left")
    merged = merged.sort_values(["ordem_conta", "_sort_key", "descricao"], na_position="last").reset_index(drop=True)
    merged = merged.drop(columns=["_sort_key"])
    return merged, value_columns


def build_display_table_cdsfn(
    df_long: pd.DataFrame,
    block_key: str,
    periodos_referencia: list[str],
    *,
    column_labels: dict[str, str] | None = None,
) -> pd.DataFrame:
    df_view, value_columns = build_hierarchy_frame_cdsfn(df_long, block_key)
    if df_view.empty:
        return pd.DataFrame()

    periodos_validos = [p for p in periodos_referencia]
    for periodo in periodos_validos:
        if periodo not in df_view.columns:
            df_view[periodo] = pd.NA
    colunas = ["descricao", "nivel", "depth", "has_children"] + periodos_validos
    df_export = df_view[colunas].copy()

    def _label_conta(row) -> str:
        depth = int(row.get("depth", 0) or 0)
        descricao = str(row.get("descricao") or "")
        return f"{'   ' * depth}{descricao}"

    df_export.insert(0, "Conta", df_export.apply(_label_conta, axis=1))
    df_export = df_export.drop(columns=["descricao", "nivel", "depth", "has_children"])
    if column_labels:
        df_export = df_export.rename(columns=column_labels)
    return df_export


def fetch_instituicoes_cdsfn(
    page_size: int = 500,
    *,
    timeout: int = 60,
    session: Any | None = None,
) -> pd.DataFrame:
    if page_size <= 0:
        raise ValueError("page_size deve ser positivo.")

    client = session or requests
    rows: list[dict[str, Any]] = []

    def _fetch_page(page: int) -> dict[str, Any]:
        payload = {
            "segmento": None,
            "nome": "",
            "cnpj": "",
            "pais": "",
            "estado": None,
            "municipio": None,
            "incluirAgencias": False,
            "incluirInstituicoesLiquidacao": False,
            "numeroPagina": page,
            "tamanhoPagina": page_size,
        }
        response = client.post(
            PESSOAS_JURIDICAS_URL,
            json=payload,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()
        return _safe_response_json(response, f"consulta de instituições CDSFN página {page}")

    primeira_pagina = _fetch_page(0)
    content = primeira_pagina.get("content")
    if not isinstance(content, list):
        raise ValueError("Resposta da API de instituições sem campo 'content' em formato lista.")
    rows.extend(content)

    total_pages = primeira_pagina.get("totalPages")
    if not isinstance(total_pages, int):
        last = primeira_pagina.get("last")
        if isinstance(last, bool) and last:
            return _normalize_instituicoes(rows)
        raise ValueError("Resposta da API de instituições sem paginação válida ('totalPages' ausente).")

    if total_pages <= 1:
        return _normalize_instituicoes(rows)

    max_workers = min(8, total_pages - 1)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for body in executor.map(_fetch_page, range(1, total_pages)):
            page_content = body.get("content")
            if not isinstance(page_content, list):
                raise ValueError("Resposta de paginação da API sem campo 'content' em formato lista.")
            rows.extend(page_content)

    return _normalize_instituicoes(rows)


def fetch_documento_cdsfn(
    cnpj: str,
    ano_mes: str,
    codigo_documento: str = "9011",
    *,
    timeout: int = 60,
    session: Any | None = None,
) -> tuple[dict[str, Any], str]:
    cnpj_norm = _digits_only(cnpj)
    ano_mes_norm = re.sub(r"\D", "", str(ano_mes or ""))
    codigo_norm = re.sub(r"\D", "", str(codigo_documento or ""))

    if not cnpj_norm:
        raise ValueError("CNPJ inválido para consulta do documento CDSFN.")
    if not re.fullmatch(r"\d{6}", ano_mes_norm):
        raise ValueError("anoMes inválido. Use o formato YYYYMM.")
    if not codigo_norm:
        raise ValueError("codigo_documento inválido.")

    url = f"{BALANCO_DOWNLOAD_URL}/{ano_mes_norm}-{codigo_norm}-{cnpj_norm}.json"
    client = session or requests
    response = client.get(
        url,
        params={"cnpj": cnpj_norm, "anoMes": ano_mes_norm},
        headers=DEFAULT_HEADERS,
        timeout=timeout,
    )
    if response.status_code == 404:
        raise FileNotFoundError(f"Documento {codigo_norm} não encontrado para CNPJ {cnpj_norm} em {ano_mes_norm}.")
    response.raise_for_status()
    payload = _safe_response_json(response, "download do documento CDSFN")
    return payload, getattr(response, "url", url)


def validate_json_cdsfn(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Documento CDSFN inválido: raiz não é objeto JSON.")

    faltantes = [campo for campo in REQUIRED_TOP_LEVEL_KEYS if campo not in payload]
    if faltantes:
        raise ValueError(f"Documento CDSFN inválido: metadados ausentes: {', '.join(faltantes)}.")

    _normalize_reference_dates(payload)

    blocos_presentes = [chave for chave in CDSFN_BLOCKS if chave in payload]
    if not blocos_presentes:
        raise ValueError("Documento CDSFN inválido: nenhum bloco financeiro reconhecido encontrado.")

    for bloco in blocos_presentes:
        body = payload.get(bloco)
        if not isinstance(body, dict):
            raise ValueError(f"Bloco '{bloco}' inválido: esperado objeto.")
        contas = body.get("contas")
        if not isinstance(contas, list):
            raise ValueError(f"Bloco '{bloco}' inválido: campo 'contas' ausente ou não é lista.")
        for idx, conta in enumerate(contas):
            if not isinstance(conta, dict):
                raise ValueError(f"Bloco '{bloco}' inválido: conta #{idx} não é objeto.")
            faltantes_conta = [campo for campo in REQUIRED_ACCOUNT_KEYS if campo not in conta]
            if faltantes_conta:
                raise ValueError(
                    f"Bloco '{bloco}' inválido: conta #{idx} sem campos obrigatórios: {', '.join(faltantes_conta)}."
                )
            valores = conta.get("valoresIndividualizados")
            if valores is None:
                continue
            if not isinstance(valores, list):
                raise ValueError(f"Bloco '{bloco}' inválido: 'valoresIndividualizados' da conta #{idx} não é lista.")
            for jdx, valor in enumerate(valores):
                if not isinstance(valor, dict):
                    raise ValueError(f"Bloco '{bloco}' inválido: valor #{jdx} da conta #{idx} não é objeto.")
                if "@dtBase" not in valor or "@valor" not in valor:
                    raise ValueError(
                        f"Bloco '{bloco}' inválido: valor #{jdx} da conta #{idx} sem '@dtBase' e/ou '@valor'."
                    )


def extract_metadata_cdsfn(payload: dict[str, Any]) -> dict[str, Any]:
    validate_json_cdsfn(payload)
    datas, mapping = _normalize_reference_dates(payload)
    return {
        "cnpj": str(payload.get("@cnpj") or "").strip(),
        "codigo_documento": str(payload.get("@codigoDocumento") or "").strip(),
        "tipo_remessa": str(payload.get("@tipoRemessa") or "").strip(),
        "unidade_medida": str(payload.get("@unidadeMedida") or "").strip(),
        "data_base": str(payload.get("@dataBase") or "").strip(),
        "datas_base_referencia": datas,
        "datas_base_map": mapping,
    }


def list_blocks_cdsfn(payload: dict[str, Any]) -> list[dict[str, Any]]:
    validate_json_cdsfn(payload)
    blocks: list[dict[str, Any]] = []
    for block_key, meta in CDSFN_BLOCKS.items():
        if block_key not in payload:
            continue
        contas = payload.get(block_key, {}).get("contas") or []
        blocks.append(
            {
                "block_key": block_key,
                "sigla": meta["sigla"],
                "label": meta["label"],
                "contas": len(contas),
            }
        )
    return blocks


def normalize_long_cdsfn(payload: dict[str, Any], block_key: str) -> pd.DataFrame:
    validate_json_cdsfn(payload)
    if block_key not in payload:
        raise KeyError(f"Bloco '{block_key}' não existe no documento consultado.")

    metadata = extract_metadata_cdsfn(payload)
    block_meta = CDSFN_BLOCKS.get(block_key, {"sigla": block_key, "label": block_key})
    contas = payload.get(block_key, {}).get("contas") or []

    rows: list[dict[str, Any]] = []
    for idx, conta in enumerate(contas):
        conta_id = str(conta.get("@id") or "").strip()
        nivel = str(conta.get("@nivel") or "").strip()
        descricao = str(conta.get("@descricao") or "").strip()
        conta_pai = str(conta.get("@contaPai") or "").strip()
        valores = conta.get("valoresIndividualizados")

        if not isinstance(valores, list) or not valores:
            rows.append(
                {
                    "cnpj": metadata["cnpj"],
                    "codigo_documento": metadata["codigo_documento"],
                    "demonstracao": block_meta["sigla"],
                    "bloco_origem": block_key,
                    "conta_id": conta_id,
                    "nivel": nivel,
                    "descricao": descricao,
                    "conta_pai": conta_pai,
                    "ordem_conta": idx,
                    "dt_base": None,
                    "dt_base_referencia": None,
                    "valor": pd.NA,
                    "unidade_medida": metadata["unidade_medida"],
                }
            )
            continue

        for valor_item in valores:
            dt_base = str(valor_item.get("@dtBase") or "").strip() or None
            rows.append(
                {
                    "cnpj": metadata["cnpj"],
                    "codigo_documento": metadata["codigo_documento"],
                    "demonstracao": block_meta["sigla"],
                    "bloco_origem": block_key,
                    "conta_id": conta_id,
                    "nivel": nivel,
                    "descricao": descricao,
                    "conta_pai": conta_pai,
                    "ordem_conta": idx,
                    "dt_base": dt_base,
                    "dt_base_referencia": metadata["datas_base_map"].get(dt_base, dt_base),
                    "valor": pd.to_numeric(valor_item.get("@valor"), errors="coerce"),
                    "unidade_medida": metadata["unidade_medida"],
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(
        by=["ordem_conta", "nivel", "descricao", "dt_base_referencia", "dt_base"],
        key=lambda s: s.map(_level_sort_key) if s.name == "nivel" else s,
        na_position="last",
    ).reset_index(drop=True)


def pivot_wide_cdsfn(df_long: pd.DataFrame) -> pd.DataFrame:
    if df_long.empty:
        return pd.DataFrame(
            columns=[
                "demonstracao",
                "nivel",
                "descricao",
                "conta_pai",
                "conta_id",
                "ordem_conta",
            ]
        )

    base_cols = ["demonstracao", "nivel", "descricao", "conta_pai", "conta_id", "ordem_conta"]
    dt_label_col = "dt_base_referencia"
    df_work = df_long.copy()
    df_work[dt_label_col] = df_work[dt_label_col].fillna(df_work["dt_base"]).fillna("sem_data")
    pivot = (
        df_work
        .pivot_table(
            index=base_cols,
            columns=dt_label_col,
            values="valor",
            aggfunc="first",
            observed=False,
        )
        .reset_index()
    )
    pivot.columns.name = None
    return pivot.sort_values(
        by=["ordem_conta", "nivel", "descricao"],
        key=lambda s: s.map(_level_sort_key) if s.name == "nivel" else s,
        na_position="last",
    ).reset_index(drop=True)


def build_excel_display_export_cdsfn(
    metadata: dict[str, Any],
    df_display: pd.DataFrame,
    *,
    sheet_name: str = "Tabela",
) -> bytes:
    output = BytesIO()
    metadata_rows = [
        {"campo": "cnpj", "valor": metadata.get("cnpj")},
        {"campo": "codigo_documento", "valor": metadata.get("codigo_documento")},
        {"campo": "tipo_remessa", "valor": metadata.get("tipo_remessa")},
        {"campo": "unidade_medida", "valor": metadata.get("unidade_medida")},
        {"campo": "data_base", "valor": metadata.get("data_base")},
    ]

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame(metadata_rows).to_excel(writer, sheet_name="Metadata", index=False)
        df_display.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()


def build_excel_export_cdsfn(
    metadata: dict[str, Any],
    df_long: pd.DataFrame,
    df_wide: pd.DataFrame,
) -> bytes:
    output = BytesIO()
    metadata_rows = [
        {"campo": "cnpj", "valor": metadata.get("cnpj")},
        {"campo": "codigo_documento", "valor": metadata.get("codigo_documento")},
        {"campo": "tipo_remessa", "valor": metadata.get("tipo_remessa")},
        {"campo": "unidade_medida", "valor": metadata.get("unidade_medida")},
        {"campo": "data_base", "valor": metadata.get("data_base")},
    ]
    for item in metadata.get("datas_base_referencia", []):
        metadata_rows.append({"campo": f"dt_ref_{item.get('id')}", "valor": item.get("data")})

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame(metadata_rows).to_excel(writer, sheet_name="Metadata", index=False)
        df_long.to_excel(writer, sheet_name="Long", index=False)
        df_wide.to_excel(writer, sheet_name="Wide", index=False)
    return output.getvalue()
