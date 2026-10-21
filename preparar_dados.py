"""
Preparação dos dados do painel de inteligência de mercado da Aicitel.

Entrada : SP.db, base de estabelecimentos ativos do estado de São Paulo
          (Dados Abertos do CNPJ da Receita Federal, referência 2026-09,
          publicada pelo projeto Caça-Cliente no GitHub).
Saídas  : dados/empresas.parquet      estabelecimentos da área de atuação (painel Streamlit)
          dados/cidade_cnae.parquet   totais do município por atividade (comparação)
          dados/qualidade.json        relatório de limpeza e qualidade
          powerbi/*.csv               tabelas do modelo do Power BI

Etapas: filtragem do município, tratamento de datas, padronização de bairros
(grafias como "VL. OLIMPIA" e "V NOVA CONCEICAO"), máscaras de CNPJ/CEP/CNAE,
classificação das atividades em segmentos, delimitação da área de atuação e
cálculo das janelas de 12 meses.

Uso: python preparar_dados.py [caminho/para/SP.db]
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import pandas as pd

from indicadores import PESOS_PADRAO, oportunidades

RAIZ = Path(__file__).parent
DB = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "dados_brutos" / "SP.db"

# ---------------------------------------------------------------------------
# Catálogo das 71 atividades: código CNAE -> (descrição oficial, segmento)
# ---------------------------------------------------------------------------
CATALOGO = {
    "8630503": ("Atividade médica ambulatorial restrita a consultas", "Saúde"),
    "8630504": ("Atividade odontológica", "Saúde"),
    "8630501": ("Atividade médica ambulatorial com recursos para realização de procedimentos cirúrgicos", "Saúde"),
    "8630502": ("Atividade médica ambulatorial com recursos para realização de exames complementares", "Saúde"),
    "8650003": ("Atividades de psicologia e psicanálise", "Saúde"),
    "8650004": ("Atividades de fisioterapia", "Saúde"),
    "8650002": ("Atividades de profissionais da nutrição", "Saúde"),
    "7500100": ("Atividades veterinárias", "Pet"),
    "4789004": ("Comércio varejista de animais vivos e de artigos e alimentos para animais de estimação", "Pet"),
    "9602501": ("Cabeleireiros, manicure e pedicure", "Beleza e estética"),
    "9602502": ("Atividades de estética e outros serviços de cuidados com a beleza", "Beleza e estética"),
    "9609206": ("Serviços de tatuagem e colocação de piercing", "Beleza e estética"),
    "9313100": ("Atividades de condicionamento físico", "Academias e bem-estar"),
    "5611201": ("Restaurantes e similares", "Bares, restaurantes e hotéis"),
    "5611203": ("Lanchonetes, casas de chá, de sucos e similares", "Bares, restaurantes e hotéis"),
    "5611204": ("Bares e outros estabelecimentos especializados em servir bebidas, sem entretenimento", "Bares, restaurantes e hotéis"),
    "5611205": ("Bares e outros estabelecimentos especializados em servir bebidas, com entretenimento", "Bares, restaurantes e hotéis"),
    "5510801": ("Hotéis", "Bares, restaurantes e hotéis"),
    "4712100": ("Comércio varejista de mercadorias em geral, com predominância de produtos alimentícios - minimercados, mercearias e armazéns", "Mercados, padarias e alimentos"),
    "4711302": ("Comércio varejista de mercadorias em geral, com predominância de produtos alimentícios - supermercados", "Mercados, padarias e alimentos"),
    "4729699": ("Comércio varejista de produtos alimentícios em geral ou especializado em produtos alimentícios não especificados anteriormente", "Mercados, padarias e alimentos"),
    "4729602": ("Comércio varejista de mercadorias em lojas de conveniência", "Mercados, padarias e alimentos"),
    "4721102": ("Padaria e confeitaria com predominância de revenda", "Mercados, padarias e alimentos"),
    "1091102": ("Fabricação de produtos de padaria e confeitaria com predominância de produção própria", "Mercados, padarias e alimentos"),
    "4722901": ("Comércio varejista de carnes - açougues", "Mercados, padarias e alimentos"),
    "4721104": ("Comércio varejista de doces, balas, bombons e semelhantes", "Mercados, padarias e alimentos"),
    "4781400": ("Comércio varejista de artigos do vestuário e acessórios", "Moda e vestuário"),
    "1412602": ("Confecção, sob medida, de peças do vestuário, exceto roupas íntimas", "Moda e vestuário"),
    "4774100": ("Comércio varejista de artigos de óptica", "Comércio varejista diverso"),
    "4761003": ("Comércio varejista de artigos de papelaria", "Comércio varejista diverso"),
    "4771701": ("Comércio varejista de produtos farmacêuticos, sem manipulação de fórmulas", "Comércio varejista diverso"),
    "4771702": ("Comércio varejista de produtos farmacêuticos, com manipulação de fórmulas", "Comércio varejista diverso"),
    "4789002": ("Comércio varejista de plantas e flores naturais", "Comércio varejista diverso"),
    "4399103": ("Obras de alvenaria", "Construção e reformas"),
    "4321500": ("Instalação e manutenção elétrica", "Construção e reformas"),
    "4322301": ("Instalações hidráulicas, sanitárias e de gás", "Construção e reformas"),
    "4330404": ("Serviços de pintura de edifícios em geral", "Construção e reformas"),
    "4330402": ("Instalação de portas, janelas, tetos, divisórias e armários embutidos de qualquer material", "Construção e reformas"),
    "4120400": ("Construção de edifícios", "Construção e reformas"),
    "2542000": ("Fabricação de artigos de serralheria, exceto esquadrias", "Construção e reformas"),
    "2512800": ("Fabricação de esquadrias de metal", "Construção e reformas"),
    "3101200": ("Fabricação de móveis com predominância de madeira", "Construção e reformas"),
    "4744099": ("Comércio varejista de materiais de construção em geral", "Construção e reformas"),
    "4744001": ("Comércio varejista de ferragens e ferramentas", "Construção e reformas"),
    "4744005": ("Comércio varejista de materiais de construção não especificados anteriormente", "Construção e reformas"),
    "4743100": ("Comércio varejista de vidros", "Construção e reformas"),
    "4520001": ("Serviços de manutenção e reparação mecânica de veículos automotores", "Automotivo"),
    "4520002": ("Serviços de lanternagem ou funilaria e pintura de veículos automotores", "Automotivo"),
    "4520003": ("Serviços de manutenção e reparação elétrica de veículos automotores", "Automotivo"),
    "4520005": ("Serviços de lavagem, lubrificação e polimento de veículos automotores", "Automotivo"),
    "4520006": ("Serviços de borracharia para veículos automotores", "Automotivo"),
    "4530703": ("Comércio a varejo de peças e acessórios novos para veículos automotores", "Automotivo"),
    "4530705": ("Comércio a varejo de pneumáticos e câmaras-de-ar", "Automotivo"),
    "4541206": ("Comércio a varejo de peças e acessórios novos para motocicletas e motonetas", "Automotivo"),
    "4543900": ("Manutenção e reparação de motocicletas e motonetas", "Automotivo"),
    "6911701": ("Serviços advocatícios", "Serviços profissionais"),
    "7111100": ("Serviços de arquitetura", "Serviços profissionais"),
    "7420001": ("Atividades de produção de fotografias, exceto aérea e submarina", "Serviços profissionais"),
    "6920601": ("Atividades de contabilidade", "Contabilidade (concorrência)"),
    "6821801": ("Corretagem na compra e venda e avaliação de imóveis", "Imobiliário"),
    "6821802": ("Corretagem no aluguel de imóveis", "Imobiliário"),
    "8593700": ("Ensino de idiomas", "Educação"),
    "8599601": ("Formação de condutores", "Educação"),
    "9512600": ("Reparação e manutenção de equipamentos de comunicação", "Reparos, gráficas e serviços gerais"),
    "9521500": ("Reparação e manutenção de equipamentos eletroeletrônicos de uso pessoal e doméstico", "Reparos, gráficas e serviços gerais"),
    "9529102": ("Chaveiros", "Reparos, gráficas e serviços gerais"),
    "9601701": ("Lavanderias", "Reparos, gráficas e serviços gerais"),
    "9601702": ("Tinturarias", "Reparos, gráficas e serviços gerais"),
    "8219901": ("Fotocópias", "Reparos, gráficas e serviços gerais"),
    "1813001": ("Impressão de material para uso publicitário", "Reparos, gráficas e serviços gerais"),
    "1813099": ("Impressão de material para outros usos", "Reparos, gráficas e serviços gerais"),
}

# Nomes curtos para gráficos (as descrições oficiais longas se confundem quando cortadas)
NOME_CURTO = {
    "8630503": "Consultório médico (só consultas)", "8630504": "Consultório odontológico",
    "8630501": "Clínica médica com procedimentos cirúrgicos", "8630502": "Clínica médica com exames",
    "8650003": "Psicologia e psicanálise", "8650004": "Fisioterapia", "8650002": "Nutrição",
    "7500100": "Veterinária", "4789004": "Pet shop", "9602501": "Cabeleireiro, manicure e pedicure",
    "9602502": "Estética e cuidados com a beleza", "9609206": "Tatuagem e piercing",
    "9313100": "Academia", "5611203": "Lanchonete, casa de chá e sucos",
    "5611204": "Bar sem entretenimento", "5611205": "Bar com entretenimento",
    "4712100": "Minimercado, mercearia e armazém", "4711302": "Supermercado",
    "4729699": "Comércio de alimentos em geral", "4729602": "Loja de conveniência",
    "4721102": "Padaria (revenda)", "1091102": "Padaria e confeitaria (produção própria)",
    "4722901": "Açougue", "4721104": "Doces, balas e bombons",
    "4781400": "Roupas e acessórios", "1412602": "Confecção sob medida", "4774100": "Óptica",
    "4761003": "Papelaria", "4771701": "Farmácia", "4771702": "Farmácia de manipulação",
    "4789002": "Floricultura", "4321500": "Instalação elétrica", "4322301": "Instalação hidráulica e de gás",
    "4330404": "Pintura de edifícios", "4330402": "Portas, janelas e armários embutidos",
    "2542000": "Serralheria", "2512800": "Esquadrias de metal", "3101200": "Móveis de madeira",
    "4744099": "Materiais de construção em geral", "4744001": "Ferragens e ferramentas",
    "4744005": "Materiais de construção (outros)", "4743100": "Vidraçaria",
    "4520001": "Mecânica de veículos", "4520002": "Funilaria e pintura", "4520003": "Elétrica de veículos",
    "4520005": "Lava-rápido", "4520006": "Borracharia", "4530703": "Autopeças", "4530705": "Pneus",
    "4541206": "Peças para motos", "4543900": "Oficina de motos", "6911701": "Advocacia",
    "7111100": "Arquitetura", "7420001": "Fotografia", "6920601": "Contabilidade",
    "6821801": "Corretagem de imóveis (venda)", "6821802": "Corretagem de imóveis (aluguel)",
    "8593700": "Escola de idiomas", "8599601": "Autoescola",
    "9512600": "Reparo de equipamentos de comunicação", "9521500": "Reparo de eletroeletrônicos",
    "1813001": "Gráfica (material publicitário)", "1813099": "Gráfica (outros usos)",
}

REGIAO_VO = "Vila Olímpia e entorno"
REGIAO_ZS = "Demais bairros da Zona Sul"
BAIRROS_VO = {"VILA OLIMPIA": "Vila Olímpia", "ITAIM BIBI": "Itaim Bibi",
              "VILA NOVA CONCEICAO": "Vila Nova Conceição"}
ACENTOS = {  # devolve acentos às palavras mais comuns nos nomes de bairro
    "Sao": "São", "Joao": "João", "Jose": "José", "Conceicao": "Conceição", "Olimpia": "Olímpia",
    "Saude": "Saúde", "Paraiso": "Paraíso", "Chacara": "Chácara", "Agua": "Água", "Gloria": "Glória",
    "Angela": "Ângela", "Grajau": "Grajaú", "Cupece": "Cupecê", "Indianopolis": "Indianópolis",
    "Americanopolis": "Americanópolis", "Inacio": "Inácio", "Moncoes": "Monções", "Climaco": "Clímaco",
    "Mirandopolis": "Mirandópolis", "Antonio": "Antônio", "Lucia": "Lúcia", "Bras": "Brás",
    "Sebastiao": "Sebastião", "Petropolis": "Petrópolis", "Pedreira": "Pedreira",
    "Sacoma": "Sacomã", "Heliopolis": "Heliópolis", "Bonifacio": "Bonifácio",
    "Patricia": "Patrícia", "Vitoria": "Vitória", "Iguacu": "Iguaçu", "Socorro": "Socorro",
}
PREPOSICOES = {"De": "de", "Da": "da", "Do": "do", "Dos": "dos", "Das": "das", "E": "e"}


def normalizar(s: pd.Series) -> pd.Series:
    s = s.fillna("").map(lambda x: unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode())
    s = s.str.upper().str.replace(r"[^A-Z0-9 ]", " ", regex=True)
    s = s.str.replace(r"\b(VL|V)\b", "VILA", regex=True)
    s = s.str.replace(r"\b(JD|JDM)\b", "JARDIM", regex=True)
    s = s.str.replace(r"\bPQ\b", "PARQUE", regex=True)
    s = s.str.replace(r"\bCID\b", "CIDADE", regex=True)
    s = s.str.replace(r"\b(Z|ZONA|ZN) SUL\b", " ", regex=True)  # "VILA GUARANI Z SUL" -> "VILA GUARANI"
    return s.str.replace(r"\s+", " ", regex=True).str.strip()


def nome_bairro(norm: str) -> str:
    if not norm or norm.replace(" ", "").isdigit():  # vazio ou só números (erro de cadastro)
        return "Não informado"
    palavras = [PREPOSICOES.get(p, ACENTOS.get(p, p)) for p in norm.title().split()]
    palavras[0] = palavras[0][:1].upper() + palavras[0][1:]
    return " ".join(palavras)


def main() -> None:
    (RAIZ / "dados").mkdir(exist_ok=True)
    (RAIZ / "powerbi").mkdir(exist_ok=True)
    q = {}

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    q["registros_estado"] = con.execute("select count(*) from estabelecimentos").fetchone()[0]
    df = pd.read_sql("select cnpj, nome_fantasia, cnae, bairro, cep, data_situacao "
                     "from estabelecimentos where municipio = 'SAO PAULO'", con, dtype=str)
    q["registros_municipio"] = len(df)

    # 1. Duplicidades e códigos
    q["cnpj_duplicados_removidos"] = int(df["cnpj"].duplicated().sum())
    df = df.drop_duplicates("cnpj")
    sem_catalogo = set(df["cnae"]) - set(CATALOGO)
    if sem_catalogo:
        sys.exit(f"CNAE sem descrição no catálogo: {sorted(sem_catalogo)}")
    q["atividades_cnae"] = df["cnae"].nunique()

    # 2. Datas
    df["data"] = pd.to_datetime(df["data_situacao"], format="%Y%m%d", errors="coerce")
    q["datas_invalidas"] = int(df["data"].isna().sum())
    referencia = df["data"].max().normalize()
    q["data_referencia"] = referencia.strftime("%Y-%m-%d")
    ini12 = referencia - pd.DateOffset(months=12)
    ini24 = referencia - pd.DateOffset(months=24)
    df["recente_12m"] = df["data"] > ini12
    df["anterior_12m"] = (df["data"] > ini24) & (df["data"] <= ini12)

    # 3. Textos e máscaras
    df["nome_fantasia"] = df["nome_fantasia"].fillna("").str.strip()
    q["sem_nome_fantasia_pct"] = round(100 * (df["nome_fantasia"] == "").mean(), 1)
    q["cep_invalido"] = int((~df["cep"].fillna("").str.fullmatch(r"\d{8}")).sum())
    df["bairro_norm"] = normalizar(df["bairro"])
    q["bairro_vazio"] = int((df["bairro_norm"].str.replace(" ", "").str.fullmatch(r"\d*")).sum())

    # 4. Área de atuação: bairros da região da Vila Olímpia (pelo nome) + Zona Sul (CEP 04)
    achado = df["bairro_norm"].str.extract(r"\b(VILA OLIMPIA|ITAIM BIBI|VILA NOVA CONCEI\w*)\b")[0]
    achado = achado.where(~achado.fillna("").str.startswith("VILA NOVA CONCEI"), "VILA NOVA CONCEICAO")
    vo = achado.notna()
    zs = df["cep"].str.startswith("04")
    q["grafias_bairro_vila_olimpia"] = int(df.loc[vo, "bairro"].str.strip().str.upper().nunique())
    q["registros_vila_olimpia"] = int(vo.sum())
    q["registros_zona_sul"] = int((zs & ~vo).sum())

    nomes = {b: nome_bairro(b) for b in df.loc[vo | zs, "bairro_norm"].unique()}
    area = df[vo | zs].copy()
    area["bairro"] = achado[vo | zs].map(BAIRROS_VO).fillna(area["bairro_norm"].map(nomes))
    area["regiao"] = vo[vo | zs].map({True: REGIAO_VO, False: REGIAO_ZS})
    q["bairros_distintos_area"] = int(area["bairro"].nunique())

    def montar(d: pd.DataFrame) -> pd.DataFrame:
        c, cn = d["cnpj"], d["cnae"]
        return pd.DataFrame({
            "cnpj": c.str[:2] + "." + c.str[2:5] + "." + c.str[5:8] + "/" + c.str[8:12] + "-" + c.str[12:14],
            "nome_fantasia": d["nome_fantasia"],
            "matriz_filial": (c.str[8:12] == "0001").map({True: "Matriz", False: "Filial"}),
            "cnae_cod": cn,
            "cnae": cn.str[:4] + "-" + cn.str[4] + "/" + cn.str[5:7],
            "atividade": cn.map(lambda x: CATALOGO[x][0]),
            "atividade_resumo": cn.map(lambda x: NOME_CURTO.get(x, CATALOGO[x][0])),
            "segmento": cn.map(lambda x: CATALOGO[x][1]),
            "data_inicio": d["data"],
            "ano": d["data"].dt.year.astype("Int64"),
            "bairro": d["bairro"],
            "cep": d["cep"].str[:5] + "-" + d["cep"].str[5:8],
            "regiao": d["regiao"],
            "recente_12m": d["recente_12m"],
            "anterior_12m": d["anterior_12m"],
            "concorrente": cn == "6920601",
        })

    emp = montar(area).sort_values(["regiao", "bairro", "segmento", "atividade"]).reset_index(drop=True)
    emp.to_parquet(RAIZ / "dados" / "empresas.parquet", index=False)

    # 5. Comparação com o município (matrizes ativas por atividade)
    mat = df[df["cnpj"].str[8:12] == "0001"]
    cidade = mat.groupby("cnae").agg(ativas_cidade=("cnpj", "size"),
                                     novas_cidade=("recente_12m", "sum"),
                                     anteriores_cidade=("anterior_12m", "sum")).reset_index()
    cidade = cidade.rename(columns={"cnae": "cnae_cod"})
    cidade.to_parquet(RAIZ / "dados" / "cidade_cnae.parquet", index=False)

    q["matrizes_pct"] = round(100 * (emp["matriz_filial"] == "Matriz").mean(), 1)
    q["concorrentes_vila_olimpia"] = int((emp["concorrente"] & (emp["regiao"] == REGIAO_VO)).sum())
    q["concorrentes_zona_sul"] = int(emp["concorrente"].sum())
    q["fonte"] = ("Dados Abertos do CNPJ (Receita Federal), referência 2026-09, estabelecimentos "
                  "ativos de 71 atividades, cópia processada pelo projeto Caça-Cliente "
                  "(github.com/d1g4odev/caca-cliente-downloads)")
    (RAIZ / "dados" / "qualidade.json").write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6. Tabelas do Power BI
    pb = RAIZ / "powerbi"
    opt = dict(sep=";", index=False, encoding="utf-8-sig", decimal=",")
    fato = emp.copy()
    for c in ["recente_12m", "anterior_12m", "concorrente"]:
        fato[c] = fato[c].astype(int)
    fato["data_inicio"] = fato["data_inicio"].dt.strftime("%Y-%m-%d")
    fato.to_csv(pb / "fato_empresas.csv", **opt)

    dim = pd.DataFrame([(k, v[0], NOME_CURTO.get(k, v[0]), v[1]) for k, v in CATALOGO.items()],
                       columns=["cnae_cod", "atividade", "atividade_resumo", "segmento"]).merge(cidade, on="cnae_cod", how="left")
    dim.insert(1, "cnae", dim["cnae_cod"].str[:4] + "-" + dim["cnae_cod"].str[4] + "/" + dim["cnae_cod"].str[5:7])
    dim.to_csv(pb / "dim_atividade.csv", **opt)

    linhas = []
    for nome_area, filtro in [(REGIAO_VO, emp["regiao"] == REGIAO_VO), ("Zona Sul (inteira)", emp["regiao"].notna())]:
        r = oportunidades(emp[filtro], cidade)
        r.insert(0, "area", nome_area)
        linhas.append(r)
    ops = pd.concat(linhas, ignore_index=True)
    ops["crescimento"] = ops["crescimento"].round(3)
    ops["especializacao"] = ops["especializacao"].round(3)
    ops["indice"] = ops["indice"].round(1)
    ops.to_csv(pb / "oportunidades.csv", **opt)

    print(json.dumps(q, ensure_ascii=False, indent=2))
    print(f"empresas.parquet: {len(emp):,} linhas | oportunidades: {len(ops)} linhas | pesos {PESOS_PADRAO}")


if __name__ == "__main__":
    main()
