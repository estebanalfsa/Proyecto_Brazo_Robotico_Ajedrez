"""clasificador.py - Reconoce el TIPO de pieza por su sticker (solo OpenCV)."""
import os
import cv2
import numpy as np

ARCHIVO = "modelo_piezas.npz"
TAM = 32
TIPOS = "PNBRQK"
NOMBRES = {"P": "PEON", "N": "CABALLO", "B": "ALFIL", "R": "TORRE", "Q": "DAMA", "K": "REY"}
FILA1 = {"A": "R", "B": "N", "C": "B", "D": "Q", "E": "K", "F": "B", "G": "N", "H": "R"}

def tipo_inicial(nombre):
    """Tipo esperado en la posicion inicial de TU lado (filas 1 y 2)."""
    if nombre[1] == "1":
        return FILA1[nombre[0]]
    return "P" if nombre[1] == "2" else None

def recorte(rect, col, row, step, margen=0.12):
    m = int(step * margen)
    return rect[row * step + m:(row + 1) * step - m, col * step + m:(col + 1) * step - m]

def vector(zona):
    g = cv2.GaussianBlur(cv2.cvtColor(zona, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    b = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 8)
    b = cv2.resize(b, (TAM, TAM), interpolation=cv2.INTER_AREA)
    return (b.astype(np.float32) / 255.0).reshape(-1)

def variantes(zona):
    """La muestra original + pequenos giros y desplazamientos (aumento de datos)."""
    h, w = zona.shape[:2]
    out = [vector(zona)]
    for ang in (-8, -4, 4, 8):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        out.append(vector(cv2.warpAffine(zona, M, (w, h), borderMode=cv2.BORDER_REPLICATE)))
    for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2)):
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        out.append(vector(cv2.warpAffine(zona, M, (w, h), borderMode=cv2.BORDER_REPLICATE)))
    return out

class Clasificador:
    def __init__(self):
        self.X = np.empty((0, TAM * TAM), np.float32)
        self.y = np.empty((0,), np.int32)
        self.knn = None
        if os.path.exists(ARCHIVO):
            d = np.load(ARCHIVO)
            self.X, self.y = d["X"], d["y"]
            self._entrenar()

    def listo(self):
        return self.knn is not None

    def _entrenar(self):
        if len(self.y) == 0:
            return
        self.knn = cv2.ml.KNearest_create()
        self.knn.train(self.X, cv2.ml.ROW_SAMPLE, self.y.astype(np.float32).reshape(-1, 1))

    def agregar_lote(self, muestras):
        """muestras = [(recorte_bgr, 'P'), ...]"""
        xs, ys = [], []
        for zona, tipo in muestras:
            v = variantes(zona)
            xs += v
            ys += [TIPOS.index(tipo)] * len(v)
        self.X = np.vstack([self.X, np.array(xs, np.float32)])
        self.y = np.concatenate([self.y, np.array(ys, np.int32)])
        np.savez(ARCHIVO, X=self.X, y=self.y)
        self._entrenar()

    def predecir(self, zona):
        """(tipo, confianza 0-1) segun el voto de los 5 vecinos mas parecidos."""
        if self.knn is None:
            return None, 0.0
        _, res, vec, _ = self.knn.findNearest(vector(zona).reshape(1, -1), 5)
        return TIPOS[int(res[0, 0])], float((vec == res[0, 0]).sum()) / 5.0