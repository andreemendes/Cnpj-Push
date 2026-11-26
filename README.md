# Empresas novas em SC — mapa + notificação no celular

Todo mês a Receita Federal publica a lista de todos os CNPJs do Brasil. Este projeto:

1. confere **todo dia** se saiu lista nova;
2. quando sai, baixa a lista, separa as empresas **ativas de Santa Catarina** e compara com o que já tinha visto;
3. coloca tudo num **mapa do Brasil** (passe o mouse num estado, clique para aproximar, clique nas bolinhas para ver os dados);
4. manda **notificação no seu Android** com cada empresa nova (10 por dia, para você ir abordando aos poucos) e um aviso geral quando chega lote novo.

Tudo roda de graça no GitHub. Você não precisa deixar computador ligado.

---

## Passo a passo (uns 20 minutos, só uma vez)

### 1. Criar o repositório no GitHub
1. Crie uma conta em https://github.com (se ainda não tiver).
2. Clique em **New repository**. Nome: `cnpj-sc`. Marque **Public** (precisa ser público para o site grátis; os dados ficam protegidos por senha, veja abaixo). Crie.
3. Na página do repositório, clique em **uploading an existing file** e arraste **todo o conteúdo desta pasta** (`config.json`, `README.md`, as pastas `docs` e `scripts`). Clique em **Commit changes**.
4. A pasta `.github` às vezes não sobe arrastando (ela é "oculta"). Para garantir: **Add file → Create new file**, digite o nome `.github/workflows/atualizar.yml`, cole o conteúdo do arquivo `atualizar.yml` desta pasta e salve.

### 2. Guardar a senha do mapa e o canal de notificação
Em **Settings → Secrets and variables → Actions → New repository secret**, crie dois:

| Nome | Valor |
|---|---|
| `SENHA_MAPA` | uma senha que você vai digitar para abrir o mapa |
| `NTFY_TOPICO` | um nome difícil de adivinhar, ex.: `empresas-sc-k38fq2x9` |

> O nome do tópico funciona como senha das notificações: quem souber o nome recebe também. Não use algo óbvio.

### 3. Ligar o site
**Settings → Pages** → em *Branch* escolha `main` e a pasta `/docs` → **Save**.
Em 1 ou 2 minutos aparece o endereço, algo como `https://SEU-USUARIO.github.io/cnpj-sc/`.

Abra o `config.json` no GitHub (ícone de lápis) e troque `site_url` por esse endereço. É ele que a notificação abre quando você toca.

### 4. Instalar o app de notificação no Android
1. Instale o **ntfy** na Play Store.
2. Toque em **+**, digite o mesmo nome que você colocou em `NTFY_TOPICO` e assine.

### 5. Rodar a primeira vez
**Actions → Atualizar empresas → Run workflow**.
A primeira execução baixa vários GB da Receita e pode levar **de 1 a 3 horas**. No fim chega a notificação *"Mapa de empresas pronto"*.

A primeira carga é a "foto inicial": tudo que já existe entra no mapa sem gerar notificação individual. Daí pra frente, **só as empresas novas** geram notificação.

---

## Como funciona no dia a dia
- O robô roda todo dia às 8h17. Se a Receita não publicou mês novo, ele só manda as notificações do dia que estão na fila e termina em segundos.
- Quando sai mês novo (geralmente na primeira quinzena), chega um aviso tipo **"412 empresas novas em SC"**. As notificações individuais vão saindo **10 por dia**. Para mudar, edite `notificacoes_por_dia` no `config.json`.
- Tocar numa notificação abre o mapa já na bolinha daquela empresa.
- No mapa, **rosa** = novas desta atualização, **azul** = as anteriores. No balão de cada empresa dá para marcar a situação (contatei, virou cliente, descartei). Isso fica salvo no seu aparelho.
- O mapa mostra as empresas abertas nos últimos **60 dias**. Para mudar, edite `dias_no_mapa` no `config.json`. Mais dias deixam o mapa mais pesado no celular.

## Bom saber
- **Localização é aproximada.** A Receita não informa coordenadas, então a bolinha fica perto do centro da cidade. O endereço completo está no balão, e o botão *Ver no Google Maps* leva ao lugar certo.
- **A Receita atualiza uma vez por mês.** Uma empresa aberta hoje aparece no próximo lote.
- **Muitos CNPJs novos são MEI.** Use o filtro *Esconder MEI* se quiser focar em empresas maiores, e o filtro de ramo para pegar quem costuma precisar de site (restaurante, salão, clínica, academia...).
- **Privacidade e LGPD:** os dados são públicos, mas muitos telefones e e-mails de MEI são pessoais. Na abordagem, se apresente, seja direto e pare de contatar se a pessoa pedir. Por isso o mapa fica protegido por senha.

## Se algo der errado
- **"Nenhum mês encontrado" ou erro 401/404 ao listar:** a Receita mudou o endereço dos arquivos (já aconteceu em 2026). Abra https://arquivos.receitafederal.gov.br, navegue até *Dados → Cadastros → CNPJ*. O endereço da página terá `/index.php/s/ALGUMCODIGO`. Coloque esse código em `receita_share_token` no `config.json`.
- **Download muito lento ou travando:** o servidor da Receita às vezes fica lento. O script tenta 5 vezes. Se falhar, rode de novo pelo *Run workflow* no dia seguinte.
- **O GitHub desligou o agendamento:** o GitHub pausa agendamentos de repositórios sem atividade por 60 dias. Como o robô salva dados todo mês, isso não deve acontecer. Se acontecer, vá em *Actions* e clique em *Enable workflow*.
- **Esqueceu a senha do mapa:** troque o secret `SENHA_MAPA` e rode *Run workflow* marcando **Reprocessar**.

## Arquivos
| Arquivo | O que é |
|---|---|
| `docs/index.html` | o site do mapa |
| `docs/dados.bin` | os dados do mapa, criptografados com a sua senha (criado na 1ª execução) |
| `docs/dados.json` | dados **fictícios** de demonstração, apagados na 1ª execução |
| `scripts/atualizar.py` | baixa, filtra e compara os dados da Receita |
| `scripts/notificar.py` | manda as notificações do dia |
| `dados/` | memória do robô: quais CNPJs já viu e a fila de notificações |
| `config.json` | estado (`uf`), dias no mapa, notificações por dia, endereço do site |

Para testar no computador: `pip install requests cryptography` e depois `python scripts/atualizar.py --pasta-local PASTA_COM_ZIPS --mes 2026-11`.
