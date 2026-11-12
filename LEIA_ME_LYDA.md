# Lyda - Sistema de Mini-Etiquetas Zebra ZD230 (ZPL II Nativo)

Sistema desktop em Python (interface gráfica nativa) feito sob medida para a **Lyda** imprimir **várias mini-etiquetas com contorno de recorte e código de barras** dentro de uma etiqueta grande instalada na **Zebra ZD230**.

---

## Principais Funcionalidades

1. **Qualquer Tamanho de Etiqueta Grande e Grade de Mini-Etiquetas (Aba 2)**:
   - Configure a largura e altura exatas (em `mm`) do papel grande instalado na Zebra ZD230.
   - Defina quantas **colunas** e **linhas** de mini-etiquetas cabem dentro de cada etiqueta grande (ex: `2x5 = 10 mini-etiquetas`, `2x6 = 12`, `3x6 = 18`, etc.).
   - O sistema calcula automaticamente as dimensões de cada mini-etiqueta ou permite ajuste manual.
   - Desenha **contorno (borda preta)** ao redor de cada mini-etiqueta e **marcas guias de tesoura** nas extremidades para facilitar o corte antes de colar nos equipamentos.

2. **Leitura de Planilhas Excel (`.xlsx`, `.xls`) e `.csv` (Aba 1)**:
   - Carregue qualquer planilha de equipamentos.
   - Filtre, busque, selecione quais linhas deseja imprimir ou adicione itens avulsos na hora.
   - Defina quantas cópias de cada mini-etiqueta deseja gerar.

3. **Administração Total do que Escrever na Etiqueta (Aba 3)**:
   - Escolha qual coluna da planilha alimenta o **Código de Barras (`Code 128`)** ou **QR Code** para bipar com o leitor.
   - Configure até **5 linhas de texto extras** puxando de qualquer coluna da planilha (ex: `EQUIPAMENTO`, `PATRIMONIO`, `SETOR`, `RESPONSAVEL`, `DATA`) com prefixo livre (ex: `"PAT: "`, `"SETOR: "`), tamanho de fonte ajustável e negrito, ou textos fixos.
   - Cabeçalho fixo opcional no topo (ex: `LYDA`).

4. **Pré-Visualização em Tempo Real + Envio Direto ZPL Nativo (Aba 4 e Painel Direito)**:
   - Veja na tela exatamente como a etiqueta grande ficará dividida antes de gastar etiqueta física.
   - Envia **ZPL II puro em modo RAW** direto para a **Zebra ZD230** via USB no Windows (`WinSpool RAW`, sem perda de qualidade de driver gráfico, garantindo leitura imediata pelo leitor de código de barras) ou via Rede TCP/IP (porta `9100`).

---

## Como Instalar e Usar no PC Windows da Lyda

### Opção 1: Executar Direto com 2 Cliques
1. Copie esta pasta inteira para o computador da Lyda (com Python 3 instalado).
2. Dê dois cliques em **`INICIAR_SISTEMA_LYDA.bat`**.
3. Na primeira execução ele cria o ambiente `.venv` e instala os leitores de Excel automaticamente, abrindo o sistema em seguida.

### Opção 2: Gerar um Arquivo Executável Único (`Lyda_Etiquetas_ZD230.exe`)
Se quiser um `.exe` único que não dependa de nada:
1. Dê dois cliques em **`GERAR_EXE_WINDOWS.bat`**.
2. Ele criará o executável pronto na pasta `dist\Lyda_Etiquetas_ZD230.exe`.

