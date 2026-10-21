"""Cálculo dos indicadores de oportunidade (usado pelo painel e pela preparação dos dados)."""
from __future__ import annotations

import numpy as np
import pandas as pd

PESOS_PADRAO = {"volume": 0.30, "novas": 0.30, "crescimento": 0.20, "especializacao": 0.20}
MINIMO_EMPRESAS = 20  # atividades com menos matrizes que isso ficam fora do ranking


def _escala(s: pd.Series) -> pd.Series:
    """Reescala para 0-1 (min-max). Série constante vira 0,5."""
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or hi == lo:
        return pd.Series(0.5, index=s.index)
    return (s - lo) / (hi - lo)


def oportunidades(area: pd.DataFrame, cidade: pd.DataFrame, pesos: dict | None = None,
                  minimo: int = MINIMO_EMPRESAS) -> pd.DataFrame:
    """
    area   : estabelecimentos da área escolhida (colunas cnae_cod, atividade, segmento,
             matriz_filial, recente_12m, anterior_12m, concorrente)
    cidade : uma linha por cnae_cod com ativas_cidade (matrizes ativas no município)

    Indicadores por atividade (só matrizes, sem escritórios de contabilidade):
      volume          matrizes ativas na área
      novas           matrizes que entraram em atividade nos últimos 12 meses
      crescimento     (novas / entradas nos 12 meses anteriores) da atividade dividido pela
                      mesma razão para o conjunto da área; acima de 1 = cresce mais que a média
      especializacao  quociente locacional: peso da atividade na área / peso na cidade
    Índice = soma ponderada dos quatro indicadores reescalados de 0 a 1, vezes 100.
    """
    pesos = pesos or PESOS_PADRAO
    m = area[(area["matriz_filial"] == "Matriz") & ~area["concorrente"]]
    if m.empty:
        return pd.DataFrame()
    chaves = [c for c in ["cnae_cod", "atividade", "atividade_resumo", "segmento"] if c in m.columns]
    g = m.groupby(chaves, as_index=False).agg(
        volume=("cnae_cod", "size"), novas=("recente_12m", "sum"), anteriores=("anterior_12m", "sum"))
    razao_total = (g["novas"].sum() + 1) / (g["anteriores"].sum() + 1)
    g["crescimento"] = ((g["novas"] + 1) / (g["anteriores"] + 1)) / razao_total

    cid = cidade.set_index("cnae_cod")["ativas_cidade"]
    cid = cid[cid.index.isin(g["cnae_cod"])]
    peso_area = g.set_index("cnae_cod")["volume"] / g["volume"].sum()
    peso_cid = cid / cid.sum()
    g["especializacao"] = g["cnae_cod"].map(peso_area / peso_cid)

    g = g[g["volume"] >= minimo].copy()
    if g.empty:
        return g
    comp = pd.DataFrame({
        "volume": _escala(np.log1p(g["volume"])),
        "novas": _escala(np.log1p(g["novas"])),
        "crescimento": _escala(g["crescimento"].clip(0, 3)),
        "especializacao": _escala(g["especializacao"].clip(0, 3)),
    })
    soma = sum(pesos.values()) or 1
    g["indice"] = 100 * sum(comp[k] * v for k, v in pesos.items()) / soma
    g = g.sort_values("indice", ascending=False).reset_index(drop=True)
    g.insert(0, "posicao", np.arange(1, len(g) + 1))
    return g
