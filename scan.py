import io # usado pra ler a imagem embutida no pdf
import logging # usado pra salvar um log com o resultado de cada arquivo
import re # usado pra procurar os números no texto da imagem
import sys # usado pra ler o argumento "refazer" da linha de comando
from pathlib import Path # usado pra listar e renomear os arquivos pdf

import pymupdf # usado pra abrir o pdf e extrair a imagem
import pytesseract # usado pra ler o texto da imagem
from PIL import Image # usado pra manipular a imagem
from pyzbar.pyzbar import decode # usado pra decodificar o código de barras

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
    for codigo in decode(img):
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


def ler_numero_po(img):
    # a PO fica no quadro "DADOS ADICIONAIS", no rodapé da página.
    # fazer o OCR só nesse pedaço é bem mais rápido e mais preciso do que na página inteira
    largura, altura = img.size
    rodape = img.convert("L").crop((0, int(altura * 0.80), int(largura * 0.70), altura))

    # tenta alguns tamanhos diferentes, porque o OCR às vezes confunde um dígito (ex.: "7" vira "/")
    tentativas = [rodape.resize((int(rodape.width * zoom), int(rodape.height * zoom)), Image.LANCZOS) for zoom in (1.5, 2, 1)]
    tentativas.append(img.convert("L")) # último recurso: página inteira

    for imagem in tentativas:
        texto = pytesseract.image_to_string(imagem, lang="por", config="--psm 6")
        achado = re.search(r"\bP[O0]\s*[:.]?\s*(\d[\d/.,]*\d)", texto)
        if not achado:
            continue
        numero = re.sub(r"\D", "", achado.group(1)) # remove lixo que o OCR coloca no meio dos dígitos
        if len(numero) == 6: # as POs têm 6 dígitos; se não tiver, provavelmente o OCR errou e tenta de novo
            parcial = "PARCIAL" in texto[achado.start():].upper()
            return f"{numero} PARCIAL" if parcial else numero

    return None


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
    numero_PO = ler_numero_po(img)
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
