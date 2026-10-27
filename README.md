# Painel de Inteligência de Mercado - Aicitel

Projeto de Desenvolvimento de uma Solução de Business Intelligence, curso de Análise e Desenvolvimento de Sistemas (UNISAGRADO).

Organização: Aicitel - E Soares Assessoria Contábil LTDA, escritório de contabilidade na Vila Olímpia, São Paulo/SP.

## Problema

Um escritório pequeno de contabilidade precisa decidir onde e em quais nichos buscar clientes, mas não tem uma visão organizada do mercado à sua volta. O painel responde a três perguntas:

- Quais empresas existem na área de atuação do escritório?
- Quais segmentos estão crescendo?
- Quais perfis de empresa têm mais chance de precisar de serviço contábil?

A base de clientes do escritório não foi usada. Ela envolve sigilo profissional e dados protegidos pela LGPD, e a resposta às perguntas acima depende do mercado, não da carteira atual.

## Dados

Dados Abertos do CNPJ da Receita Federal, referência setembro de 2026 (registros até 13/09/2026). Como o servidor da Receita não estava acessível no ambiente de desenvolvimento, foi usada a cópia processada e publicada pelo projeto Caça-Cliente no GitHub (`github.com/d1g4odev/caca-cliente-downloads`, release `cnpj-data-2026-09`, arquivo `SP.db`).

Essa cópia tem limitações que afetam a análise. Ela traz só estabelecimentos ativos, então não é possível medir encerramentos. Cobre 71 atividades típicas de pequenos negócios, e não toda a economia. E não informa porte (ME/EPP), opção pelo Simples nem MEI. Por isso, a rotina de atualização mensal (abaixo) passou a usar os arquivos oficiais da Receita, que trazem essas três informações.

A área de atuação foi dividida em duas regiões. A primeira, "Vila Olímpia e entorno", reúne Vila Olímpia, Itaim Bibi e Vila Nova Conceição, identificados pelo nome do bairro. A segunda, "Demais bairros da Zona Sul", cobre os CEPs de 04000-000 a 04999-999.

## Tratamento

O script `preparar_dados.py` faz todo o pré-processamento:

1. Filtra o município de São Paulo (756.868 estabelecimentos) e remove CNPJs repetidos.
2. Converte as datas do formato AAAAMMDD; 2.835 datas inválidas ficam sem valor.
3. Padroniza os bairros. Retira acentos e pontuação, expande abreviações (VL, V, JD, PQ) e unifica grafias. Só a região da Vila Olímpia tinha 20 formas diferentes de escrever os três bairros.
4. Aplica máscaras de CNPJ, CEP e CNAE, inclui a descrição oficial de cada CNAE e agrupa as atividades em 15 segmentos.
5. Marca as empresas abertas nos últimos 12 meses e nos 12 meses anteriores, para medir crescimento.
6. Gera as tabelas do painel (`dados/`) e do Power BI (`powerbi/`).

## Análises

**Descritiva.** Empresas por segmento, por bairro e por mês de abertura.

**Diagnóstica.** Ritmo de aberturas de cada segmento comparado ao da área. A comparação é relativa porque a base só tem empresas ativas, e isso faz qualquer ano antigo parecer menor do que foi.

**Prescritiva.** Um índice de oportunidade de 0 a 100 por atividade, que combina quantidade de empresas, empresas abertas nos últimos 12 meses, crescimento acima da média e especialização da área (quociente locacional em relação ao município). O índice gera uma lista de prospecção com as empresas recém-abertas das atividades mais bem colocadas. Escritórios de contabilidade entram como concorrência, e o painel mostra quantas empresas existem por escritório em cada bairro.

## Estrutura

```
painel_aicitel/
├── app.py                  painel em Streamlit
├── indicadores.py          cálculo do índice de oportunidade
├── preparar_dados.py       limpeza e tratamento
├── requirements.txt
├── .streamlit/config.toml  tema do painel
├── dados/                  tabelas usadas pelo Streamlit
└── powerbi/                tabelas, consultas, medidas, tema e guia do Power BI
```

## Rodar no computador

```
pip install -r requirements.txt
streamlit run app.py
```

O painel abre no navegador em `http://localhost:8501`.

Para refazer o tratamento a partir da base bruta, baixe o `SP.db.gz` da release indicada acima, descompacte em `dados_brutos/SP.db` e rode `python preparar_dados.py`.

## Publicar no Streamlit Community Cloud

O serviço é gratuito e publica direto de um repositório do GitHub.

1. Crie um repositório público no GitHub e envie esta pasta. O `.gitignore` já deixa de fora a base bruta, que passa do limite de tamanho do GitHub.
2. Entre em `share.streamlit.io` com a conta do GitHub e clique em **Create app**.
3. Escolha o repositório, a branch `main` e o arquivo `app.py`. Em **App URL**, dá para escolher um endereço, como `aicitel-mercado.streamlit.app`.
4. Clique em **Deploy**. Em poucos minutos o painel fica no ar, com um link para entregar ao professor.

Apps gratuitos entram em repouso depois de alguns dias sem acesso. Quem abrir o link nesse período vê um botão para acordar o app, que volta em menos de um minuto.

## Atualização mensal automática

A rotina `.github/workflows/atualizar-dados.yml` roda no GitHub Actions nos dias 5 e 20 de cada mês. Ela consulta o repositório público da Receita Federal e, quando há uma base nova, baixa os arquivos oficiais (Estabelecimentos, Empresas e Simples), refaz o tratamento com `preparar_dados.py` e grava os dados novos na pasta `dados/`. O Streamlit Community Cloud percebe a mudança no repositório e atualiza o painel sozinho.

Com a base oficial, o painel passa a mostrar o porte de cada empresa e a opção pelo Simples Nacional e pelo MEI. A rotina pode ser disparada à mão em **Actions > Atualizar dados do painel > Run workflow**.

## Power BI

As instruções de montagem, conferência e publicação estão em `powerbi/GUIA_POWER_BI.md`.
