/**
 * Chat de IA embutido na planilha - permite perguntar sobre os dados
 * coletados (aba "Histórico Completo") diretamente pela interface do
 * Google Sheets, sem precisar do script Python rodando.
 *
 * COMO INSTALAR:
 * 1. Na planilha, abra Extensões > Apps Script.
 * 2. Apague o conteúdo do arquivo "Código.gs" (ou Code.gs) e cole este arquivo.
 * 3. Crie um novo arquivo HTML (ícone "+" > HTML), nomeie "Sidebar", e cole
 *    o conteúdo de apps_script/Sidebar.html.
 * 4. Na barra de funções do editor (acima do código), escolha a função
 *    "configurarChave" e clique em "Executar" uma vez - vai pedir
 *    permissão, autorize. Isso vai abrir um prompt pedindo sua chave da
 *    Anthropic (sk-ant-...) e guardá-la de forma segura (Script Properties,
 *    não fica visível em nenhuma célula da planilha).
 * 5. Volte pra planilha e recarregue a página (F5). Vai aparecer um novo
 *    menu "🤖 Assistente IA" > "Abrir chat".
 */

const NOME_ABA_HISTORICO = 'Histórico Completo';
const NOME_ABA_ANALISE = 'Análise IA';
const MODELO_CLAUDE = 'claude-haiku-4-5';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🤖 Assistente IA')
    .addItem('Abrir chat', 'abrirChat')
    .addItem('Configurar chave da Anthropic', 'configurarChave')
    .addToUi();
}

function abrirChat() {
  const html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setTitle('Assistente IA - Anúncios');
  SpreadsheetApp.getUi().showSidebar(html);
}

/** Roda uma vez, manualmente, pra guardar a chave da Anthropic com segurança. */
function configurarChave() {
  const ui = SpreadsheetApp.getUi();
  const resposta = ui.prompt(
    'Configurar chave da Anthropic',
    'Cole aqui sua ANTHROPIC_API_KEY (sk-ant-...):',
    ui.ButtonSet.OK_CANCEL
  );

  if (resposta.getSelectedButton() !== ui.Button.OK) return;

  const chave = resposta.getResponseText().trim();
  if (!chave) {
    ui.alert('Nenhuma chave informada.');
    return;
  }

  PropertiesService.getScriptProperties().setProperty('ANTHROPIC_API_KEY', chave);
  ui.alert('Chave salva com sucesso.');
}

/** Lê a aba de histórico e monta um texto compacto (uma linha por registro). */
function _montarContextoHistorico() {
  const planilha = SpreadsheetApp.getActiveSpreadsheet();
  const abaHistorico = planilha.getSheetByName(NOME_ABA_HISTORICO);

  if (!abaHistorico) {
    return 'Nenhum histórico disponível ainda - rode "python main.py publicar_historico" no projeto.';
  }

  const valores = abaHistorico.getDataRange().getValues();
  // valores[0] é o cabeçalho: Data, Anúncio, SKU/ID, Visitas, Vendas, Receita (R$)
  const linhas = valores.slice(1).map(function (linha) {
    return linha.join(' | ');
  });

  return 'Cabeçalho: ' + valores[0].join(' | ') + '\n' + linhas.join('\n');
}

/** Lê a última análise em texto gerada pela IA (aba "Análise IA"), se existir. */
function _obterUltimaAnalise() {
  const planilha = SpreadsheetApp.getActiveSpreadsheet();
  const abaAnalise = planilha.getSheetByName(NOME_ABA_ANALISE);
  if (!abaAnalise) return '';

  const valores = abaAnalise.getDataRange().getValues();
  return valores.map(function (linha) { return linha.join(' '); }).join('\n');
}

/**
 * Função chamada pela barra lateral (Sidebar.html) via google.script.run.
 * Recebe a pergunta do usuário, monta o contexto com os dados da planilha,
 * chama a API da Anthropic via HTTP puro (Apps Script não suporta o SDK
 * oficial em JavaScript/npm) e retorna a resposta em texto.
 */
function perguntarIA(pergunta) {
  const apiKey = PropertiesService.getScriptProperties().getProperty('ANTHROPIC_API_KEY');
  if (!apiKey) {
    return 'Chave da Anthropic não configurada. Rode o menu "🤖 Assistente IA" > "Configurar chave da Anthropic" primeiro.';
  }

  const contextoHistorico = _montarContextoHistorico();
  const ultimaAnalise = _obterUltimaAnalise();

  const systemPrompt =
    'Você é um assistente que responde perguntas sobre o desempenho de anúncios ' +
    'de um vendedor no Mercado Livre, com base nos dados fornecidos (histórico ' +
    'diário de visitas, vendas e receita por anúncio). Responda em português, ' +
    'de forma direta e objetiva, citando números quando fizer sentido. Se a ' +
    'pergunta não puder ser respondida com os dados disponíveis, diga isso ' +
    'claramente em vez de inventar números.';

  const mensagemUsuario =
    'DADOS HISTÓRICOS (uma linha por dia/anúncio):\n' + contextoHistorico +
    (ultimaAnalise ? ('\n\nÚLTIMA ANÁLISE GERADA:\n' + ultimaAnalise) : '') +
    '\n\nPERGUNTA: ' + pergunta;

  const payload = {
    model: MODELO_CLAUDE,
    max_tokens: 1024,
    system: systemPrompt,
    messages: [{ role: 'user', content: mensagemUsuario }],
  };

  const opcoes = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };

  const resposta = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', opcoes);
  const corpo = JSON.parse(resposta.getContentText());

  if (corpo.error) {
    return 'Erro da API da Anthropic: ' + corpo.error.message;
  }

  const blocoTexto = corpo.content.find(function (bloco) { return bloco.type === 'text'; });
  return blocoTexto ? blocoTexto.text : 'A IA não retornou texto.';
}
