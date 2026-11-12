# Guia Definitivo: Como Transformar o PC do Colaborador no Servidor Local Permanente da LYDA

Este guia explica como configurar o computador de um colaborador para atuar como o **Servidor Central da LYDA** na rede local, de forma que:
1. **Nunca feche ou seja desligado por engano** (roda 100% em segundo plano, sem janela de prompt aberta na tela).
2. **Inicie sozinho sempre que o computador for ligado ou reiniciado**.
3. **Tenha auto-recuperação (Watchdog)**: se o processo travar ou for encerrado, ele renasce automaticamente em 3 segundos.
4. **O PC nunca entre em modo de suspensão/dormir** enquanto conectado à tomada.
5. **Todos os outros computadores, notebooks e celulares da empresa acessem pelo navegador** através da rede Wi-Fi ou cabo.

---

## Passo 1: Copiar a pasta do sistema para o PC do Colaborador
1. Copie a pasta inteira do sistema para um local fixo no computador dele, por exemplo:
   `C:\LYDA_SISTEMA`
   *(Evite deixar na pasta Downloads ou Lixeira para não ser apagado acidentalmente).*

2. Certifique-se de que o **Python 3** está instalado no computador dele (baixe de [python.org](https://www.python.org) marcando a opção *"Add Python to PATH"* na instalação).

---

## Passo 2: Executar o Instalador Automático de 1 Clique
1. Abra a pasta `C:\LYDA_SISTEMA`.
2. Clique com o botão direito no arquivo:
   👉 **`INSTALAR_SERVIDOR_PERMANENTE_WINDOWS.bat`**
3. Selecione **"Executar como Administrador"**.

O instalador fará tudo sozinho:
- Instalará as bibliotecas necessárias (`Flask`, `OpenPyXL`, `ReportLab`, `Pillow`).
- Liberará a porta `8080` no Firewall do Windows.
- Desativará a suspensão/sono do computador na tomada.
- Criará a tarefa permanente no **Agendador de Tarefas do Windows** para iniciar sempre no boot/logon.
- Iniciará o servidor imediatamente em modo silencioso invisível.
- Criará um atalho na Área de Trabalho: **"Acessar Sistema LYDA (Servidor Local)"**.

---

## Passo 3: Pegar o Link da Rede e Enviar para a Equipe
No final da instalação (ou executando o arquivo `VER_LINK_DE_ACESSO_NA_REDE.bat`), a tela mostrará os links:

- **Para o próprio colaborador usar neste PC:**
  `http://localhost:8080`

- **Para TODOS os outros computadores, tablets e celulares da LYDA acessarem:**
  `http://192.168.X.XXX:8080` *(o número exato do IP aparecerá na tela)*

Envie este link no WhatsApp ou e-mail da equipe. Todos podem salvar nos Favoritos do Google Chrome, Edge ou Safari!

---

## Dica Importante: Fixar o IP do PC do Colaborador
Para que o número do IP nunca mude quando o roteador da empresa for reiniciado:
- **Opção A:** Peça para o responsável pela TI/Rede fixar o IP local deste computador no roteador (DHCP Reservation).
- **Opção B:** Ou acessem pelo nome do computador na rede, por exemplo:
  `http://NOME-DO-PC:8080`

---

## Como o Colaborador Trabalha no Dia a Dia?
- O colaborador pode usar o computador normalmente para suas tarefas normais (trabalhar no Excel, e-mails, navegação, etc.).
- Ele **não verá nenhuma janela preta de terminal aberta** atrapalhando a tela.
- Se ele precisar usar o sistema LYDA, basta dar dois cliques no atalho da Área de Trabalho.

---

## Como Parar o Servidor (caso precise de manutenção)?
Caso queira interromper temporariamente o servidor:
- Dê dois cliques em **`PARAR_SERVIDOR_WINDOWS.bat`**.
