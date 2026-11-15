"""
juego.py - Interfaz de juego: tablero con lo que ve la camara + ORIGEN / DESTINO + boton JUGAR
==============================================================================================
Une los dos programas en uno solo (usa vision_tablero.py y robot.py, sin tocarlos):

   camara -> que casillas tienen pieza -> se comprueba la jugada -> el robot la hace -> la camara la verifica

Antes de dejar jugar comprueba, con lo que ve la camara AHORA:
   1. la casilla de ORIGEN tiene pieza           (si esta vacia: no se puede)
   2. la casilla de DESTINO esta libre           (si esta ocupada: no se puede, elige otra)
   3. el brazo llega a esas casillas (estan ensenadas o se calculan)
   4. el tablero no esta tapado por una mano o el brazo y la lectura es estable
   5. el robot no esta ocupado con otro movimiento

Uso:
    python juego.py --listar                       (que numero de camara funciona)
    python juego.py --camara 1                     (simulacion, sin robot)
    python juego.py --camara 1 --puerto COM6       (con robot)

Primera vez (ventana de la camara): clic en las 4 esquinas, C, O hasta que A1 quede abajo-izquierda
(lado del robot), quita las piezas y pulsa E, vuelve a poner las piezas. Se guarda y no hay que repetirlo
mientras la camara no se mueva (si se mueve: R y recalibrar).

En la ventana del juego: clic en una casilla = ORIGEN, otro clic = DESTINO, boton JUGAR (o tecla J).
Teclas: J jugar | L limpiar | X PARADA | U releer el tablero | D diagnostico | Q salir
"""
import argparse
import textwrap
import threading
import time

import cv2
import numpy as np

import robot
import vision_tablero as V

# NUEVAS IMPORTACIONES PARA CLASIFICADOR DE PIEZAS
import chess
import clasificador
import json
import os


if not hasattr(robot.Brazo, "retirar"):
    raise SystemExit("Actualiza robot.py: falta la pose de retirada (Brazo.retirar).")

VENTANA = "Ajedrez robot"
PANEL_W = 360
ARCHIVO_TOP = "calibracion_top.json"
ALTO = V.BOARD_PIXELS
FONDO = (38, 38, 38)
GRIS = (110, 110, 110)
GRIS_CLARO = (170, 170, 170)


class Juego(V.App):
    def __init__(self, brazo):
        self.clf = clasificador.Clasificador()
        self.logico = chess.Board()         # tablero logico (posicion inicial)
        self.mi_color = chess.WHITE         # tu lado (filas 1-2), sea rojo o negro     
        self.destinos = set()
        self.tipos = {}
        self.frame = None
        self.calib_top = None
        self.H_top = None
        if os.path.exists(ARCHIVO_TOP):
            with open(ARCHIVO_TOP) as f:
                self.H_top = np.array(json.load(f), np.float32)
        super().__init__(brazo)
        self.sel_o = None
        self.sel_d = None
        x0, x1 = V.BOARD_PIXELS + 20, V.BOARD_PIXELS + PANEL_W - 20
        mitad = (x0 + x1) // 2
        self.botones = [
            {"rect": (x0, 440, x1, 505), "texto": "JUGAR", "color": V.VERDE, "accion": self.jugar, "id": "jugar"},
            {"rect": (x0, 518, mitad - 8, 558), "texto": "LIMPIAR", "color": GRIS, "accion": self.limpiar, "id": "limpiar"},
            {"rect": (mitad + 8, 518, x1, 558), "texto": "PARAR", "color": V.ROJO, "accion": self.parar, "id": "parar"},
            {"rect": (x0, 572, mitad - 8, 612), "texto": "REPOSO SEGURO", "color": (0, 120, 200), "accion": self.reposo_seguro, "id": "reposo"},
            {"rect": (mitad + 8, 572, x1, 612), "texto": "RETIRAR BRAZO", "color": (150, 100, 0), "accion": self.retirar_brazo, "id": "retirar"},
        ]

    # ---------------- seleccion ----------------
    def seleccionar(self, nombre):
        if self.sel_o is None or self.sel_d is not None:
            self.sel_o, self.sel_d = nombre, None
        elif nombre == self.sel_o:
            self.sel_o = None
        else:
            self.sel_d = nombre
            self.destinos = (self.casillas_legales(self.sel_o) or set()) if (self.sel_o and not self.sel_d) else set()

    def ingresar_casilla(self, nombre):                        # tambien las que se escriben con M
        self.seleccionar(nombre)

    def limpiar(self):
        self.sel_o = self.sel_d = None
        self.destinos = set()

    # ---------------- comprobaciones ----------------
    def estado_jugada(self):
        """(ok, texto, color, que_limpiar) segun lo que ve la camara AHORA.
        que_limpiar si falla: 'nada' (motivo pasajero), 'destino' (elegir otro destino) o 'todo'."""
        t, o, d = self.t, self.sel_o, self.sel_d
        if o is None:
            return False, "Elige la casilla de ORIGEN (clic en el tablero).", V.BLANCO, "nada"
        if d is None:
            if t.fondo_rect is not None and not t.ocupada(o):
                return False, f"En {o} NO hay pieza (segun la camara). Elige otro origen.", V.ROJO, "todo"
            if t.fondo_rect is not None:
                return False, f"Origen {o} con pieza. Ahora elige la casilla de DESTINO.", V.AMARILLO, "nada"
            return False, f"Origen {o}. Ahora elige el DESTINO.", V.AMARILLO, "nada"
        if self.brazo.ocupado:
            return False, "Robot ocupado: espera a que termine el movimiento.", V.NARANJA, "nada"
        if t.fondo_rect is None:
            return False, "Falta capturar el tablero VACIO (tecla E en la ventana de la camara).", V.ROJO, "nada"
        ok, texto, conservar = self.validar(o, d)
        if not ok:
            return False, texto, V.ROJO, ("destino" if conservar else "todo")
        if t.ocluido:
            return False, "El tablero esta TAPADO (mano o brazo). Espera un momento.", V.ROJO, "nada"
        if self.congelado():
            return False, "Estabilizando la lectura de la camara...", V.AMARILLO, "nada"
        if (t.cuenta > 0).any():
            return False, "Leyendo el tablero, espera un instante...", V.AMARILLO, "nada"
        return True, f"{o} -> {d}: origen con pieza y destino libre. Listo para JUGAR.", V.VERDE, "nada"

    # ---------------- ajedrez ----------------
    def casillas_legales(self, nombre):
        """Casillas a las que puede ir esa pieza tuya, o None si no es tuya."""
        sq = chess.parse_square(nombre.lower())
        p = self.logico.piece_at(sq)
        if p is None or p.color != self.mi_color:
            return None
        self.logico.turn = self.mi_color
        return {chess.square_name(m.to_square).upper() for m in self.logico.legal_moves
                if m.from_square == sq and not self.logico.is_capture(m)
                and not self.logico.is_castling(m)}      # capturas y enroque: mas adelante

    def validar(self, origen, destino):
        ok, texto, conservar = super().validar(origen, destino)
        if not ok:
            return ok, texto, conservar
        legales = self.casillas_legales(origen)
        if legales is None:
            return False, f"{origen} no es una pieza tuya", False
        if destino not in legales:
            return False, f"Esa pieza no puede ir a {destino}. Posibles: {' '.join(sorted(legales)) or 'ninguna'}", True
        return True, "", False

    def registrar_jugada(self, o, d):
        a, b = chess.parse_square(o.lower()), chess.parse_square(d.lower())
        self.logico.turn = self.mi_color
        m = next((m for m in self.logico.legal_moves if m.from_square == a and m.to_square == b), None)
        if m:
            self.logico.push(m)
        self.logico.turn = self.mi_color

    def revisar_verificacion(self):
        v = self.verificar
        super().revisar_verificacion()
        if v and time.time() >= v[0] and self.t.ocupada(v[2]) and not self.t.ocupada(v[1]):
            self.registrar_jugada(v[1], v[2])           # la camara confirmo: se anota la jugada

    # ---------------- reconocimiento ----------------
    def equipo_propio(self):
        vals = [x for x in self.t.color[6:8, :].flatten() if x]   # filas 2 y 1 (indices 6 y 7)
        return max(set(vals), key=vals.count) if vals else None

    def procesar(self, rect):
        super().procesar(rect)
        self.tipos = {}
        eq = self.equipo_propio()
        if eq is None or not self.clf.listo():
            return
        rc = self.rect_clasif(rect)
        for row in range(8):
            for col in range(8):
                if self.t.estable[row, col] and self.t.color[row, col] == eq:
                    tp, conf = self.clf.predecir(clasificador.recorte(rc, col, row, V.STEP))

    def entrenar(self, rect):
        eq = self.equipo_propio()
        muestras = []
        for fila in (1, 2):
            for col in "ABCDEFGH":
                n = f"{col}{fila}"
                if self.t.ocupada(n) and self.t.color[V.indices(n)[1], V.indices(n)[0]] == eq:
                    c, r = V.indices(n)
                    muestras.append((clasificador.recorte(rect, c, r, V.STEP), clasificador.tipo_inicial(n)))
        if len(muestras) != 16:
            self.msg(f"Hay {len(muestras)} piezas de tu equipo en filas 1-2 (deben ser 16). No se entreno.", V.ROJO, 8)
            return
        self.clf.agregar_lote(muestras)
        self.msg("Entrenado con la posicion inicial (16 piezas). Repite moviendo un poco las tablitas.", V.VERDE, 8)
#--------------------------- RECONOCIMIENTO DE PIEZAS---------------------------    
    # ---------------- ajedrez ----------------
    def casillas_legales(self, nombre):
        """Casillas a las que puede ir esa pieza tuya, o None si no es tuya."""
        sq = chess.parse_square(nombre.lower())
        p = self.logico.piece_at(sq)
        if p is None or p.color != self.mi_color:
            return None
        self.logico.turn = self.mi_color
        return {chess.square_name(m.to_square).upper() for m in self.logico.legal_moves
                if m.from_square == sq and not self.logico.is_capture(m)
                and not self.logico.is_castling(m)}      # capturas y enroque: mas adelante

    def validar(self, origen, destino):
        ok, texto, conservar = super().validar(origen, destino)
        if not ok:
            return ok, texto, conservar
        legales = self.casillas_legales(origen)
        if legales is None:
            return False, f"{origen} no es una pieza tuya", False
        if destino not in legales:
            return False, f"Esa pieza no puede ir a {destino}. Posibles: {' '.join(sorted(legales)) or 'ninguna'}", True
        return True, "", False

    def registrar_jugada(self, o, d):
        a, b = chess.parse_square(o.lower()), chess.parse_square(d.lower())
        self.logico.turn = self.mi_color
        m = next((m for m in self.logico.legal_moves if m.from_square == a and m.to_square == b), None)
        if m:
            self.logico.push(m)
        self.logico.turn = self.mi_color

    def revisar_verificacion(self):
        v = self.verificar
        super().revisar_verificacion()
        if v and time.time() >= v[0] and self.t.ocupada(v[2]) and not self.t.ocupada(v[1]):
            self.registrar_jugada(v[1], v[2])           # la camara confirmo: se anota la jugada

    # ---------------- reconocimiento ----------------
    def equipo_propio(self):
        vals = [x for x in self.t.color[6:8, :].flatten() if x]   # filas 2 y 1 (indices 6 y 7)
        return max(set(vals), key=vals.count) if vals else None

    def procesar(self, rect):
        super().procesar(rect)
        self.tipos = {}
        eq = self.equipo_propio()
        if eq is None or not self.clf.listo():
            return
        for row in range(8):
            for col in range(8):
                if self.t.estable[row, col] and self.t.color[row, col] == eq:
                    tp, conf = self.clf.predecir(clasificador.recorte(rect, col, row, V.STEP))
                    if tp:
                        self.tipos[V.nombre_casilla(col, row)] = (tp, conf)

    def entrenar(self, rect):
        eq = self.equipo_propio()
        muestras = []
        for fila in (1, 2):
            for col in "ABCDEFGH":
                n = f"{col}{fila}"
                if self.t.ocupada(n) and self.t.color[V.indices(n)[1], V.indices(n)[0]] == eq:
                    c, r = V.indices(n)
                    muestras.append((clasificador.recorte(rect, c, r, V.STEP), clasificador.tipo_inicial(n)))
        if len(muestras) != 16:
            self.msg(f"Hay {len(muestras)} piezas de tu equipo en filas 1-2 (deben ser 16). No se entreno.", V.ROJO, 8)
            return
        self.clf.agregar_lote(muestras)
        self.msg("Entrenado con la posicion inicial (16 piezas). Repite moviendo un poco las tablitas.", V.VERDE, 8)
    # ---------------- acciones ----------------
    def jugar(self):
        ok, texto, color, limpiar = self.estado_jugada()
        if not ok:
            print("RECHAZADO:", texto)
            self.msg(texto, V.ROJO, 8)
            if limpiar == "destino":
                self.sel_d = None                       # el origen vale: solo falta otro destino
            elif limpiar == "todo":
                self.limpiar()
            return                                      # 'nada': la seleccion se queda para reintentar
        o, d = self.sel_o, self.sel_d
        self.limpiar()
        self.solicitar(o, d)

    def parar(self):
        self.brazo.parar()
        self.msg("PARADA DE EMERGENCIA", V.ROJO, 10)

    def _en_hilo(self, hacer, ok_msg):
        if self.brazo.ocupado:
            self.msg("Robot ocupado: espera a que termine", V.ROJO, 6)
            return
        self.brazo.ocupado = True

        def tarea():
            try:
                hacer()
                self.msg(ok_msg, V.VERDE, 15)
            except Exception as e:
                print("ERROR del robot:", e)
                self.msg(f"Error del robot: {e}", V.ROJO, 15)
            finally:
                self.libre_desde = time.time() + V.DESCANSO_S
                self.brazo.ocupado = False

        threading.Thread(target=tarea, daemon=True).start()

    def reposo_seguro(self):
        self._en_hilo(self.brazo.reposo, "Brazo en REPOSO SEGURO (apoyado). Ya puedes apagar la fuente.")

    def retirar_brazo(self):
        self._en_hilo(self.brazo.retirar, "Brazo retirado (fuera del encuadre de la camara).")

    # ---------------- entrada ----------------
    def clic(self, event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if x < V.BOARD_PIXELS and y < V.BOARD_PIXELS:
            if self.t.H is not None:
                self.seleccionar(V.nombre_casilla(min(7, x // V.STEP), min(7, y // V.STEP)))
            return
        for b in self.botones:
            x1, y1, x2, y2 = b["rect"]
            if x1 <= x <= x2 and y1 <= y <= y2:
                b["accion"]()
                return

    def teclado(self, key, frame):
        if key != 255:
            c = chr(key).lower()
            if c == "j":
                self.jugar()
                return True
            if c == "l":
                self.limpiar()
                return True
            if c == "p":
                self.entrenar(self.rect_clasif(self.t.rectificar(frame)))
                return True
            if c == "h":
                self.calib_top = []
                self.msg("Clic en el CENTRO del sticker de A1, H1, H8 y A8 (en ese orden)", V.AMARILLO, 30)
                return True
        return super().teclado(key, frame)

    # ---------------- dibujo ----------------
    def _caja(self, panel, titulo, valor, rect, color, activa):
        x1, y1, x2, y2 = rect
        cv2.rectangle(panel, (x1, y1), (x2, y2), color if activa else GRIS, 3 if activa else 1)
        V.texto(panel, titulo, (x1 + 10, y1 + 20), 0.5, GRIS_CLARO, 1)
        V.texto(panel, valor, (x1 + 10, y2 - 12), 1.0, color if valor != "--" else GRIS, 2)

    def render(self, rect):
        t = self.t
        if rect is None:
            tab = np.full((ALTO, V.BOARD_PIXELS, 3), (70, 70, 70), np.uint8)
            pasos = ["Falta calibrar el tablero.", "En la ventana de la camara:", "1) clic en las 4 esquinas",
                     "2) pulsa C", "3) pulsa O hasta que A1", "    quede abajo-izquierda", "4) quita las piezas, pulsa E"]
            for i, linea in enumerate(pasos):
                V.texto(tab, linea, (40, 200 + 34 * i), 0.7, V.BLANCO, 1)
        else:
            tab = V.dibujar_tablero(rect, t, None, self.debug)
            for nombre, color, rotulo in ((self.sel_o, V.AMARILLO, "ORIGEN"), (self.sel_d, V.CIAN, "DESTINO")):
                if nombre:
                    c, r = V.indices(nombre)
                    cv2.rectangle(tab, (c * V.STEP + 2, r * V.STEP + 2),
                                  ((c + 1) * V.STEP - 2, (r + 1) * V.STEP - 2), color, 4)
                    V.texto(tab, rotulo, (c * V.STEP + 6, (r + 1) * V.STEP - 8), 0.4, color, 1)
            for n in self.destinos:
                c, r = V.indices(n)
                cv2.circle(tab, (c * V.STEP + V.STEP // 2, r * V.STEP + V.STEP // 2), 10, V.VERDE, -1)
            for n, (tp, conf) in self.tipos.items():
                c, r = V.indices(n)
                esp = self.logico.piece_at(chess.parse_square(n.lower()))
                ok_tipo = esp is not None and esp.symbol().upper() == tp
                V.texto(tab, tp, (c * V.STEP + 6, r * V.STEP + 20), 0.6, V.VERDE if ok_tipo else V.ROJO, 2)
                
            if self.congelado():
                V.texto(tab, "ROBOT MOVIENDO - lectura congelada", (V.BOARD_PIXELS // 2 - 160, 20), 0.6, V.ROJO, 2)
            elif t.ocluido:
                V.texto(tab, "TAPADO (mano o brazo): sin actualizar", (V.BOARD_PIXELS // 2 - 170, 20), 0.6, V.ROJO, 2)

        panel = np.full((ALTO, PANEL_W, 3), FONDO, np.uint8)
        x0, x1 = 20, PANEL_W - 20
        V.texto(panel, "AJEDREZ ROBOT", (x0, 38), 0.9, V.BLANCO, 2)
        V.texto(panel, "Clic en el tablero: 1) origen  2) destino", (x0, 64), 0.45, GRIS_CLARO, 1)
        self._caja(panel, "ORIGEN", self.sel_o or "--", (x0, 80, x1, 148), V.AMARILLO, self.sel_o is None)
        self._caja(panel, "DESTINO", self.sel_d or "--", (x0, 158, x1, 226), V.CIAN, self.sel_o is not None and self.sel_d is None)

        ok, texto, color, _ = self.estado_jugada()
        y = 252
        for linea in textwrap.wrap(texto, 34)[:3]:
            V.texto(panel, linea, (x0, y), 0.55, color, 1)
            y += 24
        if self.sel_o in self.tipos:
            V.texto(panel, f"Pieza vista: {clasificador.NOMBRES[self.tipos[self.sel_o][0]]}", (x0, 316), 0.55, V.CIAN, 1)
        V.texto(panel, "ROBOT: MOVIENDO" if self.brazo.ocupado else "ROBOT: listo", (x0, 340), 0.5,
                V.NARANJA if self.brazo.ocupado else V.VERDE, 1)
        if t.H is None or t.fondo_rect is None:
            cam, ccol = "CAMARA: falta calibrar / tablero vacio (E)", V.ROJO
        elif t.ocluido:
            cam, ccol = "CAMARA: tablero tapado", V.ROJO
        elif self.congelado():
            cam, ccol = "CAMARA: lectura congelada", V.NARANJA
        else:
            cam, ccol = "CAMARA: leyendo bien", V.VERDE
        V.texto(panel, cam, (x0, 364), 0.5, ccol, 1)
        s, scol, hasta = self.mensaje
        if s and time.time() < hasta:
            y = 394
            for linea in textwrap.wrap(s, 40)[:2]:
                V.texto(panel, linea, (x0, y), 0.45, scol, 1)
                y += 20

        for b in self.botones:
            x1b, y1b, x2b, y2b = b["rect"]
            col = b["color"] if (b["id"] != "jugar" or ok) else (80, 80, 80)
            cv2.rectangle(panel, (x1b - V.BOARD_PIXELS, y1b), (x2b - V.BOARD_PIXELS, y2b), col, -1)
            esc = 1.0 if b["id"] == "jugar" else 0.5
            (w, h), _ = cv2.getTextSize(b["texto"], V.FONT, esc, 2 if b["id"] == "jugar" else 1)
            cx = (x1b + x2b) // 2 - V.BOARD_PIXELS
            V.texto(panel, b["texto"], (cx - w // 2, (y1b + y2b) // 2 + h // 2), esc, V.BLANCO,
                    2 if b["id"] == "jugar" else 1)
        return np.hstack([tab, panel])


#metodos nuevos
    def rect_clasif(self, rect):
        """Vista rectificada a la altura de los stickers (si se calibro), si no la normal."""
        if self.H_top is None or self.frame is None:
            return rect
        return cv2.warpPerspective(self.frame, self.H_top, (V.BOARD_PIXELS, V.BOARD_PIXELS))

    def clic_camara(self, event, x, y, flags, param):
        if self.calib_top is None:
            return super().clic_camara(event, x, y, flags, param)
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        self.calib_top.append((x, y))
        if len(self.calib_top) < 4:
            self.msg(f"Sticker {len(self.calib_top)}/4 guardado", V.AMARILLO, 30)
            return
        s = V.STEP
        dst = np.float32([[0.5 * s, 7.5 * s], [7.5 * s, 7.5 * s], [7.5 * s, 0.5 * s], [0.5 * s, 0.5 * s]])
        self.H_top = cv2.getPerspectiveTransform(np.float32(self.calib_top), dst)
        self.calib_top = None
        with open(ARCHIVO_TOP, "w") as f:
            json.dump(self.H_top.tolist(), f)
        self.msg("Calibracion de altura guardada", V.VERDE, 8)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camara", type=int, default=V.CAMERA_INDEX)
    ap.add_argument("--puerto", help="puerto del Arduino (ej. COM6). Sin puerto = simulacion")
    ap.add_argument("--listar", action="store_true", help="prueba los numeros de camara y sale")
    args = ap.parse_args()
    if args.listar:
        V.listar_camaras()
        return

    try:
        brazo = robot.Brazo(args.puerto)
    except RuntimeError as e:
        print("ERROR:", e)
        return
    if args.puerto:
        if not robot.confirmar_encendido("de RETIRADA (donde lo dejaste, fuera del encuadre de la camara)"):
            return
        try:
            brazo.activar(desde=robot.pose_retirada())
        except (RuntimeError, TimeoutError) as e:
            print("ERROR:", e)
            return

    cap = V.abrir_camara(args.camara)
    if cap is None:
        print("Error: no se pudo abrir la camara", args.camara, "(prueba:  python juego.py --listar)")
    for _ in range(40):          # deja que la camara ajuste exposicion y balance antes de leer el tablero
        cap.read()
        return
    

    app = Juego(brazo)
    app.libre_desde = time.time() + 1.5               # espera a que el brazo termine de retirarse
    if app.t.cargar():
        print("Calibracion anterior cargada (si la camara se movio, pulsa R y recalibra).")
        app.msg("Calibracion cargada. Revisa que el cuadro calce con el tablero", V.AMARILLO, 10)

    cv2.namedWindow(V.WINDOW_CAMERA)
    cv2.namedWindow(VENTANA)
    cv2.setMouseCallback(V.WINDOW_CAMERA, app.clic_camara)
    cv2.setMouseCallback(VENTANA, app.clic)

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Error: la camara dejo de responder")
            break
        cv2.imshow(V.WINDOW_CAMERA, app.vista_camara(frame))
        rect = None
        if app.t.H is not None:
            rect = app.t.rectificar(frame)
            app.procesar(rect)
        cv2.imshow(VENTANA, app.render(rect))
        app.revisar_verificacion()
        if not app.teclado(cv2.waitKey(1) & 0xFF, frame):
            break

    cap.release()
    cv2.destroyAllWindows()
    if args.puerto and brazo.activo:
        if input("Llevar el brazo al REPOSO SEGURO antes de salir? (S/n): ").strip().lower() != "n":
            try:
                brazo.reposo()
                print("Brazo en reposo seguro. Ya puedes apagar la fuente.")
            except (RuntimeError, TimeoutError) as e:
                print("ERROR:", e)


if __name__ == "__main__":
    main()
    
    print("inicio main")