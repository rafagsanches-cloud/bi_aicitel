"""
Preparação dos dados do painel de inteligência de mercado da Aicitel.

Fontes aceitas
  receita  arquivos oficiais dos Dados Abertos do CNPJ (Receita Federal), baixados do
           WebDAV público da Receita (padrão). Traz porte, Simples Nacional e MEI.
  sqlite   cópia SP.db publicada pelo projeto Caça-Cliente (referência 2026-09), sem
           porte, Simples Nacional e MEI. Mantida como alternativa.

Saídas
  dados/empresas.parquet      estabelecimentos da área de atuação (painel Streamlit)
  dados/cidade_cnae.parquet   totais do município por atividade (comparação)
  dados/qualidade.json        relatório de limpeza e qualidade
  powerbi/*.csv               tabelas do modelo do Power BI (opção --powerbi)

Etapas: filtragem do município, tratamento de datas, padronização de bairros
(grafias como "VL. OLIMPIA" e "V NOVA CONCEICAO"), máscaras de CNPJ/CEP/CNAE,
classificação das atividades em segmentos, delimitação da área de atuação,
cálculo das janelas de 12 meses e, na fonte oficial, junção do porte e da
opção pelo Simples Nacional e pelo MEI.

Uso
  python preparar_dados.py                          # baixa o mês mais recente da Receita
  python preparar_dados.py --mes 2026-09            # escolhe o mês
  python preparar_dados.py --pasta-zips C:\\cnpj     # usa zips já baixados
  python preparar_dados.py --fonte sqlite dados_brutos/SP.db
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sqlite3
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from indicadores import PESOS_PADRAO, oportunidades

RAIZ = Path(__file__).parent
WEBDAV = "https://arquivos.receitafederal.gov.br/public.php/webdav"
TOKEN_PUBLICO = "YggdBLfdninEJX9"  # chave pública do compartilhamento da Receita (usuário, senha vazia)

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


PORTE = {"00": "Não informado", "01": "ME", "03": "EPP", "05": "Demais"}
REGIMES = ["MEI", "Simples Nacional (exceto MEI)", "Fora do Simples"]

COLS_ESTAB = [
    "cnpj_basico", "cnpj_ordem", "cnpj_dv", "matriz_filial", "nome_fantasia", "situacao",
    "data_situacao", "motivo", "cidade_exterior", "pais", "data_inicio", "cnae", "cnae_secundaria",
    "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep", "uf", "municipio",
    "ddd1", "tel1", "ddd2", "tel2", "ddd_fax", "fax", "email", "sit_especial", "data_sit_especial",
]
USE_ESTAB = ["cnpj_basico", "cnpj_ordem", "cnpj_dv", "nome_fantasia", "situacao", "data_inicio",
             "cnae", "bairro", "cep", "uf", "municipio"]
COLS_EMP = ["cnpj_basico", "razao_social", "natureza", "qualificacao", "capital_social", "porte", "ente"]
COLS_SIMPLES = ["cnpj_basico", "opcao_simples", "data_opcao_simples", "data_exclusao_simples",
                "opcao_mei", "data_opcao_mei", "data_exclusao_mei"]
LEITURA = dict(sep=";", header=None, dtype=str, encoding="cp1252", encoding_errors="replace",
               keep_default_na=False, na_values=[""], on_bad_lines="warn")
BLOCO = 500_000


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Download dos arquivos oficiais (WebDAV público da Receita Federal)
# ---------------------------------------------------------------------------
def _cabecalho() -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{TOKEN_PUBLICO}:".encode()).decode()}


def listar_webdav(caminho: str = "") -> list[tuple[str, int | None]]:
    import requests
    from urllib.parse import unquote
    r = requests.request("PROPFIND", f"{WEBDAV}/{caminho}", timeout=120,
                         headers={**_cabecalho(), "Depth": "1"})
    r.raise_for_status()
    itens = []
    for resp in ET.fromstring(r.content).findall("{DAV:}response"):
        nome = unquote(resp.findtext("{DAV:}href", "").rstrip("/").split("/")[-1])
        tam = resp.findtext(".//{DAV:}getcontentlength")
        itens.append((nome, int(tam) if tam else None))
    return itens


def mes_mais_recente() -> str:
    meses = sorted(n for n, _ in listar_webdav() if re.fullmatch(r"\d{4}-\d{2}", n))
    if not meses:
        sys.exit("Nenhuma pasta AAAA-MM encontrada no WebDAV da Receita.")
    return meses[-1]


def baixar(mes: str, nome: str, destino: Path, tamanho: int | None, tentativas: int = 6) -> Path:
    import requests
    arq = destino / nome
    if arq.exists() and tamanho and arq.stat().st_size == tamanho:
        return arq
    parcial = arq.with_suffix(".part")
    for t in range(1, tentativas + 1):
        try:
            ja = parcial.stat().st_size if parcial.exists() else 0
            cab = {**_cabecalho(), **({"Range": f"bytes={ja}-"} if ja else {})}
            with requests.get(f"{WEBDAV}/{mes}/{nome}", headers=cab, stream=True, timeout=180) as r:
                if r.status_code == 200:
                    ja = 0
                r.raise_for_status()
                with open(parcial, "ab" if ja else "wb") as f:
                    for pedaco in r.iter_content(4 << 20):
                        f.write(pedaco)
            if tamanho and parcial.stat().st_size != tamanho:
                raise IOError(f"tamanho {parcial.stat().st_size} diferente do esperado {tamanho}")
            with open(parcial, "rb") as f:
                if f.read(2) != b"PK":
                    raise IOError("o arquivo baixado não é um zip")
            parcial.replace(arq)
            log(f"  baixado {nome} ({arq.stat().st_size / 1e6:,.0f} MB)")
            return arq
        except Exception as e:  # noqa: BLE001
            log(f"  falha em {nome}: {e} (tentativa {t}/{tentativas})")
            time.sleep(min(60, 10 * t))
    sys.exit(f"Não foi possível baixar {nome}.")


class Arquivos:
    """Entrega os zips de um tipo, baixando sob demanda e apagando depois de usados."""

    def __init__(self, mes: str | None, pasta_zips: str | None, manter: bool):
        self.local = Path(pasta_zips) if pasta_zips else None
        self.manter = manter or bool(pasta_zips)
        if self.local:
            self.mes = mes or "local"
            self.remotos = {}
        else:
            self.mes = mes or mes_mais_recente()
            self.remotos = {n: t for n, t in listar_webdav(self.mes + "/") if n.lower().endswith(".zip")}
            self.destino = RAIZ / "dados_brutos" / self.mes
            self.destino.mkdir(parents=True, exist_ok=True)
        log(f"Base da Receita: {self.mes}")

    def __call__(self, padrao: str):
        if self.local:
            nomes = sorted(p.name for p in self.local.iterdir() if re.fullmatch(padrao, p.name, re.I))
        else:
            nomes = sorted(n for n in self.remotos if re.fullmatch(padrao, n, re.I))
        if not nomes:
            sys.exit(f"Nenhum arquivo '{padrao}' na base {self.mes}.")
        for nome in nomes:
            arq = self.local / nome if self.local else baixar(self.mes, nome, self.destino, self.remotos[nome])
            yield arq
            if not self.manter:
                arq.unlink(missing_ok=True)


def carregar_receita(args) -> tuple[pd.DataFrame, pd.DataFrame, dict, str]:
    arquivos = Arquivos(args.mes, args.pasta_zips, args.manter_zips)
    q = {"base_receita": arquivos.mes}

    cod_sp = {"7107"}
    for zp in arquivos(r"Municipios\.zip"):
        mun = pd.read_csv(zp, names=["cod", "nome"], **LEITURA)
        cod_sp = set(mun.loc[mun["nome"].str.strip().str.upper() == "SAO PAULO", "cod"]) or cod_sp

    # 1. Estabelecimentos ativos das 71 atividades no município de São Paulo
    partes, n_estado = [], 0
    for zp in arquivos(r"Estabelecimentos\d\.zip"):
        log(f"Lendo {zp.name}")
        for ch in pd.read_csv(zp, names=COLS_ESTAB, usecols=USE_ESTAB, chunksize=BLOCO, **LEITURA):
            ch = ch[(ch["uf"] == "SP") & (ch["situacao"] == "02") & ch["cnae"].isin(CATALOGO)]
            n_estado += len(ch)
            ch = ch[ch["municipio"].isin(cod_sp)]
            if not ch.empty:
                partes.append(ch)
    df = pd.concat(partes, ignore_index=True)
    df["cnpj"] = df["cnpj_basico"] + df["cnpj_ordem"] + df["cnpj_dv"]
    df["data"] = pd.to_datetime(df["data_inicio"].where(~df["data_inicio"].isin(["0", "00000000"])),
                                format="%Y%m%d", errors="coerce")
    q["registros_estado"] = int(n_estado)
    log(f"  {len(df):,} estabelecimentos ativos no município ({n_estado:,} no estado)")

    # 2. Porte (tabela Empresas) e opção pelo Simples Nacional e pelo MEI (tabela Simples)
    basicos = set(df["cnpj_basico"])
    blocos = []
    for zp in arquivos(r"Empresas\d\.zip"):
        log(f"Lendo {zp.name}")
        for ch in pd.read_csv(zp, names=COLS_EMP, usecols=["cnpj_basico", "porte"], chunksize=BLOCO, **LEITURA):
            blocos.append(ch[ch["cnpj_basico"].isin(basicos)])
    emp = pd.concat(blocos, ignore_index=True).drop_duplicates("cnpj_basico")

    blocos = []
    for zp in arquivos(r"Simples\.zip"):
        log(f"Lendo {zp.name}")
        for ch in pd.read_csv(zp, names=COLS_SIMPLES, usecols=["cnpj_basico", "opcao_simples", "opcao_mei"],
                              chunksize=2 * BLOCO, **LEITURA):
            blocos.append(ch[ch["cnpj_basico"].isin(basicos)])
    sim = pd.concat(blocos, ignore_index=True).drop_duplicates("cnpj_basico")

    extras = emp.merge(sim, on="cnpj_basico", how="outer").set_index("cnpj_basico")
    fonte = (f"Dados Abertos do CNPJ (Receita Federal), base {arquivos.mes}, arquivos oficiais "
             "baixados do repositório público da Receita; estabelecimentos ativos de 71 atividades")
    return df[["cnpj", "nome_fantasia", "cnae", "bairro", "cep", "data"]], extras, q, fonte


def carregar_sqlite(caminho: str) -> tuple[pd.DataFrame, None, dict, str]:
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    q = {"registros_estado": con.execute("select count(*) from estabelecimentos").fetchone()[0]}
    df = pd.read_sql("select cnpj, nome_fantasia, cnae, bairro, cep, data_situacao "
                     "from estabelecimentos where municipio = 'SAO PAULO'", con, dtype=str)
    df["data"] = pd.to_datetime(df["data_situacao"], format="%Y%m%d", errors="coerce")
    fonte = ("Dados Abertos do CNPJ (Receita Federal), referência 2026-09, estabelecimentos "
             "ativos de 71 atividades, cópia processada pelo projeto Caça-Cliente "
             "(github.com/d1g4odev/caca-cliente-downloads)")
    return df[["cnpj", "nome_fantasia", "cnae", "bairro", "cep", "data"]], None, q, fonte


# ---------------------------------------------------------------------------
# Tratamento comum às duas fontes
# ---------------------------------------------------------------------------
def processar(df: pd.DataFrame, extras: pd.DataFrame | None, q: dict, fonte: str, powerbi: bool) -> None:
    (RAIZ / "dados").mkdir(exist_ok=True)
    q["registros_municipio"] = len(df)

    # 1. Duplicidades e códigos
    q["cnpj_duplicados_removidos"] = int(df["cnpj"].duplicated().sum())
    df = df.drop_duplicates("cnpj").copy()
    sem_catalogo = set(df["cnae"]) - set(CATALOGO)
    if sem_catalogo:
        sys.exit(f"CNAE sem descrição no catálogo: {sorted(sem_catalogo)}")
    q["atividades_cnae"] = df["cnae"].nunique()

    # 2. Datas (a referência é a data mais recente da base, nunca posterior a hoje)
    q["datas_invalidas"] = int(df["data"].isna().sum())
    hoje = pd.Timestamp.today().normalize()
    referencia = min(df.loc[df["data"] <= hoje, "data"].max().normalize(), hoje)
    q["data_referencia"] = referencia.strftime("%Y-%m-%d")
    ini12 = referencia - pd.DateOffset(months=12)
    ini24 = referencia - pd.DateOffset(months=24)
    df["recente_12m"] = (df["data"] > ini12) & (df["data"] <= referencia)
    df["anterior_12m"] = (df["data"] > ini24) & (df["data"] <= ini12)

    # 3. Textos e máscaras
    df["nome_fantasia"] = df["nome_fantasia"].fillna("").str.strip()
    q["sem_nome_fantasia_pct"] = round(100 * (df["nome_fantasia"] == "").mean(), 1)
    df["cep"] = df["cep"].fillna("")
    q["cep_invalido"] = int((~df["cep"].str.fullmatch(r"\d{8}")).sum())
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

    c, cn = area["cnpj"], area["cnae"]
    emp = pd.DataFrame({
        "cnpj": c.str[:2] + "." + c.str[2:5] + "." + c.str[5:8] + "/" + c.str[8:12] + "-" + c.str[12:14],
        "nome_fantasia": area["nome_fantasia"],
        "matriz_filial": (c.str[8:12] == "0001").map({True: "Matriz", False: "Filial"}),
        "cnae_cod": cn,
        "cnae": cn.str[:4] + "-" + cn.str[4] + "/" + cn.str[5:7],
        "atividade": cn.map(lambda x: CATALOGO[x][0]),
        "atividade_resumo": cn.map(lambda x: NOME_CURTO.get(x, CATALOGO[x][0])),
        "segmento": cn.map(lambda x: CATALOGO[x][1]),
        "data_inicio": area["data"],
        "ano": area["data"].dt.year.astype("Int64"),
        "bairro": area["bairro"],
        "cep": area["cep"].str[:5] + "-" + area["cep"].str[5:8],
        "regiao": area["regiao"],
        "recente_12m": area["recente_12m"],
        "anterior_12m": area["anterior_12m"],
        "concorrente": cn == "6920601",
    })

    # 5. Porte, Simples Nacional e MEI (somente na fonte oficial)
    if extras is not None:
        ex = extras.reindex(c.str[:8].values)
        mei = ex["opcao_mei"].fillna("N").eq("S").values
        simples = ex["opcao_simples"].fillna("N").eq("S").values
        emp["porte"] = pd.Series(ex["porte"].map(PORTE).fillna("Não informado").values, index=emp.index)
        emp["simples"] = pd.Series(simples, index=emp.index).map({True: "Sim", False: "Não"})
        emp["mei"] = pd.Series(mei, index=emp.index).map({True: "Sim", False: "Não"})
        emp["regime"] = pd.Series(
            ["MEI" if m else ("Simples Nacional (exceto MEI)" if s else "Fora do Simples")
             for m, s in zip(mei, simples)], index=emp.index)
        m = emp[(emp["matriz_filial"] == "Matriz") & ~emp["concorrente"]]
        q["mei_pct"] = round(100 * (m["regime"] == "MEI").mean(), 1)
        q["simples_exceto_mei_pct"] = round(100 * (m["regime"] == REGIMES[1]).mean(), 1)
        q["fora_simples_pct"] = round(100 * (m["regime"] == REGIMES[2]).mean(), 1)

    emp = emp.sort_values(["regiao", "bairro", "segmento", "atividade"]).reset_index(drop=True)
    emp.to_parquet(RAIZ / "dados" / "empresas.parquet", index=False)

    # 6. Comparação com o município (matrizes ativas por atividade)
    mat = df[df["cnpj"].str[8:12] == "0001"]
    cidade = (mat.groupby("cnae").agg(ativas_cidade=("cnpj", "size"), novas_cidade=("recente_12m", "sum"),
                                      anteriores_cidade=("anterior_12m", "sum"))
              .reset_index().rename(columns={"cnae": "cnae_cod"}))
    cidade.to_parquet(RAIZ / "dados" / "cidade_cnae.parquet", index=False)

    q["matrizes_pct"] = round(100 * (emp["matriz_filial"] == "Matriz").mean(), 1)
    q["concorrentes_vila_olimpia"] = int((emp["concorrente"] & (emp["regiao"] == REGIAO_VO)).sum())
    q["concorrentes_zona_sul"] = int(emp["concorrente"].sum())
    q["fonte"] = fonte
    q["atualizado_em"] = pd.Timestamp.today().strftime("%Y-%m-%d")
    (RAIZ / "dados" / "qualidade.json").write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")

    if powerbi:
        gerar_powerbi(emp, cidade)
    print(json.dumps(q, ensure_ascii=False, indent=2))
    log(f"empresas.parquet: {len(emp):,} linhas")


def gerar_powerbi(emp: pd.DataFrame, cidade: pd.DataFrame) -> None:
    pb = RAIZ / "powerbi"
    pb.mkdir(exist_ok=True)
    opt = dict(sep=";", index=False, encoding="utf-8-sig", decimal=",")
    fato = emp.copy()
    for col in ["recente_12m", "anterior_12m", "concorrente"]:
        fato[col] = fato[col].astype(int)
    fato["data_inicio"] = fato["data_inicio"].dt.strftime("%Y-%m-%d")
    fato.to_csv(pb / "fato_empresas.csv", **opt)

    dim = pd.DataFrame([(k, v[0], NOME_CURTO.get(k, v[0]), v[1]) for k, v in CATALOGO.items()],
                       columns=["cnae_cod", "atividade", "atividade_resumo", "segmento"])
    dim = dim.merge(cidade, on="cnae_cod", how="left")
    dim.insert(1, "cnae", dim["cnae_cod"].str[:4] + "-" + dim["cnae_cod"].str[4] + "/" + dim["cnae_cod"].str[5:7])
    dim.to_csv(pb / "dim_atividade.csv", **opt)

    linhas = []
    for nome_area, filtro in [(REGIAO_VO, emp["regiao"] == REGIAO_VO), ("Zona Sul (inteira)", emp["regiao"].notna())]:
        r = oportunidades(emp[filtro], cidade)
        r.insert(0, "area", nome_area)
        linhas.append(r)
    ops = pd.concat(linhas, ignore_index=True)
    for col, casas in [("crescimento", 3), ("especializacao", 3), ("indice", 1)]:
        ops[col] = ops[col].round(casas)
    ops.to_csv(pb / "oportunidades.csv", **opt)
    log(f"Tabelas do Power BI gravadas em {pb} (pesos {PESOS_PADRAO})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepara os dados do painel da Aicitel")
    ap.add_argument("--fonte", choices=["receita", "sqlite"], default="receita")
    ap.add_argument("caminho_sqlite", nargs="?", default=str(RAIZ / "dados_brutos" / "SP.db"),
                    help="caminho do SP.db (só para --fonte sqlite)")
    ap.add_argument("--mes", help="base da Receita no formato AAAA-MM (padrão: a mais recente)")
    ap.add_argument("--pasta-zips", help="pasta com os zips da Receita já baixados")
    ap.add_argument("--manter-zips", action="store_true", help="não apaga os zips baixados")
    ap.add_argument("--powerbi", action="store_true", help="gera também os CSVs do Power BI")
    ap.add_argument("--so-se-houver-base-nova", action="store_true",
                    help="encerra sem fazer nada se a base mais recente da Receita já estiver no painel")
    args = ap.parse_args()

    if args.fonte == "receita" and args.so_se_houver_base_nova and not args.pasta_zips:
        atual = RAIZ / "dados" / "qualidade.json"
        base_atual = json.loads(atual.read_text(encoding="utf-8")).get("base_receita") if atual.exists() else None
        args.mes = args.mes or mes_mais_recente()
        if base_atual == args.mes:
            log(f"A base {args.mes} já está no painel. Nada a atualizar.")
            return

    if args.fonte == "receita":
        df, extras, q, fonte = carregar_receita(args)
    else:
        df, extras, q, fonte = carregar_sqlite(args.caminho_sqlite)
    processar(df, extras, q, fonte, args.powerbi)


if __name__ == "__main__":
    main()
