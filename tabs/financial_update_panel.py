"""Atualização da análise financeira por botões: verificar, revisar e aplicar."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pandas as pd
import streamlit as st

from utils.prudential_analysis import dre_row_labels

ACCEPT = "Aceitar na linha indicada"
MAX_INDIVIDUAL_DECISIONS = 30
KIND_LABELS = {"nova": "Conta nova", "sumiu": "Conta que sumiu", "renomeada": "Nome alterado", "salto": "Salto na linha"}
STATUS = {
    "validated": ("info", "Verificação concluída. Nada foi alterado na base."),
    "needs_review": ("warning", "Há contas a revisar. Nada foi alterado na base."),
    "updated": ("success", "Base atualizada."),
    "unchanged": ("info", "O arquivo do BCB é igual ao que já está carregado."),
    "failed": ("error", "A atualização parou e a base anterior foi preservada."),
}


def _reports_dir(root: Path) -> Path:
    path = Path(root) / "data/cache/financial_analysis_updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_state(root: Path) -> dict:
    """Estado do processo; um processo encerrado à força não fica como "em andamento"."""
    try:
        job = json.loads((_reports_dir(root) / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if job.get("running"):
        try:
            os.kill(int(job["pid"]), 0)
        except (OSError, ValueError, KeyError):
            job.update(running=False, interrupted=True)
    return job


def latest_report(root: Path) -> tuple[dict, Path] | tuple[None, None]:
    # Relatórios têm a data no nome; job.json e decisions.json são arquivos de controle.
    files = sorted(_reports_dir(root).glob("[0-9]*T*.json"), key=lambda path: path.name)
    if not files:
        return None, None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8")), files[-1]
    except ValueError:
        return None, None


def start_job(root: Path, *, check_only: bool, period=None, csv=None, decisions=None, publish=False, token=None) -> None:
    """Roda em processo próprio: a sessão pode fechar sem interromper a atualização."""
    directory = _reports_dir(root)
    job_file = directory / "job.json"
    command = [sys.executable, str(Path(root) / "tools/update_financial_analysis.py"), "--root", str(root), "--job-file", str(job_file)]
    if check_only:
        command.append("--check-only")
    if period:
        command += ["--data-base", f"{period[:4]}-{period[4:]}"]
    if csv:
        command += ["--csv", str(csv)]
    if decisions:
        answers = directory / "decisions.json"
        answers.write_text(json.dumps(decisions, ensure_ascii=False), encoding="utf-8")
        command += ["--decisions", str(answers)]
    environment = dict(os.environ)
    if publish and token:
        command.append("--publish")
        environment["GITHUB_PAT"] = token
    log = (directory / "job.log").open("ab")
    process = subprocess.Popen(command, cwd=root, env=environment, stdout=log, stderr=log, start_new_session=True)
    job_file.write_text(json.dumps({"pid": process.pid, "stage": "Iniciando", "running": True}), encoding="utf-8")


def store_upload(root: Path, upload) -> Path:
    """Aceita o .zip da página do BCB ou o .csv já extraído."""
    directory = _reports_dir(root) / "uploads"
    directory.mkdir(exist_ok=True)
    name = Path(upload.name).name
    path = directory / name
    path.write_bytes(upload.getvalue())
    if not name.lower().endswith(".zip"):
        return path
    with zipfile.ZipFile(path) as archive:
        members = [member for member in archive.namelist() if member.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("O arquivo .zip deve conter exatamente um .csv")
        target = directory / Path(members[0]).name
        target.write_bytes(archive.read(members[0]))
    return target


def _money(value) -> str:
    return f"R$ {abs(float(value)) / 1e9:,.2f} bi".replace(",", "X").replace(".", ",").replace("X", ".")


def _review_table(items) -> pd.DataFrame:
    return pd.DataFrame([{
        "Tipo": KIND_LABELS[item["kind"]], "Documento": item["document"], "Conta": item.get("account") or "–",
        "Nome no BCB": item["name"], "Valor no sistema": _money(item["total_brl"]) + (f" (antes {_money(item['previous_brl'])})" if item.get("previous_brl") is not None else ""),
        "Instituições": item.get("institutions") or "–", "Linha indicada": item.get("row_label") or "–",
    } for item in items])


def _options(item) -> list[str]:
    """Só conta de resultado pode ir para outra linha da DRE."""
    return [ACCEPT, *dre_row_labels().values()] if item.get("account") and item.get("result_account") else [ACCEPT]


def _review_form(report) -> dict | None:
    """Devolve as respostas somente quando todos os itens que suspendem foram respondidos."""
    pending = set(report.get("pending_review") or ())
    items = [item for item in report["validation"]["review"] if item["id"] in pending]
    if not items:
        return {}
    st.warning(f"{len(items)} item(ns) precisam de decisão. A linha indicada segue a regra por prefixo; altere só se a conta pertencer a outra linha.")
    st.dataframe(_review_table(items), hide_index=True, width="stretch")
    accept_all = st.checkbox("Aceitar todos na linha indicada", key="financial_update_accept_all")
    if len(items) > MAX_INDIVIDUAL_DECISIONS and not accept_all:
        st.caption(f"Com mais de {MAX_INDIVIDUAL_DECISIONS} itens, a decisão é em bloco. Confira o relatório completo antes de aceitar.")
        return None
    labels = {label: ident for ident, label in dre_row_labels().items()}
    answers = {}
    for item in items if not accept_all else ():
        answer = st.selectbox(f"{KIND_LABELS[item['kind']]}: {item.get('account') or item['name']} ({item.get('row_label') or 'fora da DRE'})",
                              _options(item), index=None, placeholder="Escolha uma decisão", key=f"financial_update_{report['run_id']}_{item['id']}")
        if answer is None:
            st.caption("Responda todos os itens para liberar a aplicação.")
            return None
        answers[item["id"]] = {"row": labels.get(answer)}
    return {item["id"]: {"row": None} for item in items} if accept_all else answers


def _render_report(root, report, path, token) -> None:
    kind, message = STATUS.get(report.get("status"), ("info", str(report.get("status"))))
    getattr(st, kind)(message + (f" {report['error']}" if report.get("error") else ""))
    validation = report.get("validation") or {}
    columns = st.columns(4)
    columns[0].metric("Última data no BCB", report.get("period") or "–")
    columns[1].metric("Data carregada antes", report.get("previous_max_period") or "–")
    columns[2].metric("Conferências", f"{validation.get('checks', 0):,}".replace(",", "."))
    columns[3].metric("Instituições", validation.get("institutions", "–"))
    errors, warnings = validation.get("errors") or [], validation.get("warnings") or []
    if errors:
        st.dataframe(pd.DataFrame(errors).astype(str), hide_index=True, width="stretch")
    if report.get("changed"):
        st.caption("Bases com alteração: " + ", ".join(report["changed"]) + ".")
    publication = report.get("publication") or {}
    if publication.get("status") == "published":
        st.success(f"Publicado em {publication['repo']}@{publication['tag']}. O site passa a ler esta versão.")
    elif publication.get("status") == "failed":
        st.error(f"A base local foi atualizada, mas a publicação falhou: {publication['error']}. Sem publicação, a atualização se perde no reinício do servidor.")
    review = validation.get("review") or []
    if report.get("status") in {"validated", "needs_review"}:
        answers = _review_form(report)
        if report.get("changed") and answers is not None:
            publish = st.checkbox("Publicar ao concluir", value=bool(token), disabled=not token, key="financial_update_publish",
                                  help=None if token else "Configure GITHUB_PAT nos Secrets para publicar.")
            if not publish:
                st.caption("Sem publicar, a atualização fica só neste servidor e se perde no próximo reinício.")
            if st.button("Aplicar atualização", type="primary", key="financial_update_apply"):
                start_job(root, check_only=False, period=report["period"], csv=report.get("csv"), decisions=answers, publish=publish, token=token)
                st.rerun()
        elif not report.get("changed"):
            st.caption("Não há nada a aplicar.")
    notices = [item for item in review if not item["blocking"]]
    if notices or warnings:
        with st.expander(f"Avisos que não impedem a atualização ({len(notices) + len(warnings)})"):
            if notices:
                st.dataframe(_review_table(notices), hide_index=True, width="stretch")
            if warnings:
                st.dataframe(pd.DataFrame([{"Instituição": item.get("code"), "Conferência": item.get("check"), "Competência": item.get("period") or item.get("previous_period") or "–"} for item in warnings]), hide_index=True, width="stretch")
    st.download_button("Baixar relatório completo", data=path.read_bytes(), file_name=path.name, mime="application/json", key="financial_update_report")


def render(root: Path, token: str | None = None) -> None:
    root = Path(root)
    st.markdown("### Análise financeira")
    st.caption("Baixa a última publicação de Balancetes do BCB e o IF.data, confere contas e totais e só então atualiza Balanço, DRE e bases dependentes.")

    @st.fragment(run_every=3)
    def progress():
        job = job_state(root)
        if job.get("running"):
            st.info(f"Em andamento: {job.get('stage')}. Você pode fechar esta página.")
        elif st.session_state.get("financial_update_waiting"):
            st.session_state["financial_update_waiting"] = False
            st.rerun()

    job = job_state(root)
    if job.get("running"):
        st.session_state["financial_update_waiting"] = True
        progress()
        return
    if job.get("interrupted"):
        st.warning("A última execução foi interrompida antes de terminar. A base anterior foi preservada; execute novamente.")
    upload = st.file_uploader("Usar arquivo baixado do BCB (opcional)", type=["zip", "csv"], key="financial_update_upload",
                              help="Só é necessário se o download automático falhar.")
    if st.button("Verificar BCB", type="primary", key="financial_update_check"):
        try:
            csv = store_upload(root, upload) if upload else None
        except (ValueError, zipfile.BadZipFile) as exc:
            st.error(f"Arquivo inválido: {exc}")
        else:
            start_job(root, check_only=True, csv=csv)
            st.rerun()
    report, path = latest_report(root)
    if report:
        _render_report(root, report, path, token)
