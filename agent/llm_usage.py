"""Extração de contagens de tokens a partir da resposta LangChain / provedores compatíveis."""

from __future__ import annotations


def extract_llm_usage_tokens(response) -> tuple[int | None, int | None]:
    """
    Obtém contagem de tokens de entrada/saída quando o provider popula o AIMessage.

    LangChain costuma usar ``usage_metadata``; alguns backends só preenchem ``response_metadata``.
    """
    inp: int | None = None
    outp: int | None = None

    um = getattr(response, "usage_metadata", None)
    if isinstance(um, dict):
        ri = um.get("input_tokens")
        ro = um.get("output_tokens")
        if ri is None:
            ri = um.get("prompt_tokens")
        if ro is None:
            ro = um.get("completion_tokens")
        try:
            inp = int(ri) if ri is not None else None
        except (TypeError, ValueError):
            inp = None
        try:
            outp = int(ro) if ro is not None else None
        except (TypeError, ValueError):
            outp = None

    if inp is None or outp is None:
        rm = getattr(response, "response_metadata", None)
        if isinstance(rm, dict):
            usage = rm.get("usage")
            if not isinstance(usage, dict):
                usage = rm.get("token_usage")
            if isinstance(usage, dict):
                ri = usage.get("input_tokens") or usage.get("prompt_tokens")
                ro = usage.get("output_tokens") or usage.get("completion_tokens")
                try:
                    if inp is None and ri is not None:
                        inp = int(ri)
                except (TypeError, ValueError):
                    pass
                try:
                    if outp is None and ro is not None:
                        outp = int(ro)
                except (TypeError, ValueError):
                    pass

    return inp, outp
