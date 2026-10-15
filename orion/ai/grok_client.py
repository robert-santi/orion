"""Chamada externa removida. A verificação não usa conta nem rede de terceiros."""


def ask_grok(*_args, **_kwargs) -> str:
    raise RuntimeError("A verificação do ORION não chama serviço externo.")
