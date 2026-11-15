"""Cache Streamlit com chave de revisão para renders oficiais concorrentes."""
from __future__ import annotations

from functools import wraps
import inspect
from typing import Any, Callable

import streamlit as st

from .official_store import get_official_read_snapshot


def revision_cache_data(func: Callable | None = None, **options: Any):
    """Preserva cache_data legado e acrescenta a revisão ao hash no modo oficial.

    O wrapper interno publica uma assinatura que conserva os nomes dos
    parâmetros originais: o Streamlit usa esses nomes para excluir argumentos
    iniciados em '_'. O campo adicional é keyword-only e não começa com '_'.
    A assinatura pública e os argumentos recebidos pela função são preservados.
    """
    def decorate(function: Callable):
        signature = inspect.signature(function)
        name = "tomaconta_official_revision_id"
        while name in signature.parameters:
            name += "_revision"
        parameters = list(signature.parameters.values())
        index = next((i for i, parameter in enumerate(parameters)
                      if parameter.kind == inspect.Parameter.VAR_KEYWORD), len(parameters))
        parameters.insert(index, inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY))

        @wraps(function)
        def with_revision(*args, **kwargs):
            revision, supplied, original_value = kwargs.pop(name)
            if supplied:
                kwargs[name] = original_value
            return function(*args, **kwargs)

        with_revision.__signature__ = signature.replace(parameters=parameters)
        legacy = st.cache_data(**options)(function)
        official = st.cache_data(**options)(with_revision)

        def revision_arguments(kwargs, snapshot):
            # Preserva até uma colisão do campo interno dentro de **kwargs.
            result = dict(kwargs)
            result[name] = (snapshot.revision_id, name in kwargs, kwargs.get(name))
            return result

        @wraps(function)
        def cached(*args, **kwargs):
            snapshot = get_official_read_snapshot()
            if snapshot is None:
                return legacy(*args, **kwargs)
            return official(*args, **revision_arguments(kwargs, snapshot))

        def clear(*args, **kwargs):
            if not args and not kwargs:
                legacy.clear()
                official.clear()
                return
            snapshot = get_official_read_snapshot()
            if snapshot is None:
                legacy.clear(*args, **kwargs)
            else:
                official.clear(*args, **revision_arguments(kwargs, snapshot))

        cached.clear = clear
        cached._revision_cache_parameter = name
        return cached

    return decorate if func is None else decorate(func)
