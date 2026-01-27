import requests
import pandas as pd
import numpy as np
import time

BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"
cache_lucros = {}

def _fetch_json(url: str, timeout: int, retries: int = 2, backoff: float = 1.5):
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt >= retries:
                raise
            time.sleep(backoff * (attempt + 1))
    return None

def normalizar_nome_coluna(valor: str) -> str:
    if not isinstance(valor, str):
        return valor
    return " ".join(valor.split())

def obter_coluna_nome_instituicao(df: pd.DataFrame) -> str | None:
    candidatos = {
        "NomeInstituicao",
        "NomeInstituição",
        "Nome Instituicao",
        "Nome Instituição",
        "Nome da Instituicao",
        "Nome da Instituição",
    }
    for coluna in df.columns:
        if coluna in candidatos:
            return coluna
        if normalizar_nome_coluna(str(coluna)) in candidatos:
            return coluna
    return None

def extrair_cadastro(ano_mes: str) -> pd.DataFrame:
    url = f"{BASE_URL}/IfDataCadastro(AnoMes={int(ano_mes)})?$format=json&$top=5000"
    try:
        data = _fetch_json(url, timeout=60)
    except requests.RequestException:
        return pd.DataFrame()
    return pd.DataFrame((data or {}).get("value", []))

def extrair_valores(ano_mes: str) -> pd.DataFrame:
    url = (
        f"{BASE_URL}/IfDataValores("
        f"AnoMes={int(ano_mes)},"
        f"TipoInstituicao=1,"
        f"Relatorio='1'"
        f")?$format=json&$top=200000"
    )
    try:
        data = _fetch_json(url, timeout=120)
    except requests.RequestException:
        return pd.DataFrame()
    return pd.DataFrame((data or {}).get("value", []))

def extrair_lucro_periodo(ano_mes: str) -> pd.DataFrame:
    if ano_mes in cache_lucros:
        return cache_lucros[ano_mes]
    
    url = (
        f"{BASE_URL}/IfDataValores("
        f"AnoMes={int(ano_mes)},"
        f"TipoInstituicao=1,"
        f"Relatorio='1'"
        f")?$format=json&$top=200000"
    )
    try:
        data = _fetch_json(url, timeout=120)
    except requests.RequestException:
        return pd.DataFrame()

    df = pd.DataFrame((data or {}).get("value", []))
    if df.empty:
        return pd.DataFrame()
    
    df_lucro = df[df["NomeColuna"] == "Lucro Líquido"].copy()
    df_lucro = df_lucro.groupby("CodInst")["Saldo"].sum().reset_index()
    df_lucro.columns = ["CodInst", "Lucro Líquido"]
    
    cache_lucros[ano_mes] = df_lucro
    return df_lucro

def calcular_lucro_semestral(ano_mes: str, df_pivot: pd.DataFrame) -> pd.DataFrame:
    ano = ano_mes[:4]
    mes = ano_mes[4:6]
    df_result = df_pivot.copy()
    
    if mes == "09":
        periodo_anterior = f"{ano}06"
        df_lucro_anterior = extrair_lucro_periodo(periodo_anterior)
        
        if not df_lucro_anterior.empty and "Lucro Líquido" in df_result.columns:
            df_result = df_result.merge(
                df_lucro_anterior, on="CodInst", how="left", suffixes=("", "_06")
            )
            df_result["Lucro Líquido"] = (
                df_result["Lucro Líquido"].fillna(0) +
                df_result["Lucro Líquido_06"].fillna(0)
            )
            df_result = df_result.drop(columns=["Lucro Líquido_06"], errors="ignore")
    
    elif mes == "12":
        periodo_anterior = f"{ano}09"
        df_lucro_anterior = extrair_lucro_periodo(periodo_anterior)
        
        if not df_lucro_anterior.empty and "Lucro Líquido" in df_result.columns:
            df_result = df_result.merge(
                df_lucro_anterior, on="CodInst", how="left", suffixes=("", "_09")
            )
            df_result["Lucro Líquido"] = (
                df_result["Lucro Líquido"].fillna(0) +
                df_result["Lucro Líquido_09"].fillna(0)
            )
            df_result = df_result.drop(columns=["Lucro Líquido_09"], errors="ignore")
    
    return df_result

def aplicar_aliases(df: pd.DataFrame, dict_aliases: dict) -> pd.DataFrame:
    df = df.copy()
    df['Instituição'] = df['Instituição'].apply(lambda x: dict_aliases.get(x, x) if pd.notna(x) else x)
    return df

def processar_periodo(ano_mes: str, dict_aliases: dict) -> pd.DataFrame:
    df_cad = extrair_cadastro(ano_mes)
    df_valores = extrair_valores(ano_mes)
    if df_valores.empty:
        return None
    if "NomeColuna" in df_valores.columns:
        df_valores["NomeColuna"] = df_valores["NomeColuna"].map(normalizar_nome_coluna)

    nome_col_valores = obter_coluna_nome_instituicao(df_valores)
    if nome_col_valores:
        df_nomes = df_valores[["CodInst", nome_col_valores]].drop_duplicates().rename(
            columns={nome_col_valores: "NomeInstituicao"}
        )
    else:
        df_nomes = pd.DataFrame()

    if df_cad.empty:
        if not df_nomes.empty:
            df_cad = df_nomes.copy()
        else:
            df_cad = df_valores[["CodInst"]].drop_duplicates().copy()
            df_cad["NomeInstituicao"] = df_cad["CodInst"]
    elif not df_nomes.empty and "NomeInstituicao" in df_cad.columns:
        df_cad = df_cad.merge(
            df_nomes,
            on="CodInst",
            how="left",
            suffixes=("", "_valores")
        )
        df_cad["NomeInstituicao"] = df_cad["NomeInstituicao"].fillna(
            df_cad["NomeInstituicao_valores"]
        )
        df_cad = df_cad.drop(columns=["NomeInstituicao_valores"], errors="ignore")
    
    colunas_desejadas = [
        "Ativo Total",
        "Carteira de Crédito",
        "Carteira de Crédito Classificada",
        "Títulos e Valores Mobiliários",
        "Passivo Exigível",
        "Captações",
        "Patrimônio Líquido",
        "Lucro Líquido",
        "Patrimônio de Referência",
        "Patrimônio de Referência para Comparação com o RWA (e)",
        "Índice de Basileia",
        "Índice de Imobilização",
        "Número de Agências",
        "Número de Postos de Atendimento",
    ]
    
    df_filt = df_valores[df_valores["NomeColuna"].isin(colunas_desejadas)].copy()
    
    if df_filt.empty:
        return None
    
    df_pivot = df_filt.pivot_table(
        index="CodInst",
        columns="NomeColuna",
        values="Saldo",
        aggfunc="sum",
    ).reset_index()
    df_pivot.columns.name = None
    
    if "Carteira de Crédito Classificada" in df_pivot.columns:
        if "Carteira de Crédito" in df_pivot.columns:
            df_pivot["Carteira de Crédito"] = (
                df_pivot["Carteira de Crédito"].fillna(0) +
                df_pivot["Carteira de Crédito Classificada"].fillna(0)
            )
        else:
            df_pivot["Carteira de Crédito"] = df_pivot["Carteira de Crédito Classificada"]
        
        df_pivot = df_pivot.drop(columns=["Carteira de Crédito Classificada"], errors="ignore")
    
    df_pivot = calcular_lucro_semestral(ano_mes, df_pivot)
    
    df_merged = df_pivot.merge(
        df_cad[["CodInst", "NomeInstituicao"]],
        on="CodInst",
        how="left",
    )
    
    colunas_ordem = [
        "NomeInstituicao",
        "Ativo Total",
        "Carteira de Crédito",
        "Títulos e Valores Mobiliários",
        "Passivo Exigível",
        "Captações",
        "Patrimônio Líquido",
        "Lucro Líquido",
        "Patrimônio de Referência",
        "Patrimônio de Referência para Comparação com o RWA (e)",
        "Índice de Basileia",
        "Índice de Imobilização",
        "Número de Agências",
        "Número de Postos de Atendimento",
    ]
    colunas_finais = [c for c in colunas_ordem if c in df_merged.columns]
    df_out = df_merged[colunas_finais].copy()
    
    num_cols = [c for c in colunas_finais if c != "NomeInstituicao"]
    df_out = df_out.dropna(subset=num_cols, how="all")
    
    mes = int(ano_mes[4:6])
    
    if "Lucro Líquido" in df_out.columns and "Patrimônio Líquido" in df_out.columns:
        if mes == 3:
            fator = 4
        elif mes == 6:
            fator = 2
        elif mes == 9:
            fator = 12 / 9
        elif mes == 12:
            fator = 1
        else:
            fator = 12 / mes
        
        df_out["ROE An. (%)"] = (
            (fator * df_out["Lucro Líquido"].fillna(0)) /
            df_out["Patrimônio Líquido"].replace(0, np.nan)
        )
    
    if "Carteira de Crédito" in df_out.columns and "Patrimônio Líquido" in df_out.columns:
        df_out["Crédito/PL"] = (
            df_out["Carteira de Crédito"].fillna(0) /
            df_out["Patrimônio Líquido"].replace(0, np.nan)
        )
    
    if "Carteira de Crédito" in df_out.columns and "Captações" in df_out.columns:
        df_out["Crédito/Captações (%)"] = (
            df_out["Carteira de Crédito"].fillna(0) /
            df_out["Captações"].replace(0, np.nan)
        )
    
    if "Carteira de Crédito" in df_out.columns and "Ativo Total" in df_out.columns:
        df_out["Carteira/Ativo (%)"] = (
            df_out["Carteira de Crédito"].fillna(0) /
            df_out["Ativo Total"].replace(0, np.nan)
        )
    
    df_out = df_out.rename(columns={"NomeInstituicao": "Instituição"})
    df_out = aplicar_aliases(df_out, dict_aliases)
    df_out["Período"] = f"{ano_mes[4:6]}/{ano_mes[:4]}"
    
    if "Carteira de Crédito" in df_out.columns:
        df_out = df_out.sort_values("Carteira de Crédito", ascending=False, na_position="last")
    
    return df_out

def gerar_periodos(ano_inicial, mes_inicial, ano_final, mes_final):
    PERIODOS = []
    ano_atual = ano_inicial
    mes_atual = mes_inicial
    
    while True:
        periodo = f"{ano_atual}{mes_atual}"
        PERIODOS.append(periodo)
        
        if ano_atual == ano_final and mes_atual == mes_final:
            break
        
        if mes_atual == '03':
            mes_atual = '06'
        elif mes_atual == '06':
            mes_atual = '09'
        elif mes_atual == '09':
            mes_atual = '12'
        elif mes_atual == '12':
            mes_atual = '03'
            ano_atual += 1
    
    return PERIODOS

def processar_todos_periodos(periodos, dict_aliases, progress_callback=None):
    dados_periodos = {}
    
    for i, per in enumerate(periodos):
        if progress_callback:
            progress_callback(i, len(periodos), per)
        
        try:
            df_per = processar_periodo(per, dict_aliases)
            if df_per is not None and not df_per.empty:
                dados_periodos[per] = df_per
            time.sleep(1.5)
        except Exception as e:
            print(f"Erro no período {per}: {e}")
    
    return dados_periodos

def carregar_cores_aliases(df_aliases):
    dict_cores_personalizadas = {}
    
    mapa_cores = {
        'Azul-marinho': '#003366',
        'Laranja': '#FF6600',
        'Amarelo ouro': '#FFD700',
        'Vinho': '#8B0000',
        'Verde': '#28A745',
        'Roxo-vivo': '#820AD1',
        'Laranja 2': '#FF8C00',
        'Verde mais claro': '#03A64A',
        'Ciano': '#00B0FF',
        'Laranja 3': '#FF7F50',
        'Ciano 2': '#00CED1',
        'Amarelo ouro 2': '#FFB500',
        'Verde whatsapp': '#25D366',
        'Marrom': '#8B4513',
        'Azul royal': '#4169E1',
        'Cinza escuro': '#404040',
        'Azul petróleo': '#006699',
        'Vermelho': '#DC143C',
        'Preto': '#000000',
        'Rosa': '#FF1493',
        'Azul Citi': '#003DA5',
        'Laranja escuro': '#FF4500',
        'Verde oliva': '#556B2F',
        'Azul Porto': '#0066CC',
        'Azul escuro': '#000080'
    }
    
    for idx, row in df_aliases.iterrows():
        banco = row['Alias Banco']
        
        if pd.notna(row.get('Código Cor')):
            dict_cores_personalizadas[banco] = row['Código Cor']
        elif pd.notna(row.get('Cor')):
            cor_nome = row['Cor']
            if cor_nome in mapa_cores:
                dict_cores_personalizadas[banco] = mapa_cores[cor_nome]
            else:
                dict_cores_personalizadas[banco] = cor_nome
    
    return dict_cores_personalizadas
