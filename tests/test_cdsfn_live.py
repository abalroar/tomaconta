from __future__ import annotations

from io import BytesIO

import pandas as pd

from utils.cdsfn_live import (
    build_display_table_cdsfn,
    build_excel_display_export_cdsfn,
    build_hierarchy_frame_cdsfn,
    build_excel_export_cdsfn,
    extract_metadata_cdsfn,
    fetch_documento_cdsfn,
    fetch_instituicoes_cdsfn,
    list_blocks_cdsfn,
    list_reference_periods_cdsfn,
    load_instituicoes_csv_cdsfn,
    normalize_long_cdsfn,
    pivot_wide_cdsfn,
    validate_json_cdsfn,
)


def _sample_payload() -> dict:
    return {
        "@cnpj": "05503849",
        "@codigoDocumento": "9011",
        "@tipoRemessa": "I",
        "@unidadeMedida": "1000",
        "@dataBase": "122025",
        "datasBaseReferencia": [
            {"@id": "dt1", "@data": "A122025"},
            {"@id": "dt2", "@data": "S122025"},
        ],
        "BalancoPatrimonial": {
            "contas": [
                {
                    "@id": "conta1",
                    "@nivel": "1",
                    "@descricao": "Ativo",
                    "@contaPai": "",
                    "valoresIndividualizados": [{"@dtBase": "dt1", "@valor": 656719.0}],
                },
                {
                    "@id": "conta2",
                    "@nivel": "1.1",
                    "@descricao": "Disponibilidades",
                    "@contaPai": "1",
                    "valoresIndividualizados": [{"@dtBase": "dt1", "@valor": 100.0}],
                },
                {
                    "@id": "conta3",
                    "@nivel": "2",
                    "@descricao": "Passivo",
                    "@contaPai": "",
                    "valoresIndividualizados": [{"@dtBase": "dt1", "@valor": 1000.0}],
                },
                {
                    "@id": "conta4",
                    "@nivel": "2.1",
                    "@descricao": "Patrimônio líquido",
                    "@contaPai": "2",
                    "valoresIndividualizados": [{"@dtBase": "dt1", "@valor": 500.0}],
                },
            ]
        },
        "DemonstracaoDoResultado": {
            "contas": [
                {
                    "@id": "conta-header",
                    "@nivel": "1",
                    "@descricao": "Outros resultados abrangentes",
                    "@contaPai": "",
                },
                {
                    "@id": "conta3",
                    "@nivel": "1.1.1",
                    "@descricao": "Receita com operações de crédito",
                    "@contaPai": "1.1",
                    "valoresIndividualizados": [
                        {"@dtBase": "dt2", "@valor": 211791.0},
                        {"@dtBase": "dt1", "@valor": 217098.0},
                    ],
                }
            ]
        },
    }


class _DummyResponse:
    def __init__(self, body, status_code: int = 200, url: str = ""):
        self._body = body
        self.status_code = status_code
        self.url = url
        self.text = body if isinstance(body, str) else ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _DummyClient:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        pagina = json["numeroPagina"]
        if pagina == 0:
            return _DummyResponse(
                {
                    "content": [
                        {"nome": "Banco A", "cnpj": "12345678", "idBacen": "1"},
                        {"nome": "Banco B", "cnpj": "87654321", "idBacen": "2"},
                    ],
                    "number": 0,
                    "totalPages": 2,
                    "last": False,
                }
            )
        return _DummyResponse(
            {
                "content": [{"nome": "Banco C", "cnpj": "11112222", "idBacen": "3"}],
                "number": 1,
                "totalPages": 2,
                "last": True,
            }
        )

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return _DummyResponse(_sample_payload(), url="https://example.com/final")


def test_validate_and_extract_metadata_cdsfn():
    payload = _sample_payload()
    validate_json_cdsfn(payload)
    metadata = extract_metadata_cdsfn(payload)
    assert metadata["cnpj"] == "05503849"
    assert metadata["codigo_documento"] == "9011"
    assert metadata["datas_base_map"]["dt1"] == "A122025"


def test_list_blocks_and_normalize_long_cdsfn():
    payload = _sample_payload()
    blocks = list_blocks_cdsfn(payload)
    assert [item["sigla"] for item in blocks] == ["BP", "DRE"]

    df_long = normalize_long_cdsfn(payload, "DemonstracaoDoResultado")
    assert list(df_long.columns) == [
        "cnpj",
        "codigo_documento",
        "demonstracao",
        "bloco_origem",
        "conta_id",
        "nivel",
        "descricao",
        "conta_pai",
        "ordem_conta",
        "dt_base",
        "dt_base_referencia",
        "valor",
        "unidade_medida",
    ]
    assert len(df_long) == 3
    assert set(df_long["dt_base_referencia"].dropna()) == {"A122025", "S122025"}
    assert df_long[df_long["conta_id"] == "conta-header"]["valor"].isna().all()


def test_pivot_wide_cdsfn_preserves_dates_as_columns():
    df_long = normalize_long_cdsfn(_sample_payload(), "DemonstracaoDoResultado")
    df_wide = pivot_wide_cdsfn(df_long)
    assert "A122025" in df_wide.columns
    assert "S122025" in df_wide.columns
    assert df_wide.iloc[0]["nivel"] == "1.1.1"


def test_fetch_instituicoes_cdsfn_iterates_pages_until_last():
    client = _DummyClient()
    df = fetch_instituicoes_cdsfn(page_size=500, session=client)
    assert len(client.posts) == 2
    assert list(df["nome"]) == ["Banco A", "Banco B", "Banco C"]
    assert client.posts[0]["json"]["incluirAgencias"] is False
    assert client.posts[0]["json"]["tamanhoPagina"] == 500


def test_fetch_documento_cdsfn_builds_expected_url_and_params():
    client = _DummyClient()
    payload, final_url = fetch_documento_cdsfn("05503849", "202512", session=client)
    assert payload["@codigoDocumento"] == "9011"
    assert final_url == "https://example.com/final"
    assert client.gets[0]["url"].endswith("/202512-9011-05503849.json")
    assert client.gets[0]["params"] == {"cnpj": "05503849", "anoMes": "202512"}


def test_build_excel_export_cdsfn_returns_bytes():
    payload = _sample_payload()
    metadata = extract_metadata_cdsfn(payload)
    df_long = normalize_long_cdsfn(payload, "BalancoPatrimonial")
    df_wide = pivot_wide_cdsfn(df_long)
    excel_bytes = build_excel_export_cdsfn(metadata, df_long, df_wide)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 100


def test_load_instituicoes_csv_cdsfn_parses_bootstrap_file(tmp_path):
    csv_path = tmp_path / "instituicoes.csv"
    csv_path.write_text(
        "\n".join(
            [
                "SEGMENTO;-;",
                "NOME DA INSTITUICAO;-;",
                "CNPJ;-;",
                "PAIS;Todos;",
                "UF;-;",
                "MUNICIPIO;-;",
                ";",
                "CNPJ;NOME DA INSTITUICAO;MUNICIPIO;UF;SITUAÇÃO;",
                '5503849;"CLOUDWALK FINANCEIRA S.A."; "SAO PAULO";"SP";"Autorizada em Atividade";',
                '60394079;"BANCO ITAUBANK S.A.";"SAO PAULO";"SP";"Autorizada em Atividade";',
            ]
        ),
        encoding="latin1",
    )
    df = load_instituicoes_csv_cdsfn(csv_path)
    assert list(df["cnpj"]) == ["60394079", "05503849"]
    assert "label" in df.columns


def test_build_hierarchy_frame_cdsfn_splits_balance_sections():
    df_long = normalize_long_cdsfn(_sample_payload(), "BalancoPatrimonial")
    df_view, value_cols = build_hierarchy_frame_cdsfn(df_long, "BalancoPatrimonial")
    assert "A122025" in value_cols
    assert set(df_view["section"]) >= {"Ativo", "Passivo", "Patrimônio líquido"}
    ativo_row = df_view[df_view["descricao"] == "Ativo"].iloc[0]
    assert int(ativo_row["depth"]) == 0


def test_list_reference_periods_cdsfn_returns_sorted_unique_refs():
    refs = list_reference_periods_cdsfn(_sample_payload())
    assert [item["raw"] for item in refs] == ["S122025", "A122025"]
    assert refs[0]["label"] == "S dez/25"


def test_build_display_table_cdsfn_uses_selected_columns_only():
    df_long = normalize_long_cdsfn(_sample_payload(), "DemonstracaoDoResultado")
    df_display = build_display_table_cdsfn(
        df_long,
        "DemonstracaoDoResultado",
        ["S122025"],
        column_labels={"S122025": "S dez/25"},
    )
    assert list(df_display.columns) == ["Conta", "S dez/25"]
    assert "Receita com operações de crédito" in df_display["Conta"].iloc[-1]


def test_build_excel_display_export_cdsfn_returns_bytes():
    payload = _sample_payload()
    metadata = extract_metadata_cdsfn(payload)
    df_long = normalize_long_cdsfn(payload, "BalancoPatrimonial")
    df_display = build_display_table_cdsfn(df_long, "BalancoPatrimonial", ["A122025"])
    excel_bytes = build_excel_display_export_cdsfn(metadata, df_display, sheet_name="BP")
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 100
