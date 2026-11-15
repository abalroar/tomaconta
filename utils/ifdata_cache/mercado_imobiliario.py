"""Olinda/MercadoImobiliario: meses retomáveis e promoção pelo BaseCache."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pandas as pd
import requests

from ..mercado_imobiliario import CATALOG_VERSION, CHARTS, FACT_COLUMNS, normalize_records, validate_frame
from .base import BaseCache, CacheConfig, CacheResult
from .release_config import add_release_cache_buster, build_release_asset_url, get_release_config
from .taxas_juros_historico import _build_odata_url, _escape_odata_literal, _request_json
from .update_state import locked_cache_update

BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/MercadoImobiliario/versao/v1/odata/mercadoimobiliario"
FIRST_MONTH = "2014-04"
CONFIG = CacheConfig(nome="mercado_imobiliario", descricao="Mercado Imobiliário — Olinda/BCB",
    subdir="mercado_imobiliario", arquivo_dados="dados.parquet", arquivo_metadata="metadata.json",
    max_idade_horas=24 * 35, colunas_obrigatorias=FACT_COLUMNS, api_url=BASE_URL)


class MercadoImobiliarioCache(BaseCache):
    def __init__(self, base_dir: Path, *, request_json=None):
        super().__init__(replace(CONFIG, github_url_base=get_release_config().release_base_url), base_dir)
        self._request = request_json or _request_json

    def _validar_dados(self, dados):
        ok, message = super()._validar_dados(dados)
        if not ok:
            return ok, message
        check = validate_frame(dados)
        return check["success"], check["message"]

    def latest_available(self) -> dict[str, str]:
        result = {}
        for block, prefix in (("credito", "credito_"), ("imoveis", "imoveis_")):
            payload = self._request(_build_odata_url(BASE_URL, {"$filter": f"startswith(Info,'{prefix}')",
                "$orderby": "Data desc", "$top": 1, "$format": "json"}))
            rows = payload.get("value")
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"Não foi possível confirmar a competência de {block}")
            result[block] = pd.Timestamp(rows[0]["Data"]).strftime("%Y-%m")
        return result

    def default_start(self) -> date:
        if self.existe_leitura():
            loaded = self.carregar_local()
            if loaded.sucesso and loaded.dados is not None:
                return (loaded.dados["data"].max().to_period("M") - 11).start_time.date()
        return pd.Period(FIRST_MONTH, freq="M").start_time.date()

    def fetch_month(self, period: str, *, page_size: int = 5000) -> tuple[pd.DataFrame, dict]:
        month = pd.Period(period, freq="M")
        base_filter = f"Data eq '{month.end_time:%Y-%m-%d}'"
        records, cursor, seen = [], "", set()
        for _ in range(1000):
            filter_ = base_filter + (f" and Info gt '{_escape_odata_literal(cursor)}'" if cursor else "")
            url = _build_odata_url(BASE_URL, {"$filter": filter_, "$orderby": "Info asc",
                "$top": page_size, "$select": "Data,Info,Valor", "$format": "json"})
            payload = self._request(url)
            rows = payload.get("value")
            if not isinstance(rows, list):
                raise ValueError("Resposta Olinda sem lista value")
            infos = [str(row.get("Info", "")) for row in rows]
            # A collation da fonte difere da ordem Unicode (ex.: sufixo NA).
            # O cursor usa a mesma ordenação da consulta, sem reordenar páginas.
            if (len(infos) != len(set(infos)) or any(info in seen for info in infos)
                    or any(row.get("Data") != f"{month.end_time:%Y-%m-%d}" for row in rows)):
                raise ValueError("Página fora da competência ou com chave repetida")
            seen.update(infos)
            records.extend(rows)
            if len(rows) < page_size:
                break
            cursor = infos[-1]
        else:
            raise ValueError("Limite de páginas atingido; mês não confirmado")
        frame = normalize_records(records)
        return frame, {"periodo": str(month), "registros_fonte": len(records), "registros_escopo": len(frame),
            "sha256_resposta": sha256(json.dumps(records, sort_keys=True).encode()).hexdigest(),
            "consulta": base_filter, "endpoint": BASE_URL}

    @locked_cache_update
    def materialize_history(self, *, start=None, end=None, overwrite=False, rebuild=False,
                            max_workers=3, progress_callback=None) -> CacheResult:
        """Checkpoint privado por mês; falha nunca promove dados parciais."""
        try:
            start_date = pd.Timestamp(start or (pd.Period(FIRST_MONTH, freq="M").start_time if rebuild else self.default_start()))
            end_date = pd.Timestamp(end or date.today())
            if start_date > end_date:
                raise ValueError("Data inicial posterior à final")
            available = self.latest_available()
            end_month = end_date.to_period("M")
            if end_date.date() < end_month.end_time.date():
                end_month -= 1
            final = min(end_month, max(pd.Period(p, freq="M") for p in available.values()))
            periods = list(pd.period_range(max(start_date.to_period("M"), pd.Period(FIRST_MONTH)), final, freq="M"))
            if not periods:
                raise ValueError("Janela solicitada sem competências publicadas")
            previous = pd.DataFrame(columns=FACT_COLUMNS)
            if self.existe_leitura():
                old = self.carregar_local()
                if not old.sucesso:
                    raise ValueError("Não foi possível preservar a base anterior: " + old.mensagem)
                previous = old.dados
            plan = {"start": str(periods[0]), "end": str(periods[-1]), "catalog": CATALOG_VERSION,
                    "base": (old.metadata or {}).get("integridade") if not previous.empty else None,
                    "overwrite": overwrite, "rebuild": rebuild}
            fingerprint = sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:20]
            stage = self.cache_dir / "staging" / fingerprint
            stage.mkdir(parents=True, exist_ok=True)
            frames, receipts, failures = {}, {}, []

            def collect(period):
                key = str(period)
                path, receipt = stage / f"{key}.parquet", stage / f"{key}.json"
                if path.exists() and receipt.exists():
                    info = json.loads(receipt.read_text())
                    if sha256(path.read_bytes()).hexdigest() == info.get("sha256_parquet"):
                        frame = pd.read_parquet(path)
                        check = validate_frame(frame)
                        if check["success"]:
                            return key, frame, info
                    # Somente o checkpoint privado é substituído pela nova consulta.
                frame, info = self.fetch_month(key)
                if frame.empty:
                    raise ValueError(f"Mês {key} sem séries reconhecidas")
                temp = path.with_suffix(".tmp")
                frame.to_parquet(temp, index=False)
                temp.replace(path)
                info["sha256_parquet"] = sha256(path.read_bytes()).hexdigest()
                self._write_json_atomic(receipt, info)
                return key, frame, info

            with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 4))) as pool:
                pending = {pool.submit(collect, period): str(period) for period in periods}
                for future in as_completed(pending):
                    key = pending[future]
                    try:
                        key, frame, info = future.result()
                        frames[key], receipts[key] = frame, info
                    except Exception as exc:
                        failures.append({"periodo": key, "erro": str(exc)})
                    if progress_callback:
                        progress_callback((len(frames) + len(failures)) / len(periods), f"{key}: {len(frames)}/{len(periods)} meses confirmados")
            if failures:
                return CacheResult(False, "Coleta incompleta; base anterior preservada", metadata={"falhas": failures,
                    "finalized": False, "periodos_pendentes": [item["periodo"] for item in failures]}, fonte="Olinda/BCB")
            fresh = pd.concat([frames[str(period)] for period in periods], ignore_index=True)
            # Substitui meses inteiros: elimina observações removidas/revisadas pela fonte.
            outside = previous[~previous["data"].dt.to_period("M").isin(periods)] if not previous.empty else previous
            combined = (pd.concat([outside, fresh], ignore_index=True) if not outside.empty else fresh).sort_values(["data", "info"]).reset_index(drop=True)
            coverage = {}
            national = combined[(combined["uf"] == "br") & (combined["linha"] == "")]
            for spec in CHARTS:
                part = national[national["grafico"] == spec.key]
                coverage[spec.key] = {"inicio": part["data"].min().strftime("%Y-%m") if not part.empty else None,
                                      "fim": part["data"].max().strftime("%Y-%m") if not part.empty else None,
                                      "historico": spec.historical}
            # Cobertura nacional dos blocos ativos, comparada à competência publicada.
            fresh_national = fresh[(fresh["uf"] == "br") & (fresh["linha"] == "")]
            for spec in (item for item in CHARTS if not item.historical):
                source_end = available["imoveis" if spec.section == "Imóveis" else "credito"]
                required = min(str(final), source_end)
                if required >= str(periods[0]) and required >= ("2018-01" if spec.section == "Imóveis" else "2016-03" if spec.key == "estoque_parcela_pf" else FIRST_MONTH):
                    received = fresh_national.loc[fresh_national["grafico"] == spec.key, "data"].max()
                    if pd.isna(received) or received.strftime("%Y-%m") != required:
                        raise ValueError(f"Cobertura incompleta em {spec.title} ({spec.section}): esperado {required}")
            all_periods = sorted(combined["data"].dt.strftime("%Y%m").unique().tolist())
            previous_receipts = ((old.metadata or {}).get("extra") or {}).get("consultas", []) if not previous.empty else []
            all_receipts = {item["periodo"]: item for item in previous_receipts if "periodo" in item}
            all_receipts.update(receipts)
            result = self.salvar_local(combined, fonte="Olinda/MercadoImobiliario/BCB",
                metadata_extra={"periodos": all_periods, "total_periodos": len(all_periods), "cobertura_graficos": coverage,
                    "competencias_fonte": available, "catalog_version": CATALOG_VERSION, "series": int(combined["info"].nunique())},
                info_extra={"finalized": True, "falhas": [], "inicio_solicitado": start_date.date().isoformat(),
                    "fim_solicitado": end_date.date().isoformat(), "consultas": [all_receipts[key] for key in sorted(all_receipts)],
                    "revisao_historica": "Incremental revisa 12 meses; revisões anteriores exigem reprocessamento da janela.",
                    "bndu": "Excluído do escopo"})
            if result.sucesso:
                result.mensagem = f"{len(combined)} observações; {len(periods)} meses confirmados"
            return result
        except Exception as exc:
            return CacheResult(False, f"Mercado Imobiliário: {exc}; base anterior preservada",
                               metadata={"finalized": False, "falhas": [str(exc)]}, fonte="Olinda/BCB")

    def extrair_periodo(self, periodo, **kwargs):
        try:
            frame, receipt = self.fetch_month(str(pd.Period(str(periodo), freq="M")))
            return CacheResult(not frame.empty, f"{len(frame)} observações", dados=frame, metadata=receipt, fonte="Olinda/BCB")
        except Exception as exc:
            return CacheResult(False, str(exc), fonte="Olinda/BCB")

    def baixar_remoto(self):
        """O app baixa somente o pacote publicado; a coleta Olinda é explícita."""
        try:
            headers = {"Cache-Control": "no-cache"}
            urls = [add_release_cache_buster(build_release_asset_url(f"mercado_imobiliario_{name}"), "mercado_imobiliario", name)
                    for name in ("dados.parquet", "metadata.json")]
            data_response = requests.get(urls[0], timeout=120, headers=headers)
            meta_response = requests.get(urls[1], timeout=30, headers=headers)
            data_response.raise_for_status(); meta_response.raise_for_status()
            frame, metadata = pd.read_parquet(BytesIO(data_response.content)), meta_response.json()
            if metadata.get("integridade", {}).get("sha256") not in (None, sha256(data_response.content).hexdigest()):
                raise ValueError("Hash do pacote remoto divergente")
            ok, message = self._validar_dados(frame)
            if not ok:
                raise ValueError(message)
            return CacheResult(True, f"{len(frame)} observações do pacote publicado", dados=frame, metadata=metadata, fonte="github_releases")
        except Exception as exc:
            return CacheResult(False, str(exc), fonte="github_releases")

    def carregar(self, forcar_remoto=False):
        if self._official_snapshot is not None:
            return super().carregar(forcar_remoto=forcar_remoto)
        if not forcar_remoto and self.existe_leitura():
            local = self.carregar_local()
            if local.sucesso:
                return local
        remote = self.baixar_remoto()
        if remote.sucesso:
            saved = self.salvar_local(remote.dados, fonte=remote.fonte, metadata_extra={
                **{key: value for key, value in remote.metadata.items() if key not in {"integridade", "formato", "colunas", "total_registros"}},
                "baseline_publication_id": self._publication_metadata().get("publication_id")})
            if saved.sucesso:
                return saved
        return self.carregar_local() if self.existe_leitura() else remote
