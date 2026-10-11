"""Controles opt-in para o serviço externo, mantendo a seleção atual do app."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from .update_app_bridge import build_external_spec


def render_external_update_controls(st, bridge, cache_type, label, periods, mode, options):
    st.markdown("#### 4. Executar extração")
    st.caption("A atualização será executada pelo servidor. Você pode fechar esta página e acompanhar o resultado depois.")
    publish = st.checkbox("publicar automaticamente a versão validada ao concluir", value=True,
                          key="publicar_auto_portatil")
    try:
        status = bridge.current_status(cache_type)
    except Exception as exc:
        st.error(f"Não foi possível consultar o serviço de atualização: {exc}")
        return
    if status:
        if status["running"]:
            st.info(status["current"])
            st.progress(min(max(float(status["progress"]), 0), 1))
        elif status["status"] == "succeeded":
            st.success("Atualização concluída.")
        elif status["status"] in {"partial", "failed"}:
            st.error(status["current"])
            if st.button("retomar extração", width="stretch", key="retomar_portatil"):
                try:
                    bridge.retry(status["job_id"])
                    st.rerun()
                except Exception as exc:
                    st.error(f"Não foi possível retomar: {exc}")
        else:
            st.info(status["current"])
        st.caption(f"Última atualização registrada: {status['last_update']}")
        if status.get("publish_message"):
            st.caption(status["publish_message"])
        if st.button("Atualizar status", key="status_portatil", width="stretch"):
            st.rerun()
        if status["status"] == "succeeded":
            with st.expander("publicação manual", expanded=False):
                if st.button(f"Publicar pacote de '{cache_type}'", key="publicar_portatil", width="stretch"):
                    try:
                        bridge.publish(status["job_id"])
                        st.success("Versão validada publicada.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível publicar: {exc}")
    if st.button(f"Extrair dados de {label}", type="primary", width="stretch",
                 key="btn_extrair_portatil", disabled=bool(status.get("running"))):
        try:
            spec = build_external_spec(cache_type, periods, mode, options, publish=publish)
            fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
            key = "_portable_request_" + fingerprint
            # Um timeout pode ocorrer após o servidor aceitar o pedido. Repetir
            # a mesma intenção usa a mesma chave e recupera o job já criado.
            request_id = st.session_state.setdefault(key, uuid4().hex)
            job = bridge.submit(cache_type, periods, mode, options, publish=publish,
                                idempotency_key=request_id)
            st.session_state.pop(key, None)
            st.success(f"Atualização registrada: {job['job_id']}")
            st.rerun()
        except Exception as exc:
            st.error(f"Não foi possível registrar a atualização: {exc}")
