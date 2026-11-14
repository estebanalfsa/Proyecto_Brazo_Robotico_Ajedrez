"""
vision_tablero.py - Vision del tablero + ordenes de jugada para el brazo de ajedrez
====================================================================================
Funciones:
  - Clic en las 4 esquinas -> rectifica el tablero y nombra las 64 casillas (A1..H8).
  - Detecta casillas OCUPADAS comparando contra una foto del tablero vacio.
  - Recibe una orden "origen -> destino" (teclado o mouse) y la valida:
        * el origen debe tener pieza
        * el destino NO puede estar ocupado (si lo esta, se rechaza y pide otra casilla)
  - Si es valida, manda al robot (robot.py) a mover la pieza y luego verifica con la camara.

Requisitos:  pip install opencv-python numpy pyserial
Uso:         python vision_tablero.py --listar                    (que numero de camara funciona)
             python vision_tablero.py --camara 1                  (simulacion, sin robot)
             python vision_tablero.py --camara 1 --puerto COM5    (con robot)

Teclas (ventana normal):
  C calibrar (tras los 4 clics)   E capturar tablero VACIO   O girar orientacion
  M modo jugada                   T guardar mapa y mostrar tabla   D diagnostico
  U aceptar la lectura actual     R reiniciar                      X PARADA del robot    Q / Esc salir

El brazo tapa casillas al moverse: por eso la lectura se CONGELA mientras el robot trabaja (y 1 s
despues), se ignoran cambios masivos (mano/brazo) y el brazo debe reposar FUERA del encuadre.
Modo jugada (M): escribe origen y destino, ej.  E 3 G 5  (Esc sale del modo)
Mouse: clic en una casilla del tablero rectificado = origen, otro clic = destino.
"""
import argparse
import csv
import json
import os
import threading
import time

import cv2
import numpy as np

import robot

# ---------------------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------------------
CAMERA_INDEX = 1
RESOLUCION = (1280, 720)
BLOQUEAR_ENFOQUE = True        # evita que el autoenfoque "respire" y cambie la imagen
FOCO_MANUAL = None             # p. ej. 30; None = deja el foco como esta

BOARD_PIXELS = 640             # tamaño del tablero rectificado
STEP = BOARD_PIXELS // 8       # pixeles por casilla
BARRA_PX = 70                  # barra de estado bajo el tablero

# Deteccion de piezas
MARGEN_CASILLA = 0.15          # parte de cada casilla que NO se analiza (bordes)
UMBRAL_PIXEL = 15              # diferencia de gris para contar un pixel como "cambiado"
FRACCION_OCUPADA = 0.20        # fraccion de pixeles cambiados => hay pieza
CANNY_BAJO, CANNY_ALTO = 20, 60   # sensibilidad de bordes (piezas de poco contraste)
FRACCION_BORDES = 0.03         # fraccion de bordes NUEVOS => hay pieza (piezas del mismo tono que la casilla)
FRAMES_ESTABLES = 6            # frames seguidos iguales para aceptar un cambio
UMBRAL_EQUIPO = 0.08           # fraccion de pixeles verdes o rojos para llamar "R" a la tablita
VERIF_ESPERA_S = 2.5           # espera antes de verificar con la camara tras mover
MAX_CAMBIOS = 6                # si cambian mas casillas DE GOLPE es un brazo o una mano tapando: se ignora
DESCANSO_S = 1.0               # tras moverse el robot se espera antes de volver a leer el tablero

DIR_DATOS = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_CALIB = os.path.join(DIR_DATOS, "calibracion_tablero.json")
ARCHIVO_FONDO = os.path.join(DIR_DATOS, "fondo_vacio.png")
ARCHIVO_MAPA = os.path.join(DIR_DATOS, "mapa_casillas.csv")

WINDOW_CAMERA = "Camara - tablero"
WINDOW_BOARD = "Tablero rectificado"

VERDE, NARANJA, ROJO = (0, 170, 0), (0, 140, 255), (0, 0, 230)
AMARILLO, CIAN, BLANCO = (0, 220, 255), (255, 200, 0), (255, 255, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX


# ---------------------------------------------------------------------
# Nombres de casilla
# Vista estandar del tablero rectificado: columna 0 = A (izquierda), fila 0 = rango 8 (arriba)
# ---------------------------------------------------------------------
def nombre_casilla(col, row):
    return f"{chr(ord('A') + col)}{8 - row}"


def indices(nombre):
    """'E3' -> (col, row) en la vista rectificada."""
    n = nombre.strip().upper()
    return ord(n[0]) - ord("A"), 8 - int(n[1])


# ---------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------
def ordenar_esquinas(puntos):
    """Ordena 4 puntos (en cualquier orden) como: arriba-izq, arriba-der, abajo-der, abajo-izq."""
    pts = np.array(puntos, dtype=np.float32)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]                    # sentido horario en la imagen
    inicio = int(np.argmin(pts.sum(axis=1)))      # la mas cercana a la esquina superior izquierda
    return np.roll(pts, -inicio, axis=0)


def calcular_homografia(esquinas, rot):
    """rot (0-3) gira la orientacion del tablero rectificado en pasos de 90 grados."""
    src = np.roll(ordenar_esquinas(esquinas), -rot, axis=0)
    b = BOARD_PIXELS - 1
    dst = np.float32([[0, 0], [b, 0], [b, b], [0, b]])
    return cv2.getPerspectiveTransform(src, dst)


def proyectar(puntos, matriz):
    p = np.float32(puntos).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(p, matriz).reshape(-1, 2)


# ---------------------------------------------------------------------
# Deteccion de piezas
# ---------------------------------------------------------------------
_MASCARA_BORDE = None


def _mascara_borde():
    """True en el anillo exterior de cada casilla (la parte que NO se analiza)."""
    global _MASCARA_BORDE
    if _MASCARA_BORDE is None:
        m = int(STEP * MARGEN_CASILLA)
        mask = np.ones((BOARD_PIXELS, BOARD_PIXELS), bool)
        for row in range(8):
            for col in range(8):
                mask[row * STEP + m:(row + 1) * STEP - m, col * STEP + m:(col + 1) * STEP - m] = False
        _MASCARA_BORDE = mask
    return _MASCARA_BORDE


def equipo(zona_bgr):
    """Equipo de la tablita por color: 'R' = verde con sticker rojo, 'N' = sticker negro."""
    hsv = cv2.cvtColor(zona_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    verde = ((h > 40) & (h < 90) & (s > 70) & (v > 50)).mean()
    rojo = (((h < 10) | (h > 170)) & (s > 120) & (v > 60)).mean()
    return "R" if (verde + rojo) > UMBRAL_EQUIPO else "N"


def analizar(actual, fondo):
    """
    Compara el tablero rectificado actual contra el vacio.
    Devuelve (ocupada[8,8], color[8,8] 'R'/'N'/'', frac_cambio[8,8], frac_bordes[8,8]).
    """
    g1 = cv2.GaussianBlur(cv2.cvtColor(actual, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    g0 = cv2.GaussianBlur(cv2.cvtColor(fondo, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    # Compensa cambios globales de luz usando solo el BORDE de cada casilla (casi nunca hay
    # pieza ahi). No sirve la mediana de todo el tablero: en un tablero de ajedrez es bimodal.
    borde = _mascara_borde()
    ganancia = (float(g1[borde].mean()) + 1.0) / (float(g0[borde].mean()) + 1.0)
    g0 = np.clip(g0.astype(np.float32) * ganancia, 0, 255).astype(np.uint8)

    diff = cv2.absdiff(g1, g0)
    e1 = cv2.Canny(g1, CANNY_BAJO, CANNY_ALTO)
    e0 = cv2.dilate(cv2.Canny(g0, CANNY_BAJO, CANNY_ALTO), np.ones((5, 5), np.uint8))
    bordes_nuevos = cv2.bitwise_and(e1, cv2.bitwise_not(e0))

    m = int(STEP * MARGEN_CASILLA)
    ocup = np.zeros((8, 8), bool)
    color = np.full((8, 8), "", dtype="<U1")
    frac = np.zeros((8, 8), float)
    fbor = np.zeros((8, 8), float)
    for row in range(8):
        for col in range(8):
            y1, y2 = row * STEP + m, (row + 1) * STEP - m
            x1, x2 = col * STEP + m, (col + 1) * STEP - m
            mascara = diff[y1:y2, x1:x2] > UMBRAL_PIXEL
            frac[row, col] = mascara.mean()
            fbor[row, col] = (bordes_nuevos[y1:y2, x1:x2] > 0).mean()
            if frac[row, col] > FRACCION_OCUPADA or fbor[row, col] > FRACCION_BORDES:
                ocup[row, col] = True
                color[row, col] = equipo(actual[y1:y2, x1:x2])
    return ocup, color, frac, fbor


# ---------------------------------------------------------------------
# Estado del tablero
# ---------------------------------------------------------------------
class Tablero:
    def __init__(self):
        self.esquinas = []
        self.rot = 0
        self.H = None
        self.Hinv = None
        self.fondo_raw = None          # foto de camara del tablero vacio
        self.fondo_rect = None
        self.estable = np.zeros((8, 8), bool)
        self.cuenta = np.zeros((8, 8), int)
        self.color = np.full((8, 8), "", dtype="<U1")
        self.frac = np.zeros((8, 8))
        self.fbor = np.zeros((8, 8))
        self.raw = np.zeros((8, 8), bool)           # ultima lectura sin filtrar
        self.raw_color = np.full((8, 8), "", dtype="<U1")
        self.ocluido = False                        # True si algo (brazo, mano) tapa mucho tablero
        self.sin_lectura_inicial = True

    def reiniciar_ocupacion(self):
        self.estable[:] = False
        self.cuenta[:] = 0
        self.color[:] = ""
        self.sin_lectura_inicial = True             # la primera lectura se acepta tal cual

    def calibrar(self):
        if len(self.esquinas) != 4:
            return False
        self.H = calcular_homografia(self.esquinas, self.rot)
        self.Hinv = np.linalg.inv(self.H)
        self._recalcular_fondo()
        self.reiniciar_ocupacion()
        return True

    def _recalcular_fondo(self):
        if self.H is not None and self.fondo_raw is not None:
            self.fondo_rect = self.rectificar(self.fondo_raw)
        else:
            self.fondo_rect = None

    def rectificar(self, frame):
        return cv2.warpPerspective(frame, self.H, (BOARD_PIXELS, BOARD_PIXELS))

    def capturar_fondo(self, frame):
        self.fondo_raw = frame.copy()
        self._recalcular_fondo()
        self.reiniciar_ocupacion()

    def rotar(self):
        self.rot = (self.rot + 1) % 4
        self.calibrar()

    def reiniciar(self):
        self.__init__()

    def procesar(self, rect, congelado=False):
        """Actualiza la ocupacion estable. Un cambio se acepta tras FRAMES_ESTABLES frames iguales.
        - congelado=True (el robot se mueve): no se actualiza nada.
        - si cambian mas de MAX_CAMBIOS casillas de golpe: es un brazo o una mano, se ignora."""
        if self.fondo_rect is None:
            return
        ocup, color, self.frac, self.fbor = analizar(rect, self.fondo_rect)
        self.raw, self.raw_color = ocup, color
        self.ocluido = False
        if congelado:
            self.cuenta[:] = 0
            return
        if self.sin_lectura_inicial:
            self.aceptar_lectura()
            self.sin_lectura_inicial = False
            return
        cambia = ocup != self.estable
        if cambia.sum() > MAX_CAMBIOS:
            self.cuenta[:] = 0
            self.ocluido = True
            return
        self.cuenta[cambia] += 1
        self.cuenta[~cambia] = 0
        ok = self.cuenta >= FRAMES_ESTABLES
        self.estable[ok] = ocup[ok]
        self.cuenta[ok] = 0
        self.color[ocup] = color[ocup]

    def aceptar_lectura(self):
        """Toma la ultima lectura de la camara como el estado real (con el brazo en reposo)."""
        self.estable[:] = self.raw
        self.color[:] = np.where(self.raw, self.raw_color, "")
        self.cuenta[:] = 0

    def aplicar_movimiento(self, origen, destino):
        """Tras un movimiento del robot: el origen queda libre y el destino ocupado (la camara lo confirmara)."""
        co, ro = indices(origen)
        cd, rd = indices(destino)
        self.estable[rd, cd] = True
        self.color[rd, cd] = self.color[ro, co]
        self.estable[ro, co] = False
        self.color[ro, co] = ""
        self.cuenta[:] = 0

    def ocupada(self, nombre):
        col, row = indices(nombre)
        return bool(self.estable[row, col])

    # --- persistencia ---
    def guardar(self):
        with open(ARCHIVO_CALIB, "w") as f:
            json.dump({"esquinas": [[int(x), int(y)] for x, y in self.esquinas], "rot": self.rot}, f)
        if self.fondo_raw is not None:
            cv2.imwrite(ARCHIVO_FONDO, self.fondo_raw)

    def cargar(self):
        if not os.path.exists(ARCHIVO_CALIB):
            return False
        with open(ARCHIVO_CALIB) as f:
            d = json.load(f)
        self.esquinas = [tuple(p) for p in d["esquinas"]]
        self.rot = int(d.get("rot", 0))
        if os.path.exists(ARCHIVO_FONDO):
            self.fondo_raw = cv2.imread(ARCHIVO_FONDO)
        return self.calibrar()


# ---------------------------------------------------------------------
# Dibujo
# ---------------------------------------------------------------------
def texto(img, s, org, escala=0.5, color=BLANCO, grosor=1):
    cv2.putText(img, s, org, FONT, escala, (0, 0, 0), grosor + 2, cv2.LINE_AA)
    cv2.putText(img, s, org, FONT, escala, color, grosor, cv2.LINE_AA)


def dibujar_tablero(rect, t, origen=None, debug=False):
    out = rect.copy()
    capa = out.copy()
    for row in range(8):
        for col in range(8):
            if t.estable[row, col]:
                c = VERDE if t.color[row, col] == "R" else NARANJA
                cv2.rectangle(capa, (col * STEP + 3, row * STEP + 3),
                              ((col + 1) * STEP - 3, (row + 1) * STEP - 3), c, -1)
    out = cv2.addWeighted(capa, 0.35, out, 0.65, 0)

    for k in range(9):
        cv2.line(out, (k * STEP, 0), (k * STEP, BOARD_PIXELS), (60, 60, 60), 1)
        cv2.line(out, (0, k * STEP), (BOARD_PIXELS, k * STEP), (60, 60, 60), 1)

    for row in range(8):
        for col in range(8):
            x, y = col * STEP, row * STEP
            n = nombre_casilla(col, row)
            texto(out, n, (x + 22, y + 46), 0.65, BLANCO, 1)
            if t.estable[row, col]:
                texto(out, t.color[row, col], (x + STEP - 18, y + 16), 0.5, BLANCO, 1)
            if debug:
                texto(out, f"{t.frac[row, col] * 100:.0f}/{t.fbor[row, col] * 100:.0f}",
                      (x + 4, y + STEP - 6), 0.38, AMARILLO, 1)
    if origen:
        c, r = indices(origen)
        cv2.rectangle(out, (c * STEP + 2, r * STEP + 2), ((c + 1) * STEP - 2, (r + 1) * STEP - 2), AMARILLO, 3)
    cv2.line(out, (0, BOARD_PIXELS - 2), (BOARD_PIXELS, BOARD_PIXELS - 2), ROJO, 3)
    texto(out, "LADO DEL ROBOT", (BOARD_PIXELS // 2 - 70, BOARD_PIXELS - 8), 0.5, ROJO, 1)
    return out


def dibujar_camara(frame, t, ayuda=""):
    d = frame.copy()
    for i, p in enumerate(t.esquinas):
        cv2.circle(d, (int(p[0]), int(p[1])), 7, (0, 0, 255), -1)
        texto(d, str(i + 1), (int(p[0]) + 8, int(p[1]) - 8), 0.7, (0, 0, 255), 2)
    if t.Hinv is not None:
        for k in range(9):
            a = k * STEP
            for p0, p1 in (((a, 0), (a, BOARD_PIXELS)), ((0, a), (BOARD_PIXELS, a))):
                q = proyectar([p0, p1], t.Hinv).astype(int)
                cv2.line(d, tuple(q[0]), tuple(q[1]), (0, 255, 255), 1)
        centros = [((c + 0.5) * STEP, (r + 0.5) * STEP) for r in range(8) for c in range(8)]
        for (c, r), q in zip([(c, r) for r in range(8) for c in range(8)], proyectar(centros, t.Hinv)):
            texto(d, nombre_casilla(c, r), (int(q[0]) - 10, int(q[1]) + 5), 0.4, (0, 255, 255), 1)
    if ayuda:
        texto(d, ayuda, (10, 25), 0.6, AMARILLO, 2)
    return d


# ---------------------------------------------------------------------
# Aplicacion
# ---------------------------------------------------------------------
class App:
    def __init__(self, brazo):
        self.t = Tablero()
        self.brazo = brazo
        self.origen = None
        self.entrada = ""
        self.modo_jugada = False
        self.debug = False
        self.mensaje = ("", BLANCO, 0)
        self.verificar = None
        self.libre_desde = 0.0

    def congelado(self):
        """No se lee el tablero mientras el robot se mueve (el brazo tapa casillas) ni justo despues."""
        return self.brazo.ocupado or time.time() < self.libre_desde

    def procesar(self, rect):
        self.t.procesar(rect, congelado=self.congelado())

    def msg(self, s, color=BLANCO, dur=5.0):
        self.mensaje = (s, color, time.time() + dur)

    # ---- mouse ----
    def clic_camara(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(self.t.esquinas) < 4:
            self.t.esquinas.append((x, y))
            print(f"Esquina {len(self.t.esquinas)}: ({x}, {y})")
            if len(self.t.esquinas) == 4:
                self.msg("4 esquinas listas. Pulsa C para rectificar", AMARILLO)

    def clic_tablero(self, event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN or self.t.H is None:
            return
        if not (0 <= x < BOARD_PIXELS and 0 <= y < BOARD_PIXELS):
            return
        self.ingresar_casilla(nombre_casilla(min(7, x // STEP), min(7, y // STEP)))

    # ---- jugada ----
    def ingresar_casilla(self, nombre):
        if self.origen is None:
            self.origen = nombre
            self.msg(f"Origen {nombre}. Elige el DESTINO", AMARILLO, 30)
        else:
            origen, self.origen = self.origen, None
            self.solicitar(origen, nombre)

    def validar(self, origen, destino):
        """Devuelve (ok, mensaje, conservar_origen)."""
        t = self.t
        if self.brazo.ocupado:
            return False, "Robot ocupado: espera a que termine", False
        if t.fondo_rect is None:
            return False, "Falta capturar el tablero VACIO (tecla E)", False
        if origen == destino:
            return False, "Origen y destino son la misma casilla", False
        if not t.ocupada(origen):
            return False, f"No hay pieza en {origen}", False
        if t.ocupada(destino):
            return False, f"{destino} esta OCUPADA: no se puede mover ahi. Elige otra casilla", True
        try:
            robot.planificar(origen, destino)
        except robot.FueraDeAlcance as e:
            return False, f"Fuera de alcance: {e}", False
        return True, "", False

    def solicitar(self, origen, destino):
        ok, texto_error, conservar = self.validar(origen, destino)
        if not ok:
            print("RECHAZADO:", texto_error)
            self.msg(texto_error, ROJO, 8)
            if conservar:
                self.origen = origen          # solo falta elegir otro destino
            return
        self.msg(f"Moviendo {origen} -> {destino}", VERDE, 60)
        print(f"Moviendo {origen} -> {destino}")
        self.brazo.ocupado = True             # bloquea nuevas ordenes de inmediato

        def tarea():
            try:
                self.brazo.mover_pieza(origen, destino,
                                       progreso=lambda s: self.msg(f"{origen}->{destino}: {s}", VERDE, 60))
                self.brazo.ocupado = True                # sigue congelado mientras se actualiza el estado
                self.t.aplicar_movimiento(origen, destino)
                self.libre_desde = time.time() + DESCANSO_S
                self.msg(f"Listo {origen} -> {destino}. Verificando con la camara...", VERDE, 10)
                self.verificar = (time.time() + VERIF_ESPERA_S, origen, destino)
            except robot.Abortado:
                self.msg("Movimiento DETENIDO (revisa el tablero y pulsa U para releer)", ROJO, 15)
            except Exception as e:
                print("ERROR del robot:", e)
                self.msg(f"Error del robot: {e}", ROJO, 15)
            finally:
                self.libre_desde = time.time() + DESCANSO_S
                self.brazo.ocupado = False

        threading.Thread(target=tarea, daemon=True).start()

    def revisar_verificacion(self):
        if not self.verificar or time.time() < self.verificar[0]:
            return
        _, o, d = self.verificar
        self.verificar = None
        if self.t.ocupada(d) and not self.t.ocupada(o):
            self.msg(f"Verificado por camara: pieza en {d}, {o} libre", VERDE, 10)
        else:
            self.msg(f"ATENCION: la camara no confirma el movimiento {o}->{d}", ROJO, 15)

    # ---- teclado ----
    def teclado(self, key, frame):
        """Devuelve False para salir."""
        if key == 255:
            return True
        c = chr(key).lower()
        if c == "x":
            self.brazo.parar()
            self.msg("PARADA DE EMERGENCIA", ROJO, 10)
            return True
        if self.modo_jugada:
            if key == 27:
                self.modo_jugada, self.entrada, self.origen = False, "", None
                self.msg("Modo jugada terminado")
            elif key in (8, 127):
                if self.entrada:
                    self.entrada = self.entrada[:-1]
                else:
                    self.origen = None
            else:
                ch = c.upper()
                if (len(self.entrada) == 0 and ch in "ABCDEFGH") or \
                   (len(self.entrada) == 1 and ch in "12345678"):
                    self.entrada += ch
                    if len(self.entrada) == 2:
                        nombre, self.entrada = self.entrada, ""
                        self.ingresar_casilla(nombre)
            return True

        if key == 27 or c == "q":
            return False
        t = self.t
        if c == "r":
            t.reiniciar()
            self.origen = None
            self.msg("Reiniciado. Haz clic en las 4 esquinas", AMARILLO)
        elif c == "c":
            if t.calibrar():
                t.guardar()
                self.msg("Calibrado. Pulsa O hasta que A1 quede abajo-izq (lado del robot)", AMARILLO, 15)
            else:
                self.msg("Faltan esquinas (haz 4 clics en la camara)", ROJO)
        elif c == "e" and t.H is not None:
            t.capturar_fondo(frame)
            t.guardar()
            self.msg("Tablero vacio capturado", VERDE)
        elif c == "o" and t.H is not None:
            t.rotar()
            t.guardar()
            self.msg(f"Orientacion {t.rot * 90} deg: A1 debe quedar abajo-izq (lado del robot)", AMARILLO, 8)
        elif c == "m":
            self.modo_jugada = True
            self.msg("Modo jugada: escribe origen y destino (ej. E 3 G 5)", AMARILLO, 10)
        elif c == "t" and t.H is not None:
            exportar_mapa(t)
            self.msg(f"Mapa guardado en {ARCHIVO_MAPA}", VERDE)
        elif c == "u" and t.fondo_rect is not None:
            t.aceptar_lectura()
            self.msg("Lectura actual aceptada como estado real del tablero", VERDE)
        elif c == "d":
            self.debug = not self.debug
        return True

    # ---- vistas ----
    def vista_camara(self, frame):
        t = self.t
        if len(t.esquinas) < 4:
            ayuda = f"Clic en las 4 esquinas del tablero ({len(t.esquinas)}/4)"
        elif t.H is None:
            ayuda = "Pulsa C para rectificar"
        elif t.fondo_rect is None:
            ayuda = "Quita las piezas y pulsa E (tablero vacio)"
        else:
            ayuda = ""
        return dibujar_camara(frame, t, ayuda)

    def vista_tablero(self, rect):
        out = dibujar_tablero(rect, self.t, self.origen, self.debug)
        if self.congelado():
            texto(out, "ROBOT MOVIENDO - lectura congelada", (BOARD_PIXELS // 2 - 160, 20), 0.6, ROJO, 2)
        elif self.t.ocluido:
            texto(out, "TAPADO (mano o brazo): sin actualizar", (BOARD_PIXELS // 2 - 170, 20), 0.6, ROJO, 2)
        barra = np.zeros((BARRA_PX, BOARD_PIXELS, 3), np.uint8)
        if self.modo_jugada:
            l1 = f"JUGADA  origen: {self.origen or '--'}  escribiendo: {self.entrada or '_'}  (X=parar Esc=salir)"
        else:
            l1 = "C calib E vacio O girar M jugada U leer T mapa D diag R reinic Q salir"
        texto(barra, l1, (6, 22), 0.45, BLANCO, 1)
        s, color, hasta = self.mensaje
        if s and time.time() < hasta:
            texto(barra, s[:70], (6, 52), 0.5, color, 1)
        return np.vstack([out, barra])


def exportar_mapa(t):
    """Guarda las 64 casillas (nombre, centro en pixeles, centro en mm, ocupacion) y las muestra."""
    centros = [((c + 0.5) * STEP, (r + 0.5) * STEP) for r in range(8) for c in range(8)]
    cam = proyectar(centros, t.Hinv)
    with open(ARCHIVO_MAPA, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["casilla", "rect_x", "rect_y", "camara_x", "camara_y", "x_mm", "y_mm", "ocupada", "color"])
        for i, (c, r) in enumerate([(c, r) for r in range(8) for c in range(8)]):
            n = nombre_casilla(c, r)
            x_mm, y_mm = robot.centro_casilla_mm(n)
            w.writerow([n, int(centros[i][0]), int(centros[i][1]), int(cam[i][0]), int(cam[i][1]),
                        f"{x_mm:.1f}", f"{y_mm:.1f}", int(t.estable[r, c]), t.color[r, c]])
    print("\n    " + " ".join(f" {ch} " for ch in "ABCDEFGH"))
    for r in range(8):
        fila = " ".join(f" {t.color[r, c] if t.estable[r, c] else '.'} " for c in range(8))
        print(f" {8 - r}  {fila}")
    print(f"\nMapa guardado en {ARCHIVO_MAPA}")


def abrir_camara(idx):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(idx)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUCION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUCION[1])
    if BLOQUEAR_ENFOQUE:
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    if FOCO_MANUAL is not None:
        cap.set(cv2.CAP_PROP_FOCUS, FOCO_MANUAL)
    return cap


def listar_camaras():
    """Prueba los indices 0..5 y dice cuales abren y entregan imagen."""
    print("Buscando camaras (indices 0 a 5)...")
    hallada = False
    for i in range(6):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(i)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok:
                print(f"  --camara {i}: funciona ({frame.shape[1]}x{frame.shape[0]})")
                hallada = True
        cap.release()
    if not hallada:
        print("  No se encontro ninguna. Revisa: cable USB, que otro programa (Zoom, Teams, la app de "
              "Camara) no la este usando, y los permisos de camara de Windows.")
    else:
        print("Usa el numero que corresponda a TU camara web (0 suele ser la del portatil, 1 la externa).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camara", type=int, default=CAMERA_INDEX)
    ap.add_argument("--puerto", help="puerto del Arduino (ej. COM5). Sin puerto = simulacion")
    ap.add_argument("--listar", action="store_true", help="prueba los numeros de camara y sale")
    args = ap.parse_args()
    if args.listar:
        listar_camaras()
        return

    try:
        brazo = robot.Brazo(args.puerto)
    except RuntimeError as e:
        print("ERROR:", e)
        return
    if args.puerto:
        if not robot.confirmar_encendido():
            return
        try:
            brazo.activar()
        except (RuntimeError, TimeoutError) as e:
            print("ERROR:", e)
            return

    cap = abrir_camara(args.camara)
    if cap is None:
        print("Error: no se pudo abrir la camara", args.camara)
        return

    app = App(brazo)
    if app.t.cargar():
        print("Calibracion anterior cargada (si la camara se movio, pulsa R y recalibra).")
        app.msg("Calibracion cargada. Revisa que el cuadro calce con el tablero", AMARILLO, 10)

    cv2.namedWindow(WINDOW_CAMERA)
    cv2.namedWindow(WINDOW_BOARD)
    cv2.setMouseCallback(WINDOW_CAMERA, app.clic_camara)
    cv2.setMouseCallback(WINDOW_BOARD, app.clic_tablero)

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Error: la camara dejo de responder")
            break
        cv2.imshow(WINDOW_CAMERA, app.vista_camara(frame))
        if app.t.H is not None:
            rect = app.t.rectificar(frame)
            app.procesar(rect)
            cv2.imshow(WINDOW_BOARD, app.vista_tablero(rect))
        app.revisar_verificacion()
        if not app.teclado(cv2.waitKey(1) & 0xFF, frame):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()