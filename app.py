"""
Painel de Inteligência de Mercado - Aicitel (E Soares Assessoria Contábil LTDA)

Pergunta que o painel responde: quais empresas existem na área de atuação do
escritório, quais segmentos estão crescendo e quais perfis têm mais chance de
precisar de serviço contábil?

Rodar localmente:  streamlit run app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from indicadores import MINIMO_EMPRESAS, PESOS_PADRAO, oportunidades

RAIZ = Path(__file__).parent
AZUL, AZUL_ESCURO, VERMELHO, CINZA = "#2a78d6", "#1c5cab", "#e34948", "#898781"
SEQUENCIAL = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
REGIAO_VO = "Vila Olímpia e entorno"

st.set_page_config(page_title="Aicitel | Inteligência de Mercado", page_icon="📊", layout="wide")


# ---------------------------------------------------------------- utilidades
def br(n: float, casas: int = 0) -> str:
    """Formata número no padrão brasileiro (1.234,5)."""
    if pd.isna(n):
        return "–"
    s = f"{n:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


EIXO_BR = "replace(replace(format(datum.value, ',.0f'), ',', '.'), ',', '.')"


def eixo(titulo: str | None = None, **kw) -> alt.Axis:
    return alt.Axis(title=titulo, labelExpr=EIXO_BR, grid=True, gridColor="#e1e0d9",
                    domainColor="#c3c2b7", tickColor="#c3c2b7", labelColor="#52514e", **kw)


def eixo_cat(titulo: str | None = None, limite: int = 260) -> alt.Axis:
    return alt.Axis(title=titulo, labelLimit=limite, labelColor="#52514e", domain=False, ticks=False)


@st.cache_data
def carregar():
    emp = pd.read_parquet(RAIZ / "dados" / "empresas.parquet")
    cidade = pd.read_parquet(RAIZ / "dados" / "cidade_cnae.parquet")
    qual = json.loads((RAIZ / "dados" / "qualidade.json").read_text(encoding="utf-8"))
    return emp, cidade, qual


emp, cidade, qual = carregar()
referencia = pd.Timestamp(qual["data_referencia"])
TEM_REGIME = "regime" in emp.columns  # só a base oficial da Receita traz porte, Simples e MEI
REGIMES = ["MEI", "Simples Nacional (exceto MEI)", "Fora do Simples"]
PORTES = ["ME", "EPP", "Demais", "Não informado"]

# ---------------------------------------------------------------- filtros
with st.sidebar:
    st.header("Filtros")
    modo = st.radio("Área de atuação", [REGIAO_VO, "Zona Sul (inteira)", "Escolher bairros"],
                    help="Vila Olímpia e entorno = Vila Olímpia, Itaim Bibi e Vila Nova Conceição. "
                         "Zona Sul = CEPs iniciados em 04 mais os três bairros acima.")
    if modo == REGIAO_VO:
        base = emp[emp["regiao"] == REGIAO_VO]
    elif modo == "Zona Sul (inteira)":
        base = emp
    else:
        contagem = emp["bairro"].value_counts()
        escolha = st.multiselect("Bairros", contagem.index.tolist(),
                                 default=["Moema", "Brooklin Paulista", "Campo Belo"],
                                 format_func=lambda b: f"{b} ({br(contagem[b])})")
        base = emp[emp["bairro"].isin(escolha)]

    segmentos = sorted(s for s in emp["segmento"].unique() if s != "Contabilidade (concorrência)")
    seg_escolha = st.multiselect("Segmentos", segmentos, placeholder="Todos os segmentos")
    reg_escolha = []
    if TEM_REGIME:
        reg_escolha = st.multiselect("Regime tributário", REGIMES, placeholder="Todos os regimes",
                                     help="Opção pelo Simples Nacional e pelo MEI, segundo a Receita Federal.")
    incluir_filiais = st.toggle("Incluir filiais", value=False,
                                help="Filiais costumam ter a contabilidade feita pela matriz.")

    with st.expander("Pesos do índice de oportunidade"):
        st.caption("Ajuste quanto cada critério pesa no ranking.")
        pesos = {
            "volume": st.slider("Quantidade de empresas", 0.0, 1.0, PESOS_PADRAO["volume"], 0.05),
            "novas": st.slider("Empresas novas (12 meses)", 0.0, 1.0, PESOS_PADRAO["novas"], 0.05),
            "crescimento": st.slider("Crescimento acima da média", 0.0, 1.0, PESOS_PADRAO["crescimento"], 0.05),
            "especializacao": st.slider("Especialização da área", 0.0, 1.0, PESOS_PADRAO["especializacao"], 0.05),
        }
        minimo = st.number_input("Mínimo de empresas por atividade", 5, 500, MINIMO_EMPRESAS, 5)

    st.divider()
    base_txt = f"Base {qual['base_receita']} da Receita Federal" if "base_receita" in qual else "Base CNPJ da Receita Federal"
    atual_txt = (f" Atualizada em {pd.Timestamp(qual['atualizado_em']):%d/%m/%Y}; a atualização é automática todo mês."
                 if "atualizado_em" in qual else "")
    st.caption(f"{base_txt}, com dados até {referencia:%d/%m/%Y}. "
               f"Estabelecimentos ativos de 71 atividades típicas de pequenos negócios.{atual_txt}")

if base.empty:
    st.warning("Nenhuma empresa na seleção. Escolha ao menos um bairro.")
    st.stop()

concorrentes = base[base["concorrente"]]
dados = base[~base["concorrente"]]
if seg_escolha:
    dados = dados[dados["segmento"].isin(seg_escolha)]
if reg_escolha:
    dados = dados[dados["regime"].isin(reg_escolha)]
if not incluir_filiais:
    dados = dados[dados["matriz_filial"] == "Matriz"]
if dados.empty:
    st.warning("Nenhuma empresa com esses filtros.")
    st.stop()

# ---------------------------------------------------------------- cabeçalho
st.title("Painel de Inteligência de Mercado")
st.markdown(f"**Aicitel - Assessoria Contábil** · Área: **{modo if modo != 'Escolher bairros' else ', '.join(escolha)}**")
st.caption("Quais empresas existem na área de atuação do escritório, quais segmentos estão crescendo "
           "e quais perfis têm mais chance de precisar de serviço contábil?")

novas = int(dados["recente_12m"].sum())
anteriores = int(dados["anterior_12m"].sum())
variacao = (novas / anteriores - 1) * 100 if anteriores else float("nan")
n_conc = len(concorrentes[concorrentes["matriz_filial"] == "Matriz"])
c1, c2, c3, c4 = st.columns(4)
c1.metric("Empresas ativas", br(len(dados)))
c2.metric("Abertas nos últimos 12 meses", br(novas),
          f"{br(variacao, 1)}% sobre os 12 meses anteriores" if anteriores else None)
c3.metric("Escritórios de contabilidade na área", br(n_conc), help="Concorrentes diretos (CNAE 6920-6/01).")
c4.metric("Empresas por escritório", br(len(dados) / n_conc, 0) if n_conc else "–",
          help="Quanto maior, menos disputado é o mercado local.")

aba1, aba2, aba3, aba4, aba5 = st.tabs(
    ["Visão geral", "Segmentos em crescimento", "Oportunidades", "Bairros e concorrência", "Dados e método"])

# ---------------------------------------------------------------- 1. visão geral
with aba1:
    col_a, col_b = st.columns([1, 1.2])
    por_seg = dados.groupby("segmento").size().reset_index(name="empresas").sort_values("empresas", ascending=False)
    por_seg["rotulo"] = por_seg["empresas"].map(br)
    with col_a:
        st.subheader("Empresas por segmento")
        barras = alt.Chart(por_seg).mark_bar(color=AZUL, cornerRadiusEnd=4, height={"band": 0.75}).encode(
            x=alt.X("empresas:Q", axis=eixo("Empresas ativas")),
            y=alt.Y("segmento:N", sort="-x", axis=eixo_cat()),
            tooltip=[alt.Tooltip("segmento:N", title="Segmento"), alt.Tooltip("rotulo:N", title="Empresas")])
        st.altair_chart(barras.properties(height=34 * len(por_seg) + 40), width="stretch")

    with col_b:
        st.subheader("Empresas abertas por mês")
        fim = referencia.to_period("M") - 1  # último mês completo
        ini = fim - 35
        mensal = (dados.assign(mes=dados["data_inicio"].dt.to_period("M"))
                  .query("@ini <= mes <= @fim").groupby("mes").size()
                  .reindex(pd.period_range(ini, fim, freq="M"), fill_value=0)
                  .rename_axis("mes").reset_index(name="empresas"))
        mensal["data"] = mensal["mes"].dt.to_timestamp()
        mensal["rotulo"] = mensal["empresas"].map(br)
        mensal["mes_txt"] = mensal["data"].dt.strftime("%m/%Y")
        mensal = mensal.drop(columns="mes")
        base_l = alt.Chart(mensal).encode(x=alt.X("data:T", axis=alt.Axis(title=None, format="%m/%y",
                                                                           labelColor="#52514e", grid=False)))
        linha = base_l.mark_line(color=AZUL, strokeWidth=2).encode(y=alt.Y("empresas:Q", axis=eixo("Empresas abertas")))
        sel = alt.selection_point(fields=["data"], nearest=True, on="pointerover", empty=False)
        pontos = base_l.mark_point(color=AZUL, size=70, filled=True).encode(
            y="empresas:Q", opacity=alt.condition(sel, alt.value(1), alt.value(0)),
            tooltip=[alt.Tooltip("mes_txt:N", title="Mês"), alt.Tooltip("rotulo:N", title="Empresas abertas")]
        ).add_params(sel)
        regra = base_l.mark_rule(color="#c3c2b7").encode(opacity=alt.condition(sel, alt.value(1), alt.value(0)))
        st.altair_chart((linha + regra + pontos).properties(height=330), width="stretch")
        st.caption("Conta as empresas que continuam ativas hoje, pela data em que entraram em atividade. "
                   "Empresas abertas e já encerradas não aparecem, por isso os anos mais antigos ficam menores.")

    if TEM_REGIME:
        def barras_categoria(coluna: str, ordem: list[str], titulo: str):
            cont = dados[coluna].value_counts().reindex(ordem, fill_value=0).reset_index()
            cont.columns = ["categoria", "empresas"]
            cont["pct"] = cont["empresas"] / max(cont["empresas"].sum(), 1) * 100
            cont["rotulo"] = cont.apply(lambda r: f"{br(r.empresas)} ({br(r.pct, 1)}%)", axis=1)
            base_c = alt.Chart(cont).encode(
                y=alt.Y("categoria:N", sort=ordem, axis=eixo_cat(limite=220)),
                x=alt.X("empresas:Q", axis=eixo("Empresas ativas"),
                        scale=alt.Scale(domain=[0, max(int(cont["empresas"].max() * 1.35), 1)])))
            barras_c = base_c.mark_bar(color=AZUL, cornerRadiusEnd=4, height={"band": 0.7}).encode(
                tooltip=[alt.Tooltip("categoria:N", title=titulo), alt.Tooltip("rotulo:N", title="Empresas")])
            texto = base_c.mark_text(align="left", dx=6, color="#52514e", fontSize=12).encode(text="rotulo:N")
            return (barras_c + texto).properties(height=46 * len(ordem) + 40)

        col_r, col_p = st.columns(2)
        with col_r:
            st.subheader("Regime tributário")
            st.altair_chart(barras_categoria("regime", REGIMES, "Regime"), width="stretch")
        with col_p:
            st.subheader("Porte")
            st.altair_chart(barras_categoria("porte", PORTES, "Porte"), width="stretch")
        st.caption("Regime e porte segundo o cadastro da Receita Federal. O MEI também é optante pelo Simples "
                   "Nacional, mas aparece separado porque o serviço contábil que ele precisa é bem mais simples.")

    st.subheader("Atividades com mais empresas")
    top = (dados.groupby(["atividade_resumo", "segmento"]).agg(empresas=("cnpj", "size"), novas=("recente_12m", "sum"))
           .reset_index().sort_values("empresas", ascending=False).head(15))
    st.dataframe(top, hide_index=True, width="stretch", column_config={
        "atividade_resumo": st.column_config.TextColumn("Atividade", width="large"),
        "segmento": "Segmento",
        "empresas": st.column_config.NumberColumn("Empresas ativas", format="localized"),
        "novas": st.column_config.NumberColumn("Abertas em 12 meses", format="localized")})

# ---------------------------------------------------------------- 2. crescimento
with aba2:
    st.subheader("Quais segmentos crescem mais rápido que a média da área")
    g = dados.groupby("segmento").agg(ativas=("cnpj", "size"), novas=("recente_12m", "sum"),
                                      anteriores=("anterior_12m", "sum")).reset_index()
    media = (g["novas"].sum() + 1) / (g["anteriores"].sum() + 1)
    g["relativo"] = ((g["novas"] + 1) / (g["anteriores"] + 1)) / media
    g["dif"] = (g["relativo"] - 1) * 100
    g["variacao"] = (g["novas"] / g["anteriores"].where(g["anteriores"] > 0) - 1) * 100
    g["sentido"] = g["dif"].map(lambda d: "Acima da média" if d >= 0 else "Abaixo da média")
    g["rotulo"] = g["dif"].map(lambda d: f"{'+' if d >= 0 else ''}{br(d, 1)} p.p.")
    g = g.sort_values("dif", ascending=False)

    div = alt.Chart(g).mark_bar(cornerRadiusEnd=4, height={"band": 0.75}).encode(
        x=alt.X("dif:Q", axis=alt.Axis(title="Diferença em relação ao ritmo médio da área (%)", labelExpr=EIXO_BR,
                                       gridColor="#e1e0d9", labelColor="#52514e")),
        y=alt.Y("segmento:N", sort=alt.SortField("dif", order="descending"), axis=eixo_cat()),
        color=alt.Color("sentido:N", scale=alt.Scale(domain=["Acima da média", "Abaixo da média"],
                                                     range=[AZUL, VERMELHO]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("segmento:N", title="Segmento"), alt.Tooltip("rotulo:N", title="Diferença"),
                 alt.Tooltip("novas:Q", title="Abertas (12 meses)"),
                 alt.Tooltip("anteriores:Q", title="Abertas (12 meses anteriores)")])
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#898781").encode(x="x:Q")
    st.altair_chart((div + zero).properties(height=34 * len(g) + 60), width="stretch")
    st.caption(f"Compara as aberturas dos últimos 12 meses (até {referencia:%d/%m/%Y}) com as dos 12 meses "
               "anteriores. Como as duas janelas sofrem o mesmo efeito de encerramentos, o resultado é lido em "
               "relação à média da própria área, e não como taxa absoluta.")

    st.dataframe(g[["segmento", "ativas", "novas", "anteriores", "variacao", "dif"]], hide_index=True,
                 width="stretch", column_config={
                     "segmento": "Segmento",
                     "ativas": st.column_config.NumberColumn("Empresas ativas", format="localized"),
                     "novas": st.column_config.NumberColumn("Abertas (12 meses)", format="localized"),
                     "anteriores": st.column_config.NumberColumn("Abertas (12 meses anteriores)", format="localized"),
                     "variacao": st.column_config.NumberColumn("Variação (%)", format="%.1f"),
                     "dif": st.column_config.NumberColumn("Diferença p/ média (p.p.)", format="%.1f")})

    st.subheader("Aberturas por ano em cada segmento")
    anos = dados[dados["ano"].between(referencia.year - 10, referencia.year - 1)]
    anual = anos.groupby(["segmento", "ano"]).size().reset_index(name="empresas")
    anual["ano"] = anual["ano"].astype(int)
    multiplos = alt.Chart(anual).mark_area(color=AZUL, opacity=0.18, line={"color": AZUL, "strokeWidth": 2}).encode(
        x=alt.X("ano:O", axis=alt.Axis(title=None, labelAngle=0, values=list(range(referencia.year - 10, referencia.year, 3)),
                                       labelColor="#52514e")),
        y=alt.Y("empresas:Q", axis=alt.Axis(title=None, labelExpr=EIXO_BR, gridColor="#e1e0d9", tickCount=3,
                                            labelColor="#52514e")),
        tooltip=[alt.Tooltip("segmento:N", title="Segmento"), alt.Tooltip("ano:O", title="Ano"),
                 alt.Tooltip("empresas:Q", title="Empresas abertas", format=",.0f")]
    ).properties(width=180, height=110).facet(
        facet=alt.Facet("segmento:N", title=None, header=alt.Header(labelFontWeight="bold", labelLimit=200)),
        columns=4).resolve_scale(y="independent")
    st.altair_chart(multiplos, width="content")
    st.caption("Cada quadro tem escala própria, para mostrar a tendência de cada segmento. "
               f"Anos completos de {referencia.year - 10} a {referencia.year - 1}.")

# ---------------------------------------------------------------- 3. oportunidades
with aba3:
    st.subheader("Ranking de atividades com maior potencial de clientes")
    rank = oportunidades(dados.assign(concorrente=False), cidade, pesos, int(minimo))
    if rank.empty:
        st.info("Poucas empresas para montar o ranking. Reduza o mínimo de empresas por atividade.")
    else:
        top15 = rank.head(15).copy()
        top15["rotulo"] = top15["indice"].map(lambda v: br(v, 1))
        idx = alt.Chart(top15).mark_bar(color=AZUL, cornerRadiusEnd=4, height={"band": 0.75}).encode(
            x=alt.X("indice:Q", scale=alt.Scale(domain=[0, 100]), axis=eixo("Índice de oportunidade (0 a 100)")),
            y=alt.Y("atividade_resumo:N", sort=alt.SortField("indice", order="descending"), axis=eixo_cat(limite=380)),
            tooltip=[alt.Tooltip("atividade:N", title="Atividade"), alt.Tooltip("segmento:N", title="Segmento"),
                     alt.Tooltip("rotulo:N", title="Índice"), alt.Tooltip("volume:Q", title="Empresas ativas"),
                     alt.Tooltip("novas:Q", title="Abertas em 12 meses")])
        st.altair_chart(idx.properties(height=34 * len(top15) + 40), width="stretch")

        colunas_rank = ["posicao", "atividade_resumo", "segmento", "volume", "novas", "crescimento", "especializacao", "indice"]
        if TEM_REGIME:
            mat = dados[dados["matriz_filial"] == "Matriz"]
            pct = (mat.assign(mei=mat["regime"].eq(REGIMES[0]), sn=mat["regime"].eq(REGIMES[1]))
                   .groupby("atividade_resumo")[["mei", "sn"]].mean().mul(100).reset_index())
            rank = rank.merge(pct, on="atividade_resumo", how="left")
            colunas_rank = colunas_rank[:5] + ["mei", "sn"] + colunas_rank[5:]
        st.dataframe(rank[colunas_rank],
                     hide_index=True, width="stretch", column_config={
                         "posicao": st.column_config.NumberColumn("#", width="small"),
                         "atividade_resumo": st.column_config.TextColumn("Atividade", width="large"),
                         "segmento": "Segmento",
                         "volume": st.column_config.NumberColumn("Empresas ativas", format="localized"),
                         "novas": st.column_config.NumberColumn("Abertas em 12 meses", format="localized"),
                         "mei": st.column_config.NumberColumn("% MEI", format="%.0f%%"),
                         "sn": st.column_config.NumberColumn("% Simples (exceto MEI)", format="%.0f%%"),
                         "crescimento": st.column_config.NumberColumn("Crescimento relativo", format="%.2f",
                                                                      help="Acima de 1 = cresce mais que a média da área."),
                         "especializacao": st.column_config.NumberColumn("Especialização", format="%.2f",
                                                                         help="Acima de 1 = a área concentra mais essa atividade que a cidade."),
                         "indice": st.column_config.ProgressColumn("Índice", format="%.1f", min_value=0, max_value=100)})
        with st.expander("Como o índice é calculado"):
            st.markdown(
                "O índice combina quatro critérios, cada um reescalado de 0 a 1 e somado com os pesos da barra lateral:\n\n"
                "- **Quantidade de empresas**: matrizes ativas da atividade na área (em escala logarítmica).\n"
                "- **Empresas novas**: matrizes abertas nos últimos 12 meses. Empresa recém-aberta é quem mais procura contador.\n"
                "- **Crescimento acima da média**: ritmo de aberturas da atividade comparado ao da área inteira.\n"
                "- **Especialização**: quociente locacional, ou seja, o peso da atividade na área dividido pelo peso dela "
                "no município. Mostra nichos em que a região é forte.\n\n"
                "Filiais e escritórios de contabilidade ficam fora do cálculo.")

        st.subheader("Lista de prospecção")
        opcoes = rank["atividade_resumo"].tolist()
        alvo = st.multiselect("Atividades", opcoes, default=opcoes[:3])
        so_novas = st.toggle("Só empresas abertas nos últimos 12 meses", value=True)
        lista = dados[dados["atividade_resumo"].isin(alvo) & (dados["matriz_filial"] == "Matriz")]
        if so_novas:
            lista = lista[lista["recente_12m"]]
        colunas_lista = ["cnpj", "nome_fantasia", "atividade_resumo", "bairro", "cep", "data_inicio"]
        if TEM_REGIME:
            colunas_lista += ["regime", "porte"]
        lista = lista.sort_values("data_inicio", ascending=False)[colunas_lista]
        st.caption(f"{br(len(lista))} empresas")
        st.dataframe(lista, hide_index=True, width="stretch", column_config={
            "cnpj": "CNPJ", "nome_fantasia": "Nome fantasia",
            "atividade_resumo": st.column_config.TextColumn("Atividade", width="large"),
            "bairro": "Bairro", "cep": "CEP", "regime": "Regime", "porte": "Porte",
            "data_inicio": st.column_config.DateColumn("Início da atividade", format="DD/MM/YYYY")})
        st.download_button("Baixar lista em CSV (Excel)",
                           lista.rename(columns={"cnpj": "CNPJ", "nome_fantasia": "Nome fantasia",
                                                 "atividade_resumo": "Atividade", "bairro": "Bairro", "cep": "CEP",
                                                 "data_inicio": "Início da atividade", "regime": "Regime",
                                                 "porte": "Porte"})
                           .to_csv(sep=";", index=False, date_format="%d/%m/%Y").encode("utf-8-sig"),
                           file_name="lista_prospeccao_aicitel.csv", mime="text/csv")

# ---------------------------------------------------------------- 4. bairros
with aba4:
    col_a, col_b = st.columns([1, 1.1])
    por_bairro = dados.groupby("bairro").size().reset_index(name="empresas").sort_values("empresas", ascending=False)
    top_b = por_bairro.head(15).copy()
    top_b["rotulo"] = top_b["empresas"].map(br)
    with col_a:
        st.subheader("Bairros com mais empresas")
        bb = alt.Chart(top_b).mark_bar(color=AZUL, cornerRadiusEnd=4, height={"band": 0.75}).encode(
            x=alt.X("empresas:Q", axis=eixo("Empresas ativas")),
            y=alt.Y("bairro:N", sort="-x", axis=eixo_cat()),
            tooltip=[alt.Tooltip("bairro:N", title="Bairro"), alt.Tooltip("rotulo:N", title="Empresas")])
        st.altair_chart(bb.properties(height=34 * len(top_b) + 40), width="stretch")
    with col_b:
        st.subheader("Concorrência por bairro")
        conc = concorrentes[concorrentes["matriz_filial"] == "Matriz"].groupby("bairro").size().rename("escritorios")
        tab = por_bairro.set_index("bairro").join(conc).fillna({"escritorios": 0}).reset_index()
        tab = tab[tab["empresas"] >= 100]
        tab["por_escritorio"] = tab["empresas"] / tab["escritorios"].where(tab["escritorios"] > 0)
        tab = tab.sort_values(["por_escritorio", "empresas"], ascending=False, na_position="first").head(15)
        st.dataframe(tab, hide_index=True, width="stretch", column_config={
            "bairro": "Bairro",
            "empresas": st.column_config.NumberColumn("Empresas", format="localized"),
            "escritorios": st.column_config.NumberColumn("Escritórios de contabilidade", format="%d"),
            "por_escritorio": st.column_config.NumberColumn("Empresas por escritório", format="%.0f")})
        st.caption("Bairros com pelo menos 100 empresas, ordenados pelo número de empresas por escritório. "
                   "Bairro sem escritório aparece no topo, com o campo vazio.")

    st.subheader("Perfil de segmentos dos principais bairros")
    bairros_top = por_bairro.head(12)["bairro"].tolist()
    perfil = dados[dados["bairro"].isin(bairros_top)].groupby(["bairro", "segmento"]).size().reset_index(name="n")
    perfil["pct"] = perfil["n"] / perfil.groupby("bairro")["n"].transform("sum") * 100
    perfil["rotulo"] = perfil["pct"].map(lambda v: f"{br(v, 1)}%")
    calor = alt.Chart(perfil).mark_rect(stroke="#fcfcfb", strokeWidth=2).encode(
        x=alt.X("bairro:N", sort=bairros_top, axis=alt.Axis(title=None, labelAngle=-35, labelLimit=160,
                                                            labelColor="#52514e", domain=False, ticks=False)),
        y=alt.Y("segmento:N", axis=eixo_cat()),
        color=alt.Color("pct:Q", scale=alt.Scale(range=SEQUENCIAL),
                        legend=alt.Legend(title="% das empresas do bairro", orient="top", gradientLength=220)),
        tooltip=[alt.Tooltip("bairro:N", title="Bairro"), alt.Tooltip("segmento:N", title="Segmento"),
                 alt.Tooltip("rotulo:N", title="Participação"), alt.Tooltip("n:Q", title="Empresas")])
    st.altair_chart(calor.properties(height=34 * perfil["segmento"].nunique() + 60), width="stretch")

# ---------------------------------------------------------------- 5. dados e método
with aba5:
    st.subheader("Fonte")
    st.markdown(f"{qual['fonte']}. Dados até **{referencia:%d/%m/%Y}**.")
    st.subheader("Tratamento e qualidade dos dados")
    linhas = [
        ("Estabelecimentos no estado de SP", br(qual["registros_estado"])),
        ("Estabelecimentos no município de São Paulo", br(qual["registros_municipio"])),
        ("CNPJs duplicados removidos", br(qual["cnpj_duplicados_removidos"])),
        ("Datas de início inválidas (mantidas sem data)", br(qual["datas_invalidas"])),
        ("CEPs inválidos", br(qual["cep_invalido"])),
        ("Bairros vazios ou só com números (no município)", br(qual["bairro_vazio"])),
        ("Sem nome fantasia", f"{br(qual['sem_nome_fantasia_pct'], 1)}%"),
        ("Grafias diferentes unificadas nos bairros da Vila Olímpia e entorno", br(qual["grafias_bairro_vila_olimpia"])),
        ("Estabelecimentos na Vila Olímpia e entorno", br(qual["registros_vila_olimpia"])),
        ("Estabelecimentos nos demais bairros da Zona Sul", br(qual["registros_zona_sul"])),
        ("Matrizes (%)", f"{br(qual['matrizes_pct'], 1)}%"),
    ]
    if TEM_REGIME:
        linhas += [
            ("Matrizes optantes pelo MEI (%)", f"{br(qual['mei_pct'], 1)}%"),
            ("Matrizes no Simples Nacional, exceto MEI (%)", f"{br(qual['simples_exceto_mei_pct'], 1)}%"),
            ("Matrizes fora do Simples Nacional (%)", f"{br(qual['fora_simples_pct'], 1)}%"),
        ]
    if "atualizado_em" in qual:
        linhas.append(("Última atualização dos dados", f"{pd.Timestamp(qual['atualizado_em']):%d/%m/%Y}"))
    st.dataframe(pd.DataFrame(linhas, columns=["Item", "Valor"]), hide_index=True, width="stretch")
    st.markdown(
        "**Etapas do tratamento**\n\n"
        "1. Filtro do município de São Paulo e remoção de CNPJs repetidos.\n"
        "2. Conversão das datas (AAAAMMDD) e cálculo das janelas de 12 meses.\n"
        "3. Padronização dos bairros: retirada de acentos e pontuação, expansão de abreviações "
        "(VL, V, JD, PQ) e devolução dos acentos na exibição.\n"
        "4. Máscaras de CNPJ, CEP e CNAE, descrição oficial de cada CNAE e agrupamento em segmentos.\n"
        "5. Delimitação da área: Vila Olímpia, Itaim Bibi e Vila Nova Conceição pelo nome do bairro; "
        "Zona Sul pela faixa de CEP 04000-000 a 04999-999.\n"
        + ("6. Junção do porte (tabela Empresas) e da opção pelo Simples Nacional e pelo MEI (tabela Simples).\n"
           if TEM_REGIME else "")
        + "\n**Atualização**\n\n"
        "Uma rotina automática no GitHub baixa todo mês a base oficial mais recente da Receita Federal, refaz o "
        "tratamento e publica os dados novos no painel.\n\n"
        "**Limitações**\n\n"
        "- O painel considera só empresas ativas. Não mede encerramentos.\n"
        "- Cobre 71 atividades típicas de pequenos negócios, e não todas as atividades econômicas.\n"
        + ("- O porte é declarado pela própria empresa e pode estar desatualizado. A Receita não informa se a "
           "empresa fora do Simples está no Lucro Presumido ou no Lucro Real.\n" if TEM_REGIME else
           "- Esta base não informa porte (ME/EPP), opção pelo Simples ou MEI.\n")
        + ("- A data usada é a de início da atividade.\n" if TEM_REGIME else
           "- A data usada é a da situação cadastral atual, que para empresas ativas costuma coincidir com o "
           "início da atividade, mas pode ser posterior em empresas reativadas.\n")
        + "- Telefone, e-mail, razão social e endereço completo não foram usados (LGPD).")
