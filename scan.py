from pyzbar.pyzbar import decode # usado pra decodificar o código de barras
from fitz import open, Matrix # usado pra abrir o pdf e converter em imagem
from PIL import Image # usado pra abrir a imagem
from pytesseract import pytesseract, image_to_string # usado pra ler o texto da imagem
from re import search # usado pra procurar o número do pedido de compra no texto da imagem
from pathlib import Path # usado pra renomear o arquivo pdf

pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

with open(r"c:\Users\Murilo\OneDrive\Documents\Digitalizados\doc001.pdf") as doc: # abre o pdf
    page = doc[0] # pega a primeira página do pdf
    img_dpi = Matrix(6.7, 6.7) # aumenta a resolução da imagem
    img_pixels = doc[0].get_pixmap(matrix=img_dpi) # converte a primeira página do pdf em imagem
    img = Image.frombytes("RGB", [img_pixels.width, img_pixels.height], img_pixels.samples) # converte a imagem em um objeto PIL
    
    txt = image_to_string(img, lang='por') # lê o texto da imagem e transforma em string
    
    leitura_cod_barras = decode(img) # decodifica o código de barras da imagem
    
    if leitura_cod_barras:
        codigo_barras = leitura_cod_barras[0].data.decode("utf-8") # pega o código de barras decodificado e transforma em string
        numero_NF = codigo_barras[25:34] # pega o número da nota fiscal do código de barras
    else:
        procurar_NF = search(r"FATURA[\s\S]{0,150}?(\d{4,6})", txt) # procura o número da nota fiscal no texto da imagem caso tenha algum erro na leitura do código de barras
        if procurar_NF:
            numero_NF = procurar_NF.group(1) # pega o número da nota fiscal encontrado
        else:
            numero_NF = "undefined" # define o número da nota fiscal como "não encontrada" se não for encontrado

    while numero_NF[0] == '0':
        numero_NF = numero_NF[1:]
    
    procurar_PO = search(r"PO[\s]*(\d+)", txt) # procura o número do pedido de compra no texto da imagem
    if procurar_PO:
        if "PO" in txt: # verifica se o texto contém a palavra "PO"
            numero_PO = procurar_PO.group(1) # pega o número do pedido de compra encontrado
            if "PARCIAL" in txt: # verifica se a nota fiscal é parcial
                numero_PO = f"PO {numero_PO} PARCIAL" # adiciona a palavra "PARCIAL" ao número da PO
            else:
                numero_PO = f"PO {numero_PO}" # define o número da PO como está
    else:
        numero_PO = "undefined" # define o número da PO como "PO não encontrada" se não for encontrada

Path(r"c:\Users\Murilo\OneDrive\Documents\Digitalizados\doc001.pdf").rename( # renomeia o arquivo pdf com o número da NF e da PO
    rf"c:\Users\Murilo\OneDrive\Documents\Digitalizados\NF {numero_NF} {numero_PO}.pdf"
)
