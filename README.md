# bar-code-reading
Este repositório contém o código que criei para renomear arquivos automaticamente. Fiz isso porque, no trabalho, preciso escanear e organizar de 150 a 200 notas fiscais de venda de pedidos entregues numa pasta compartilhada toda semana; para reduzir o trabalho manual, este script renomeia cada nota com o número da NF e o número da PO (pedido de compra).

## Como funciona
- **Número da NF**: lido do código de barras (chave de acesso, validada pelo dígito verificador). Se falhar, usa OCR na chave impressa ou no "Nº:" do cabeçalho.
- **Número da PO**: OCR só no quadro "Dados Adicionais" (rodapé). A PO é lida várias vezes, com tratamentos de imagem diferentes, e vence o número mais votado; se as leituras não concordarem, fica `undefined` (melhor que um número errado).
- O arquivo é renomeado para `NF 13606 PO 518763.pdf`. Se não achar algo, fica `undefined`. Se as leituras da PO divergirem, o nome ganha `conferir` no final (ex.: `NF 13680 PO 513382 conferir.pdf`) pra você conferir na mão. Se o nome já existir, adiciona `(2)`, `(3)`...
- Cada execução grava o resultado (e erros) em `scan_log.txt`, na mesma pasta do script.

## Uso
- `python scan.py` → renomeia os `doc*.pdf` gerados pelo scanner (o `rodar.vbs` faz isso).
- `python scan.py refazer` → tenta de novo os arquivos que ficaram com `undefined` no nome.
- `python scan.py auditar` → lê de novo todas as notas já renomeadas (`NF *.pdf`) e gera a planilha `auditoria.csv` com as que não batem com o nome. Não renomeia nada. Leva uns 5 a 6 segundos por nota.

## Instalação
1. `pip install -r requirements.txt`
2. Instalar o [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) em `C:\Program Files\Tesseract-OCR`, marcando o idioma **Portuguese** na instalação.
3. Se o `pyzbar` reclamar de DLL no Windows, instalar o [Visual C++ Redistributable 2013](https://www.microsoft.com/en-us/download/details.aspx?id=40784).
