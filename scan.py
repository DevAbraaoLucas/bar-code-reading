import csv # usado pra gerar a planilha da auditoria
import io # usado pra ler a imagem embutida no pdf
import logging # usado pra salvar um log com o resultado de cada arquivo
import re # usado pra procurar os números no texto da imagem
import sys # usado pra ler o argumento "refazer" da linha de comando
from collections import Counter # usado pra contar os votos das leituras da PO
from pathlib import Path # usado pra listar e renomear os arquivos pdf

import pymupdf # usado pra abrir o pdf e extrair a imagem
import pytesseract # usado pra ler o texto da imagem
from PIL import Image, ImageFilter, ImageOps # usado pra manipular a imagem
from pyzbar.pyzbar import ZBarSymbol, decode # usado pra decodificar o código de barras

PASTA = Path(r"c:\Users\Murilo\OneDrive\Documents\Digitalizados") # pasta onde o scanner salva os pdfs
PADRAO_SCANNER = "doc*.pdf" # nome dos arquivos gerados pelo scanner (doc001.pdf, doc002.pdf...)
PADRAO_REFAZER = "NF * undefined*.pdf" # arquivos que ficaram com "undefined" e podem ser reprocessados
PADRAO_AUDITAR = "NF *.pdf" # todos os arquivos já renomeados, pra conferir se o nome está certo
TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
LARGURA_300DPI = 2480 # largura em pixels de uma folha A4 escaneada em 300 DPI (a resolução usada nos testes)

if TESSERACT.exists(): # só configura o caminho se o tesseract estiver instalado nesse lugar
    pytesseract.pytesseract.tesseract_cmd = str(TESSERACT)

logging.basicConfig(
    filename=Path(__file__).with_name("scan_log.txt"),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    encoding="utf-8",
)


def carregar_imagem(pdf):
    """Retorna a primeira página do pdf como imagem, na resolução original do scanner."""
    with pymupdf.open(pdf) as doc:
        pagina = doc[0]
        imagens = pagina.get_images()
        if imagens:
            # pega a imagem original que o scanner salvou dentro do pdf, sem ampliar.
            # ampliar demais (o antigo Matrix(6.7, 6.7)) deixava o código de barras ilegível pro pyzbar
            dados = doc.extract_image(imagens[0][0])["image"]
            return Image.open(io.BytesIO(dados)).convert("RGB")
        pixmap = pagina.get_pixmap(dpi=300) # caso o pdf não tenha imagem embutida, converte a página em 300 DPI
        return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)


def escala(img):
    """Quanto a imagem precisa ser multiplicada pra ficar no tamanho de 300 DPI (ex.: 0.5 se foi escaneada em 600 DPI)."""
    fator = LARGURA_300DPI / img.width
    return 1 if 0.95 < fator < 1.05 else fator # diferença pequena (ex.: 2478 x 2480 pixels) é ignorada


def chave_valida(chave):
    """Confere se a chave de acesso tem 44 dígitos e se o dígito verificador (último dígito) bate."""
    if len(chave) != 44 or not chave.isdigit():
        return False
    pesos = [2, 3, 4, 5, 6, 7, 8, 9] * 6
    soma = sum(int(digito) * peso for digito, peso in zip(reversed(chave[:43]), pesos))
    resto = soma % 11
    dv = 0 if resto < 2 else 11 - resto
    return dv == int(chave[43])


def numero_da_chave(chave):
    """A chave de acesso guarda o número da NF nas posições 25 a 33."""
    return chave[25:34].lstrip("0")


def ler_numero_nf(img):
    # 1ª tentativa: código de barras (só aceita se for uma chave de acesso válida)
    # o código de barras da NF-e é sempre CODE128. procurar só esse tipo é mais rápido
    # e evita os avisos "WARNING: zbar decoder databar.c" no terminal
    tentativas = [img]
    if escala(img) < 0.9: # imagem muito grande (escaneada acima de 300 DPI) atrapalha o pyzbar: tenta também reduzida
        tentativas.append(img.resize((LARGURA_300DPI, int(img.height * escala(img))), Image.LANCZOS))
    for imagem in tentativas:
        for codigo in decode(imagem, symbols=[ZBarSymbol.CODE128]):
            chave = codigo.data.decode("utf-8", errors="ignore")
            if chave_valida(chave):
                return numero_da_chave(chave)

    # se o código de barras falhar, faz o OCR da página inteira (é a parte mais lenta, por isso fica por último)
    texto = pytesseract.image_to_string(img, lang="por")

    # 2ª tentativa: chave de acesso impressa ao lado do código de barras (11 grupos de 4 dígitos)
    for achado in re.finditer(r"(?:\d{4}\s?){11}", texto):
        chave = re.sub(r"\s", "", achado.group())
        if chave_valida(chave):
            return numero_da_chave(chave)

    # 3ª tentativa: "Nº: 13606" do cabeçalho, ou o número logo abaixo de "FATURA ... NÚMERO"
    # (o regex antigo às vezes pegava o ano de uma data, gerando "NF 2026")
    achado = re.search(r"N[º°o]\s*:\s*(\d{3,9})\b", texto) or re.search(
        r"FATURA[\s\S]{0,200}?N[UÚ]MERO[^\n]*\n\s*(\d{3,9})\b", texto
    )
    if achado:
        return achado.group(1).lstrip("0")

    return None


# leituras feitas na PO: (tratamento da imagem, zoom). foram escolhidas testando várias notas reais:
# nenhuma dessas leituras errou a PO nos testes, mas cada uma às vezes não consegue ler
LEITURAS_PO = [
    ("contraste", 1),
    ("original", 1.5),
    ("engrossado", 1.5),
    ("contraste", 2),
    ("contraste", 2.5),
    ("engrossado", 2.5),
    ("engrossado", 3),
]


def preparar(rodape, tratamento, zoom, fator=1):
    # os zooms foram calibrados em 300 DPI; "fator" corrige isso se o scanner usar outra resolução
    zoom = zoom * fator
    if tratamento in ("contraste", "engrossado"):
        rodape = ImageOps.autocontrast(rodape, cutoff=1) # deixa o texto cinza claro mais escuro
    if tratamento == "engrossado":
        tamanho = max(3, round(3 / fator) // 2 * 2 + 1) # 3 em 300 DPI, 7 em 600 DPI (precisa ser ímpar)
        rodape = rodape.filter(ImageFilter.MinFilter(tamanho)) # engrossa as letras finas da fonte
    if zoom != 1:
        rodape = rodape.resize((int(rodape.width * zoom), int(rodape.height * zoom)), Image.LANCZOS)
    return rodape


def ler_numero_po(img, nome=""):
    # a PO fica no quadro "DADOS ADICIONAIS", no rodapé da página.
    # fazer o OCR só nesse pedaço é bem mais rápido e mais preciso do que na página inteira
    largura, altura = img.size
    rodape = img.convert("L").crop((0, int(altura * 0.80), int(largura * 0.70), altura))

    # a fonte desse quadro é fina e clara, e o OCR às vezes troca um dígito por outro (ex.: "3" vira "2")
    # sem deixar nenhum sinal de erro. por isso a PO é lida várias vezes, de jeitos diferentes, e vence
    # o número mais votado. se as leituras não concordarem o suficiente, fica "undefined" (melhor que errado)
    votos = Counter()
    parcial = Counter()
    for tratamento, zoom in LEITURAS_PO:
        texto = pytesseract.image_to_string(preparar(rodape, tratamento, zoom, escala(img)), lang="por", config="--psm 6")
        # o "O" de "PO" às vezes sai como "0", "C" ou "Q" no OCR quando a impressão está fraca.
        # a PO tem 5 ou 6 dígitos e precisa vir "limpa", seguida de espaço: se o OCR colocar lixo
        # no meio (ex.: "5187/63"), essa leitura é descartada
        achado = re.search(r"\bP[O0CQ]\s*[:.]?\s*(\d{5,6})(?=\s)", texto)
        if not achado:
            continue
        numero = achado.group(1)
        votos[numero] += 1
        resto_da_linha = texto[achado.end():].split("\n")[0]
        if "PARCIAL" in resto_da_linha.upper():
            parcial[numero] += 1

        # caso fácil: 3 leituras iguais e nenhuma diferente, não precisa continuar
        if len(votos) == 1 and votos[numero] >= 3:
            break

    if not votos:
        return None

    mais_votados = votos.most_common(2)
    numero, qtd = mais_votados[0]
    segundo = mais_votados[1][1] if len(mais_votados) > 1 else 0
    if len(votos) > 1:
        logging.info(f"{nome}: leituras da PO divergiram {dict(votos)}")
    if qtd < 3 or qtd < 2 * segundo: # precisa de pelo menos 3 votos e o dobro do segundo colocado
        return None
    if parcial[numero]:
        numero = f"{numero} PARCIAL"
    if len(votos) > 1: # venceu, mas alguma leitura deu outro número: marca pra conferir na mão
        numero = f"{numero} conferir"
    return numero


def nome_livre(destino):
    """Se já existir um arquivo com esse nome, adiciona (2), (3)... pra não dar erro nem sobrescrever."""
    contador = 2
    novo = destino
    while novo.exists():
        novo = destino.with_name(f"{destino.stem} ({contador}){destino.suffix}")
        contador += 1
    return novo


def processar(pdf):
    img = carregar_imagem(pdf)

    numero_NF = ler_numero_nf(img) or "undefined"
    numero_PO = ler_numero_po(img, pdf.name)
    numero_PO = f"PO {numero_PO}" if numero_PO else "undefined"

    destino = pdf.with_name(f"NF {numero_NF} {numero_PO}.pdf")
    if destino == pdf: # reprocessou e chegou no mesmo nome, não precisa renomear
        return pdf
    destino = nome_livre(destino)
    pdf.rename(destino)
    return destino


def auditar():
    """Lê de novo todas as notas já renomeadas e lista numa planilha as que não batem com o nome. Não renomeia nada."""
    pdfs = sorted(PASTA.glob(PADRAO_AUDITAR))
    planilha = Path(__file__).with_name("auditoria.csv")
    contagem = Counter()

    # "utf-8-sig" e ";" fazem o Excel em português abrir a planilha certinho, com acentos e colunas separadas
    with open(planilha, "w", newline="", encoding="utf-8-sig") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(["Arquivo", "NF no nome", "NF lida", "PO no nome", "PO lida", "Situação"])

        for i, pdf in enumerate(pdfs, start=1):
            print(f"[{i}/{len(pdfs)}] {pdf.name}")
            nome = pdf.stem
            nf_nome = nome.split()[1] if len(nome.split()) > 1 else ""
            po_nome = re.search(r"PO (\d+)", nome)
            po_nome = po_nome.group(1) if po_nome else None
            parcial_nome = "PARCIAL" in nome

            try:
                img = carregar_imagem(pdf)
                nf_lida = ler_numero_nf(img)
                po_lida_completa = ler_numero_po(img, pdf.name) or ""
            except Exception as erro:
                escritor.writerow([pdf.name, nf_nome, "", po_nome or "", "", f"erro ao ler o arquivo: {erro}"])
                contagem["erro ao ler o arquivo"] += 1
                continue
            po_lida = po_lida_completa.split()[0] if po_lida_completa else None
            parcial_lida = "PARCIAL" in po_lida_completa

            problemas = []
            if not nf_lida and not po_lida:
                problemas.append("não parece NF") # documento que não é nota (ou ilegível)
            else:
                if nf_lida != nf_nome:
                    problemas.append("NF diferente")
                if po_nome and po_lida and po_nome != po_lida:
                    problemas.append("PO diferente")
                if po_nome and not po_lida:
                    problemas.append("PO do nome não confirmada") # a leitura nova não conseguiu ler a PO
                if not po_nome and po_lida:
                    problemas.append("PO encontrada (nome está sem PO)")
                if po_nome and po_lida and parcial_nome != parcial_lida:
                    problemas.append("PARCIAL diferente")
                if "conferir" in po_lida_completa:
                    problemas.append("leituras da PO divergiram")

            if problemas:
                escritor.writerow([pdf.name, nf_nome, nf_lida or "", po_nome or "", po_lida_completa, "; ".join(problemas)])
                arquivo.flush() # grava na hora, pra não perder o que já foi feito se o programa for interrompido
                for problema in problemas:
                    contagem[problema] += 1
            else:
                contagem["ok"] += 1

    print(f"\nPronto! {len(pdfs)} arquivos conferidos. Planilha salva em: {planilha}")
    for situacao, quantidade in contagem.most_common():
        print(f"  {situacao}: {quantidade}")


def main():
    # modo normal: renomeia os pdfs novos do scanner
    # "python scan.py refazer": tenta de novo os arquivos que ficaram com "undefined"
    # "python scan.py auditar": confere todas as notas já renomeadas e gera a planilha auditoria.csv
    if "auditar" in sys.argv[1:]:
        auditar()
        return
    padrao = PADRAO_REFAZER if "refazer" in sys.argv[1:] else PADRAO_SCANNER
    for pdf in sorted(PASTA.glob(padrao)):
        try:
            destino = processar(pdf)
            logging.info(f"{pdf.name} -> {destino.name}")
        except Exception:
            logging.exception(f"erro ao processar {pdf.name}")


if __name__ == "__main__":
    main()
