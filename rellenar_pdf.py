#!/usr/bin/env python3
"""Rellena los documentos de transporte Basel (kbb.pdf, rc.pdf).

Escribe el nombre (a mitad del documento y al final, según la tienda), la fecha
junto al "Date:" de abajo, la cantidad debajo de "Quantity of equipment"
(punto 13) y marca con una X las casillas del punto 7.
Las posiciones se localizan leyendo el propio PDF, así que sirve para ambos.
Nunca sobrescribe el original: guarda <nombre>_relleno_<fecha>.pdf.

Uso:
  python3 rellenar_pdf.py archivos/kbb.pdf archivos/rc.pdf \
      --cantidad 3 --casillas smart,accesorio --tienda elche [--fecha 29/10/2026] [--salida carpeta]

Casillas: smart, componente, accesorio, ordenador
Tienda: elche (Daniel M.) o alicante (Juan S.)
Requiere: pip install pypdf reportlab pdfplumber
"""
import argparse
import datetime
import io
import re
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject
from reportlab.pdfgen import canvas

CASILLAS = ["smart", "componente", "accesorio", "ordenador"]  # orden de arriba abajo
TIENDAS = {"elche": "Daniel M.", "alicante": "Juan S."}
NOMBRES_PREVIOS = {"Daniel M.", "Juan S.S.", "Juan S."}
PATRON_FECHA = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


def localizar(ruta):
    """Devuelve las posiciones (en coordenadas PDF, origen abajo-izquierda)."""
    with pdfplumber.open(ruta) as pdf:
        p = pdf.pages[0]
        alto = p.height
        palabras = p.extract_words()
        fechas = [w for w in palabras if w["text"] == "Date:"]
        fecha = max(fechas, key=lambda w: w["top"])  # el "Date:" más bajo (punto 14)
        cant = [w for w in palabras if w["text"] == "Quantity" and w["x0"] > p.width * 0.6]
        cant = min(cant, key=lambda w: w["top"])
        equip = min((w for w in palabras if w["text"] == "equipment"
                     and abs(w["x0"] - cant["x0"]) < 15 and w["top"] > cant["top"]),
                    key=lambda w: w["top"])
        # primera palabra de la columna por debajo ("Cumulative value...")
        cumul = min((w for w in palabras if w["top"] > equip["bottom"] + 5
                     and cant["x0"] - 10 < w["x0"] < equip["x1"]), key=lambda w: w["top"])
        smart = next(w for w in palabras if w["text"] == "Smart")
        cajas = {}
        for r in p.rects:
            if (r["x1"] < smart["x0"] and smart["top"] - 10 < r["top"] < smart["top"] + 90
                    and 4 < r["width"] < 10):
                cajas[round(r["top"])] = r  # deduplica rectángulos repetidos
        cajas = [cajas[k] for k in sorted(cajas)]
        if len(cajas) != 4:
            raise SystemExit(f"{ruta}: esperaba 4 casillas en el punto 7, hay {len(cajas)}")
        # nombres ya escritos como anotación (mitad y final del documento)
        nombres = []
        for a in PdfReader(ruta).pages[0].get("/Annots") or []:
            a = a.get_object()
            if a.get("/Subtype") == "/FreeText" and str(a.get("/Contents") or "").strip() in {"Daniel M.", "Juan S.S."}:
                x0, y0 = float(a["/Rect"][0]), float(a["/Rect"][1])
                nombres.append((x0, y0))
        nombres = sorted(set(nombres), key=lambda t: -t[1])
        mitad, final = nombres[0], nombres[-1]
        # misma línea base que la etiqueta "Name:" (los dos últimos "Name:" del documento)
        etiquetas = sorted((w for w in palabras if w["text"] == "Name:"), key=lambda w: w["top"])[-2:]
        bases = [alto - w["bottom"] + 0.22 * (w["bottom"] - w["top"]) for w in etiquetas]
        return {
            "alto": alto,
            "nombres": [(mitad[0], bases[0]), (final[0], bases[1])],
            "fecha": (fecha["x1"] + 6, alto - fecha["bottom"] + 0.22 * (fecha["bottom"] - fecha["top"])),
            "cantidad": ((cant["x0"] + equip["x1"]) / 2,
                         alto - (equip["bottom"] + cumul["top"]) / 2 - 5),
            "casillas": [(c["x0"], alto - c["bottom"], c["width"]) for c in cajas],
        }


def quitar_fechas_antiguas(pagina):
    """Elimina anotaciones con fechas y nombres de rellenos anteriores (y su recuadro)."""
    annots = pagina.get("/Annots")
    if not annots:
        return
    lista = [a.get_object() for a in annots]
    viejas = [a for a in lista if a.get("/Subtype") == "/FreeText"
              and (PATRON_FECHA.search(str(a.get("/Contents") or ""))
                   or str(a.get("/Contents") or "").strip() in NOMBRES_PREVIOS)]

    def solapa(a, b):
        ax0, ay0, ax1, ay1 = [float(v) for v in a["/Rect"]]
        bx0, by0, bx1, by1 = [float(v) for v in b["/Rect"]]
        return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1

    quitar = set(id(a) for a in viejas)
    for a in lista:
        if a.get("/Subtype") == "/Square" and any(solapa(a, v) for v in viejas):
            quitar.add(id(a))
    pagina[NameObject("/Annots")] = ArrayObject(
        r for r, a in zip(annots, lista) if id(a) not in quitar)


def rellenar(ruta, fecha, cantidad, casillas, tienda, salida):
    pos = localizar(ruta)
    lector = PdfReader(ruta)
    pagina = lector.pages[0]
    ancho = float(pagina.mediabox.width)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(ancho, pos["alto"]))
    c.setFont("Helvetica", 10)
    c.setFont("Helvetica", 8)  # más pequeño para no pisar "Function:"
    for x, y in pos["nombres"]:
        c.drawString(x, y, TIENDAS[tienda])
    c.setFont("Helvetica", 10)
    c.drawString(*pos["fecha"], fecha)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(*pos["cantidad"], str(cantidad))
    c.setLineWidth(1)
    for nombre in casillas:
        x, y, lado = pos["casillas"][CASILLAS.index(nombre)]
        m = 1
        c.line(x + m, y + m, x + lado - m, y + lado - m)
        c.line(x + m, y + lado - m, x + lado - m, y + m)
    c.save()

    quitar_fechas_antiguas(pagina)
    pagina.merge_page(PdfReader(buf).pages[0])
    escritor = PdfWriter()
    escritor.add_page(pagina)
    salida.mkdir(parents=True, exist_ok=True)
    destino = salida / f"{Path(ruta).stem}_relleno_{fecha.replace('/', '-')}.pdf"
    with open(destino, "wb") as f:
        escritor.write(f)
    return destino


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--fecha", default=datetime.date.today().strftime("%d/%m/%Y"))
    ap.add_argument("--cantidad", required=True)
    ap.add_argument("--tienda", required=True, choices=sorted(TIENDAS))
    ap.add_argument("--casillas", default="", help=",".join(CASILLAS))
    ap.add_argument("--salida", help="carpeta destino (por defecto, junto al original)")
    a = ap.parse_args()
    casillas = [s.strip().lower() for s in a.casillas.split(",") if s.strip()]
    for s in casillas:
        if s not in CASILLAS:
            raise SystemExit(f"Casilla desconocida: {s}. Opciones: {', '.join(CASILLAS)}")
    for ruta in a.pdfs:
        salida = Path(a.salida) if a.salida else Path(ruta).parent
        print(rellenar(ruta, a.fecha, a.cantidad, casillas, a.tienda, salida))


if __name__ == "__main__":
    main()
