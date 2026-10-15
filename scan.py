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
TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

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
            # pega a imagem original que o scanner salvou dentro do pdf (300 DPI), sem ampliar.
            # ampliar demais (o antigo Matrix(6.7, 6.7)) deixava o código de barras ilegível pro pyzbar
            dados = doc.extract_image(imagens[0][0])["image"]
            return Image.open(io.BytesIO(dados)).convert("RGB")
        pixmap = pagina.get_pixmap(dpi=300) # caso o pdf não tenha imagem embutida, converte a página em 300 DPI
        return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)


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
    for codigo in decode(img, symbols=[ZBarSymbol.CODE128]):
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


def preparar(rodape, tratamento, zoom):
    if tratamento in ("contraste", "engrossado"):
        rodape = ImageOps.autocontrast(rodape, cutoff=1) # deixa o texto cinza claro mais escuro
    if tratamento == "engrossado":
        rodape = rodape.filter(ImageFilter.MinFilter(3)) # engrossa as letras finas da fonte
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
        texto = pytesseract.image_to_string(preparar(rodape, tratamento, zoom), lang="por", config="--psm 6")
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
    return f"{numero} PARCIAL" if parcial[numero] else numero


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


def main():
    # modo normal: renomeia os pdfs novos do scanner
    # "python scan.py refazer": tenta de novo os arquivos que ficaram com "undefined"
    padrao = PADRAO_REFAZER if "refazer" in sys.argv[1:] else PADRAO_SCANNER
    for pdf in sorted(PASTA.glob(padrao)):
        try:
            destino = processar(pdf)
            logging.info(f"{pdf.name} -> {destino.name}")
        except Exception:
            logging.exception(f"erro ao processar {pdf.name}")


if __name__ == "__main__":
    main()
