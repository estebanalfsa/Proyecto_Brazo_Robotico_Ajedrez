1. Tiene 6 servomotores   
2. Para ciertos angulos se debe de modificar algun otros servos, pasa que el brazo no es tan largo como para simplemente bajar y tomar la pieza  
3. Si, al menos esta primera etapa solo estaria probando con una, mapeando casilla por casilla  
Mis codigos:  
 """  
teach.py - Ensenarle al robot las casillas, como una maquina de garra  
=====================================================================  
Necesitas UNA sola pieza. El robot la lleva de casilla en casilla (16 en total).  
En cada casilla TU enseñas solo dos posiciones; todo lo demas (soltar, subir, bajar,  
agarrar otra vez) lo hace el robot solo, y de paso comprueba que agarra bien.  
   
EN CADA CASILLA  
  PASO 1  ALTURA SEGURA : llevas la pieza (el robot la lleva agarrada) encima de la casilla.  G = guardar  
  PASO 2  ALTURA DE APOYO: bajas hasta apoyar la pieza en el centro.                         G = guardar  
  Entonces el robot, SOLO: suelta la pieza, sube, baja, la agarra de nuevo y sube.  
  Si agarro bien: G = seguir.   Si no: B = repetir esa casilla.  
   
LA PRIMERA CASILLA (A1) es distinta, porque el robot aun no sabe abrir ni cerrar la pinza:  
  pones la pieza en A1, abres la pinza y la pones encima (G), bajas hasta rodear la pieza (G),  
  cierras hasta SUJETARLA sin apretar de mas (G) y el robot sube solo con ella.  
   
Uso (en una terminal, no en IDLE):  
    python teach.py --puerto COM5            # robot real  
    python teach.py                          # simulacion, para ver como funciona  
    python teach.py --puerto COM5 --rehacer  # empieza de cero (guarda copia de lo anterior en .bak)  
    python teach.py --puerto COM5 --solo C3,H6   # repite solo esas casillas  
   
ORIENTACION (importante): ponte DETRAS del robot, mirando hacia el tablero.  
    A1 = la esquina del tablero MAS CERCANA al robot, a SU IZQUIERDA.  
    H1 = cercana, a su derecha | A8 = lejana, a su izquierda | H8 = lejana, a su derecha.  
    Las filas se cuentan desde el robot (fila 1 = la mas cercana). NO muevas el tablero  
    despues de ensenar (marca su posicion con cinta).  
   
Teclas:  
    A / D   base  -/+            W / S   hombro +/-        E / Q   codo +/-  
    R / F   gancho +/-           Z / C   pinza -/+  (tambien [ y ] )  
    ESPACIO alterna la pinza entre sus dos extremos (los ensenados, cuando ya existen)  
    1 / 2 / 3   tamano del paso (1, 3 o 6 grados)   (mantener una tecla = mover continuo)  
    G guardar y seguir | B volver al paso anterior | L repetir esta ayuda | 0 o Esc salir  
    (con la pieza agarrada la pinza queda bloqueada, para que no se suelte por error)  
"""  
import argparse  
import json  
import os  
import sys  
import time  
   
import robot  
   
ARCHIVO = robot.ARCHIVO_POSES  
PASOS_GRADOS = {"1": 1, "2": 3, "3": 6}  
TECLAS = {  
    "a": (0, -1), "d": (0, +1),  
    "w": (1, +1), "s": (1, -1),  
    "e": (2, +1), "q": (2, -1),  
    "r": (4, +1), "f": (4, -1),  
    "z": (5, -1), "c": (5, +1),        # pinza (en teclado espanol [ y ] cuestan: AltGr)  
    "[": (5, -1), "]": (5, +1),  
}  
SOLO_PINZA = (5,)  
   
class Salir(Exception):  
    pass  
   
class ErrorRobot(Exception):  
    pass  
   
class Teclado:  
    """Lee teclas sin pulsar Enter. Windows: msvcrt. Linux/Mac: termios."""  
   
    def __enter__(self):  
        if os.name != "nt":  
            import termios  
            import tty  
            self.fd = sys.stdin.fileno()  
            self.viejo = termios.tcgetattr(self.fd)  
            tty.setcbreak(self.fd)  
        return self  
   
    def __exit__(self, *args):  
        if os.name != "nt":  
            import termios  
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.viejo)  
   
    def _hay(self):  
        if os.name == "nt":  
            import msvcrt  
            return msvcrt.kbhit()  
        import select  
        return bool(select.select([self.fd], [], [], 0)[0])  
   
    def _char(self):  
        if os.name == "nt":  
            import msvcrt  
            ch = msvcrt.getwch()  
            if ch in ("\x00", "\xe0"):      # tecla especial (flechas...): se descarta  
                msvcrt.getwch()  
                return ""  
            return ch  
        return os.read(self.fd, 1).decode(errors="ignore")  
   
    def leer(self):  
        """Espera una tecla y la devuelve en minuscula."""  
        while True:  
            ch = self._char()  
            if ch:  
                return ch.lower()  
   
    def repeticiones(self, tecla):  
        """Cuenta (y consume) las repeticiones pendientes de la MISMA tecla (tecla mantenida)."""  
        n = 0  
        while self._hay():  
            if self._char().lower() == tecla:  
                n += 1  
        return n  
   
# ---------------------------------------------------------------------  
# Ayudas visuales  
# ---------------------------------------------------------------------  
def orden_casillas():  
    """Recorrido en zigzag para no cruzar el tablero de un lado a otro."""  
    cols = [chr(65 + c) for c in robot.NODOS_IDX]  
    orden = []  
    for i, r in enumerate(robot.NODOS_IDX):  
        for c in (cols if i % 2 == 0 else cols[::-1]):  
            orden.append(f"{c}{r + 1}")  
    return orden  
   
def descripcion(nombre):  
    """Donde esta la casilla, vista desde detras del robot."""  
    c, f = robot.nombre_a_indices(nombre)  
    esquinas = {"A1": "ESQUINA cercana al robot, a su izquierda", "H1": "ESQUINA cercana al robot, a su derecha",  
                "A8": "ESQUINA lejana, a la izquierda del robot", "H8": "ESQUINA lejana, a la derecha del robot"}  
    if nombre in esquinas:  
        return esquinas[nombre]  
    return f"columna {c + 1} de 8 contando desde la izquierda del robot, fila {f + 1} de 8 contando desde el robot"  
   
def hecha(datos, n):  
    return len(datos["poses"].get(n, {})) == 2  
   
def mapa(datos, actual):  
    """Tablero en ASCII: X = casilla actual, # = ya ensenada, o = pendiente, . = se calcula sola."""  
    lineas = ["        A  B  C  D  E  F  G  H"]  
    for r in range(8, 0, -1):  
        fila = f"    {r}   "  
        for col in "ABCDEFGH":  
            n = f"{col}{r}"  
            if n == actual:  
                marca = "X"  
            elif hecha(datos, n):  
                marca = "#"  
            elif n in robot.NODOS:  
                marca = "o"  
            else:  
                marca = "."  
            fila += marca + "  "  
        lineas.append(fila)  
    lineas.append("        ^ abajo = LADO DEL ROBOT")  
    lineas.append("    X = esta   # = hecha   o = pendiente   . = se calcula sola")  
    return "\n".join(lineas)  
   
def guardar(datos):  
    with open(ARCHIVO, "w", encoding="utf-8") as f:  
        json.dump(datos, f, indent=1)  
   
# ---------------------------------------------------------------------  
# Sesion de ensenanza  
# ---------------------------------------------------------------------  
class Sesion:  
    def __init__(self, brazo, datos, mn, mx, ini, tec):  
        self.brazo, self.datos, self.mn, self.mx, self.ini, self.tec = brazo, datos, mn, mx, ini, tec  
        self.pose = list(ini)  
        self.paso = 3  
   
    # --- movimiento ---  
    def ir(self, pose=None):  
        if pose is not None:  
            self.pose = list(pose)  
        try:  
            self.brazo.ir_pose(self.pose)  
        except (RuntimeError, TimeoutError, robot.Abortado) as e:  
            raise ErrorRobot(str(e)) from None  
   
    def pinza(self, grados):  
        self.pose[5] = grados  
        self.ir()  
        if not self.brazo.simulado:  
            time.sleep(robot.PAUSA_PINZA_S)  
   
    def _mezcla(self, nombre, v, pinza):  
        p = self.datos["poses"][nombre]  
        pose = [int(round((1 - v) * a + v * b)) for a, b in zip(p["segura"], p["agarre"])]  
        pose[5] = pinza  
        return pose  
   
    def bajar(self, nombre, pinza):  
        n = max(1, robot.PASOS_VERTICALES)  
        for k in range(1, n + 1):  
            self.ir(self._mezcla(nombre, k / n, pinza))  
   
    def subir(self, nombre, pinza):  
        n = max(1, robot.PASOS_VERTICALES)  
        for k in range(1, n + 1):  
            self.ir(self._mezcla(nombre, 1 - k / n, pinza))  
   
    # --- teclado ---  
    def jog(self, titulo, texto, bloquear_pinza=False):  
        """Mueve el brazo con el teclado. Devuelve 'g' (guardar) o 'b' (volver)."""  
        print("\n" + titulo)  
        print(texto)  
        while True:  
            print(f"\r  pose {self.pose}  paso {self.paso} grados  ", end="", flush=True)  
            k = self.tec.leer()  
            if k in TECLAS:  
                j, d = TECLAS[k]  
                if j in SOLO_PINZA and bloquear_pinza:  
                    print("\n  la pinza esta bloqueada: lleva la pieza agarrada")  
                    continue  
                n = 1 + self.tec.repeticiones(k)  
                nuevo = max(self.mn[j], min(self.mx[j], self.pose[j] + d * self.paso * n))  
                if nuevo != self.pose[j]:  
                    self.pose[j] = nuevo  
                    self.ir()  
                else:  
                    print(f"\n  limite del {robot.NOMBRES[j]} ({nuevo})")  
            elif k == " ":  
                if bloquear_pinza:  
                    print("\n  la pinza esta bloqueada: lleva la pieza agarrada")  
                    continue  
                a, g = self.datos["pinza"].get("abierta"), self.datos["pinza"].get("agarre")  
                if a is not None and g is not None:  
                    destino = g if self.pose[5] == a else a  
                else:                               # aun sin ensenar: va al extremo mas lejano  
                    destino = self.mn[5] if abs(self.pose[5] - self.mn[5]) > abs(self.pose[5] - self.mx[5]) else self.mx[5]  
                self.pinza(destino)  
            elif k in PASOS_GRADOS:  
                self.paso = PASOS_GRADOS[k]  
            elif k == "l":  
                print("\nTeclas:" + __doc__.split("Teclas:")[1])  
            elif k in ("g", "b"):  
                print()  
                return k  
            elif k in ("0", "\x1b"):  
                raise Salir()  
   
    def preguntar(self, texto):  
        """Espera G (si) o B (no). Devuelve 'g' o 'b'."""  
        print("\n" + texto)  
        while True:  
            k = self.tec.leer()  
            if k in ("g", "b"):  
                return k  
            if k in ("0", "\x1b"):  
                raise Salir()  
   
    def guardar_pose(self, nombre, nivel):  
        self.datos["poses"].setdefault(nombre, {})[nivel] = list(self.pose)  
        guardar(self.datos)  
        print(f"  guardado: {nombre} / {nivel}")  
   
# ---------------------------------------------------------------------  
# Las dos clases de casilla  
# ---------------------------------------------------------------------  
def casilla_inicial(ses, n):  
    """La pieza esta puesta (por ti) en el centro de n y el robot NO la lleva todavia."""  
    d = ses.datos  
    pz = d["pinza"]  
    abierta_nueva = "abierta" not in pz  
    pasos = ["segura", "agarre"] + (["cerrar"] if "agarre" not in pz else [])  
    textos = {  
        "segura": ("PASO 1 - ALTURA SEGURA",  
                   f"  Pon UNA pieza en el centro de {n}. Con la pinza ABIERTA (ESPACIO o Z/C, lo justo para\n"  
                   f"  rodear la pieza), llevala encima de la pieza, a una altura que pase por encima de\n"  
                   f"  cualquier otra pieza, bien centrada.   G = guardar"),  
        "agarre": ("PASO 2 - ALTURA DE AGARRE",  
                   "  Baja la pinza abierta hasta que rodee la pieza a media altura.   G = guardar"),  
        "cerrar": ("PASO 3 - CERRAR LA PINZA",  
                   "  Cierra la pinza (Z / C) hasta que SUJETE la pieza, sin apretar de mas.   G = guardar\n"  
                   "  Despues el robot sube solo con la pieza."),  
    }  
    j = 0  
    while j < len(pasos):  
        paso = pasos[j]  
        if paso != "cerrar" and not abierta_nueva and ses.pose[5] != pz["abierta"]:  
            ses.pinza(pz["abierta"])  
        r = ses.jog(*textos[paso])  
        if r == "b":  
            if j == 0:  
                print("  (ya estas en el primer paso de esta casilla)")  
            j = max(0, j - 1)  
            continue  
        if paso in ("segura", "agarre"):  
            ses.guardar_pose(n, paso)  
            if abierta_nueva:  
                pz["abierta"] = ses.pose[5]  
        else:  
            pz["agarre"] = ses.pose[5]  
            guardar(d)  
            print(f"  guardado: pinza agarre = {pz['agarre']}")  
        j += 1  
    if "cerrar" not in pasos:  
        print("  El robot cierra la pinza y sube con la pieza...")  
        ses.pinza(pz["agarre"])  
    ses.subir(n, pz["agarre"])  
   
def casilla_llevando(ses, n):  
    """El robot lleva la pieza agarrada. Devuelve 'ok' o 'repetir'."""  
    d = ses.datos  
    pz = d["pinza"]  
    ab, ag = pz["abierta"], pz["agarre"]  
    textos = {  
        "segura": ("PASO 1 - ALTURA SEGURA",  
                   f"  El robot LLEVA la pieza (pinza cerrada). Llevala encima de {n}, a la misma altura\n"  
                   f"  segura de antes y bien centrada.   G = guardar"),  
        "agarre": ("PASO 2 - ALTURA DE APOYO",  
                   f"  Baja hasta que la pieza quede apoyada en el centro de {n}.   G = guardar\n"  
                   f"  Despues el robot suelta la pieza, sube, baja, la agarra de nuevo y sube (comprobacion)."),  
    }  
    j = 0  
    while j < 2:  
        paso = ("segura", "agarre")[j]  
        r = ses.jog(*textos[paso], bloquear_pinza=True)  
        if r == "b":  
            if j == 0:  
                print("  (ya estas en el primer paso de esta casilla)")  
            j = max(0, j - 1)  
            continue  
        ses.guardar_pose(n, paso)  
        j += 1  
    print("  El robot comprueba: suelta la pieza, sube, baja, la agarra y sube...")  
    ses.pinza(ab)  
    ses.subir(n, ab)  
    ses.bajar(n, ab)  
    ses.pinza(ag)  
    ses.subir(n, ag)  
    r = ses.preguntar(f"COMPROBACION de {n}: agarro bien la pieza?   G = si, seguir   B = no, repetir {n}")  
    if r == "g":  
        return "ok"  
    print(f"  Pon la pieza a mano en el centro de {n} y repite esta casilla desde el principio.")  
    return "repetir"  
   
def ensenar(ses, nodos):  
    inicio_manual = True          # en la primera casilla de la corrida la pieza la pones tu  
    i = 0  
    while i < len(nodos):  
        n = nodos[i]  
        print("\n" + "=" * 70)  
        print(f"CASILLA {i + 1} de {len(nodos)}: {n} - {descripcion(n)}")  
        print(mapa(ses.datos, n))  
        if inicio_manual:  
            casilla_inicial(ses, n)  
            r = "ok"  
        else:  
            r = casilla_llevando(ses, n)  
        if r == "repetir":  
            inicio_manual = True  
            continue  
        inicio_manual = False  
        i += 1  
    # final: deja la pieza y vuelve a reposo  
    n = nodos[-1]  
    pz = ses.datos["pinza"]  
    print(f"\nFin. El robot deja la pieza en {n} y vuelve a reposo...")  
    ses.bajar(n, pz["agarre"])  
    ses.pinza(pz["abierta"])  
    ses.subir(n, pz["abierta"])  
    ses.ir(list(ses.ini))  
   
# ---------------------------------------------------------------------  
def main(argv=None, teclado=None, brazo=None):  
    ap = argparse.ArgumentParser()  
    ap.add_argument("--puerto", help="ej. COM5. Sin puerto = simulacion")  
    ap.add_argument("--rehacer", action="store_true", help="empieza de cero (copia de lo anterior en .bak)")  
    ap.add_argument("--solo", help="repite solo estas casillas, ej. C3,H6 (no borra las demas)")  
    args = ap.parse_args(argv)  
   
    solo = [x.strip().upper() for x in args.solo.split(",")] if args.solo else None  
    if solo:  
        malas = [n for n in solo if n not in robot.NODOS]  
        if malas:  
            print(f"ERROR: {', '.join(malas)} no se ensena. Las casillas ensenadas son: {' '.join(orden_casillas())}")  
            return 1  
   
    try:  
        if brazo is None:  
            brazo = robot.Brazo(args.puerto)  
        mn, mx, ini = brazo.leer_limites()  
    except (RuntimeError, TimeoutError) as e:  
        print("ERROR:", e)  
        return 1  
   
    datos = {"limites": {"mn": mn, "mx": mx, "reposo": ini}, "pinza": {}, "poses": {}}  
    if os.path.exists(ARCHIVO):  
        if args.rehacer:  
            os.replace(ARCHIVO, ARCHIVO + ".bak")  
            print(f"--rehacer: se empieza de cero (copia de lo anterior en {os.path.basename(ARCHIVO)}.bak)")  
        else:  
            with open(ARCHIVO, encoding="utf-8") as f:  
                previo = json.load(f)  
            if previo.get("limites") == datos["limites"]:  
                datos = previo  
            else:  
                print("AVISO: los limites del firmware cambiaron desde la ultima vez (recalibraste).")  
                print("Lo ensenado antes ya no vale: se empieza de cero (copia en poses_ensenadas.json.bak).")  
                os.replace(ARCHIVO, ARCHIVO + ".bak")  
   
    orden = orden_casillas()  
    if solo:  
        nodos = [n for n in orden if n in solo]  
    else:  
        nodos = [n for n in orden if not hecha(datos, n)]  
    if not nodos:  
        if {"abierta", "agarre"} <= set(datos["pinza"]):  
            print("Ya esta todo ensenado. Usa --rehacer para empezar de cero. Prueba con: python robot.py tabla")  
        else:  
            print("Faltan los angulos de la pinza. Usa --rehacer para empezar de cero.")  
        return 0  
   
    print(f"\nCasillas ya ensenadas: {16 - len([n for n in orden if not hecha(datos, n)])} de 16")  
    print("Voy a ensenar: " + " > ".join(nodos))  
    if args.puerto and not robot.confirmar_encendido():  
        return 0  
    robot.POSES = None          # al ensenar no se usan las poses viejas (activar() las compararia)  
    try:  
        brazo.activar()  
    except (RuntimeError, TimeoutError) as e:  
        print("ERROR:", e)  
        return 1  
   
    print("\nORIENTACION" + __doc__.split("ORIENTACION")[1])  
    print(f"Pon UNA pieza en el centro de {nodos[0]} ({descripcion(nodos[0])}).")  
   
    ses = None  
    try:  
        with (teclado or Teclado()) as tec:  
            ses = Sesion(brazo, datos, mn, mx, ini, tec)  
            ensenar(ses, nodos)  
    except Salir:  
        print("\nSaliendo. El brazo queda donde esta y lo guardado se conserva.")  
        return 0  
    except ErrorRobot as e:  
        print(f"\nERROR DEL ROBOT: {e}")  
        print("El brazo puede haber quedado en una posicion inesperada. Lo guardado se conserva.")  
        return 1  
    print("\n\nListo: todas las casillas ensenadas.")  
    print("Comprueba con:  python robot.py tabla")  
    print("y prueba casillas NO ensenadas, por ejemplo:  python robot.py ir E4 --bajar --puerto COM5")  
    return 0  
   
if __name__ == "__main__":  
    sys.exit(main())  
VISION DEL TABLERO  
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
   
Requisitos:  pip install opencv-python numpy pyserial  
Uso:         python vision_tablero.py --listar                    (que numero de camara funciona)  
             python vision_tablero.py --camara 1                  (simulacion, sin robot)  
             python vision_tablero.py --camara 1 --puerto COM5    (con robot)  
   
Teclas (ventana normal):  
  C calibrar (tras los 4 clics)   E capturar tablero VACIO   O girar orientacion  
  M modo jugada                   T guardar mapa y mostrar tabla   D diagnostico  
  R reiniciar                     X PARADA del robot               Q / Esc salir  
Modo jugada (M): escribe origen y destino, ej.  E 3 G 5  (Esc sale del modo)  
Mouse: clic en una casilla del tablero rectificado = origen, otro clic = destino.  
"""  
import argparse  
import csv  
import json  
import os  
import threading  
import time  
   
import cv2  
import numpy as np  
   
import robot  
   
# ---------------------------------------------------------------------  
# CONFIGURACION  
# ---------------------------------------------------------------------  
CAMERA_INDEX = 1  
RESOLUCION = (1280, 720)  
BLOQUEAR_ENFOQUE = True        # evita que el autoenfoque "respire" y cambie la imagen  
FOCO_MANUAL = None             # p. ej. 30; None = deja el foco como esta  
   
BOARD_PIXELS = 640             # tamaño del tablero rectificado  
STEP = BOARD_PIXELS // 8       # pixeles por casilla  
BARRA_PX = 70                  # barra de estado bajo el tablero  
   
# Deteccion de piezas  
MARGEN_CASILLA = 0.15          # parte de cada casilla que NO se analiza (bordes)  
UMBRAL_PIXEL = 15              # diferencia de gris para contar un pixel como "cambiado"  
FRACCION_OCUPADA = 0.20        # fraccion de pixeles cambiados => hay pieza  
CANNY_BAJO, CANNY_ALTO = 20, 60   # sensibilidad de bordes (piezas de poco contraste)  
FRACCION_BORDES = 0.03         # fraccion de bordes NUEVOS => hay pieza (piezas del mismo tono que la casilla)  
FRAMES_ESTABLES = 6            # frames seguidos iguales para aceptar un cambio  
GRIS_PIEZA_BLANCA = 120        # brillo medio de la pieza para llamarla blanca  
VERIF_ESPERA_S = 2.5           # espera antes de verificar con la camara tras mover  
   
ARCHIVO_CALIB = "calibracion_tablero.json"  
ARCHIVO_FONDO = "fondo_vacio.png"  
ARCHIVO_MAPA = "mapa_casillas.csv"  
   
WINDOW_CAMERA = "Camara - tablero"  
WINDOW_BOARD = "Tablero rectificado"  
   
VERDE, NARANJA, ROJO = (0, 170, 0), (0, 140, 255), (0, 0, 230)  
AMARILLO, CIAN, BLANCO = (0, 220, 255), (255, 200, 0), (255, 255, 255)  
FONT = cv2.FONT_HERSHEY_SIMPLEX  
   
# ---------------------------------------------------------------------  
# Nombres de casilla  
# Vista estandar del tablero rectificado: columna 0 = A (izquierda), fila 0 = rango 8 (arriba)  
# ---------------------------------------------------------------------  
def nombre_casilla(col, row):  
    return f"{chr(ord('A') + col)}{8 - row}"  
   
def indices(nombre):  
    """'E3' -> (col, row) en la vista rectificada."""  
    n = nombre.strip().upper()  
    return ord(n[0]) - ord("A"), 8 - int(n[1])  
   
# ---------------------------------------------------------------------  
# Geometria  
# ---------------------------------------------------------------------  
def ordenar_esquinas(puntos):  
    """Ordena 4 puntos (en cualquier orden) como: arriba-izq, arriba-der, abajo-der, abajo-izq."""  
    pts = np.array(puntos, dtype=np.float32)  
    c = pts.mean(axis=0)  
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])  
    pts = pts[np.argsort(ang)]                    # sentido horario en la imagen  
    inicio = int(np.argmin(pts.sum(axis=1)))      # la mas cercana a la esquina superior izquierda  
    return np.roll(pts, -inicio, axis=0)  
   
def calcular_homografia(esquinas, rot):  
    """rot (0-3) gira la orientacion del tablero rectificado en pasos de 90 grados."""  
    src = np.roll(ordenar_esquinas(esquinas), -rot, axis=0)  
    b = BOARD_PIXELS - 1  
    dst = np.float32([[0, 0], [b, 0], [b, b], [0, b]])  
    return cv2.getPerspectiveTransform(src, dst)  
   
def proyectar(puntos, matriz):  
    p = np.float32(puntos).reshape(-1, 1, 2)  
    return cv2.perspectiveTransform(p, matriz).reshape(-1, 2)  
   
# ---------------------------------------------------------------------  
# Deteccion de piezas  
# ---------------------------------------------------------------------  
_MASCARA_BORDE = None  
   
def _mascara_borde():  
    """True en el anillo exterior de cada casilla (la parte que NO se analiza)."""  
    global _MASCARA_BORDE  
    if _MASCARA_BORDE is None:  
        m = int(STEP * MARGEN_CASILLA)  
        mask = np.ones((BOARD_PIXELS, BOARD_PIXELS), bool)  
        for row in range(8):  
            for col in range(8):  
                mask[row * STEP + m:(row + 1) * STEP - m, col * STEP + m:(col + 1) * STEP - m] = False  
        _MASCARA_BORDE = mask  
    return _MASCARA_BORDE  
   
def analizar(actual, fondo):  
    """  
    Compara el tablero rectificado actual contra el vacio.  
    Devuelve (ocupada[8,8], color[8,8] 'W'/'B'/'', frac_cambio[8,8], frac_bordes[8,8]).  
    """  
    g1 = cv2.GaussianBlur(cv2.cvtColor(actual, cv2.COLOR_BGR2GRAY), (5, 5), 0)  
    g0 = cv2.GaussianBlur(cv2.cvtColor(fondo, cv2.COLOR_BGR2GRAY), (5, 5), 0)  
    # Compensa cambios globales de luz usando solo el BORDE de cada casilla (casi nunca hay  
    # pieza ahi). No sirve la mediana de todo el tablero: en un tablero de ajedrez es bimodal.  
    borde = _mascara_borde()  
    ganancia = (float(g1[borde].mean()) + 1.0) / (float(g0[borde].mean()) + 1.0)  
    g0 = np.clip(g0.astype(np.float32) * ganancia, 0, 255).astype(np.uint8)  
   
    diff = cv2.absdiff(g1, g0)  
    e1 = cv2.Canny(g1, CANNY_BAJO, CANNY_ALTO)  
    e0 = cv2.dilate(cv2.Canny(g0, CANNY_BAJO, CANNY_ALTO), np.ones((5, 5), np.uint8))  
    bordes_nuevos = cv2.bitwise_and(e1, cv2.bitwise_not(e0))  
   
    m = int(STEP * MARGEN_CASILLA)  
    ocup = np.zeros((8, 8), bool)  
    color = np.full((8, 8), "", dtype="<U1")  
    frac = np.zeros((8, 8), float)  
    fbor = np.zeros((8, 8), float)  
    for row in range(8):  
        for col in range(8):  
            y1, y2 = row * STEP + m, (row + 1) * STEP - m  
            x1, x2 = col * STEP + m, (col + 1) * STEP - m  
            mascara = diff[y1:y2, x1:x2] > UMBRAL_PIXEL  
            frac[row, col] = mascara.mean()  
            fbor[row, col] = (bordes_nuevos[y1:y2, x1:x2] > 0).mean()  
            if frac[row, col] > FRACCION_OCUPADA or fbor[row, col] > FRACCION_BORDES:  
                ocup[row, col] = True  
                zona = g1[y1:y2, x1:x2]  
                px = zona[mascara] if mascara.any() else zona.reshape(-1)  
                color[row, col] = "W" if px.mean() > GRIS_PIEZA_BLANCA else "B"  
    return ocup, color, frac, fbor  
   
# ---------------------------------------------------------------------  
# Estado del tablero  
# ---------------------------------------------------------------------  
class Tablero:  
    def __init__(self):  
        self.esquinas = []  
        self.rot = 0  
        self.H = None  
        self.Hinv = None  
        self.fondo_raw = None          # foto de camara del tablero vacio  
        self.fondo_rect = None  
        self.estable = np.zeros((8, 8), bool)  
        self.cuenta = np.zeros((8, 8), int)  
        self.color = np.full((8, 8), "", dtype="<U1")  
        self.frac = np.zeros((8, 8))  
        self.fbor = np.zeros((8, 8))  
   
    def reiniciar_ocupacion(self):  
        self.estable[:] = False  
        self.cuenta[:] = 0  
        self.color[:] = ""  
   
    def calibrar(self):  
        if len(self.esquinas) != 4:  
            return False  
        self.H = calcular_homografia(self.esquinas, self.rot)  
        self.Hinv = np.linalg.inv(self.H)  
        self._recalcular_fondo()  
        self.reiniciar_ocupacion()  
        return True  
   
    def _recalcular_fondo(self):  
        if self.H is not None and self.fondo_raw is not None:  
            self.fondo_rect = self.rectificar(self.fondo_raw)  
        else:  
            self.fondo_rect = None  
   
    def rectificar(self, frame):  
        return cv2.warpPerspective(frame, self.H, (BOARD_PIXELS, BOARD_PIXELS))  
   
    def capturar_fondo(self, frame):  
        self.fondo_raw = frame.copy()  
        self._recalcular_fondo()  
        self.reiniciar_ocupacion()  
   
    def rotar(self):  
        self.rot = (self.rot + 1) % 4  
        self.calibrar()  
   
    def reiniciar(self):  
        self.__init__()  
   
    def procesar(self, rect):  
        """Actualiza la ocupacion estable (un cambio se acepta tras FRAMES_ESTABLES frames)."""  
        if self.fondo_rect is None:  
            return  
        ocup, color, self.frac, self.fbor = analizar(rect, self.fondo_rect)  
        cambia = ocup != self.estable  
        self.cuenta[cambia] += 1  
        self.cuenta[~cambia] = 0  
        ok = self.cuenta >= FRAMES_ESTABLES  
        self.estable[ok] = ocup[ok]  
        self.cuenta[ok] = 0  
        self.color[ocup] = color[ocup]  
   
    def ocupada(self, nombre):  
        col, row = indices(nombre)  
        return bool(self.estable[row, col])  
   
    # --- persistencia ---  
    def guardar(self):  
        with open(ARCHIVO_CALIB, "w") as f:  
            json.dump({"esquinas": [[int(x), int(y)] for x, y in self.esquinas], "rot": self.rot}, f)  
        if self.fondo_raw is not None:  
            cv2.imwrite(ARCHIVO_FONDO, self.fondo_raw)  
   
    def cargar(self):  
        if not os.path.exists(ARCHIVO_CALIB):  
            return False  
        with open(ARCHIVO_CALIB) as f:  
            d = json.load(f)  
        self.esquinas = [tuple(p) for p in d["esquinas"]]  
        self.rot = int(d.get("rot", 0))  
        if os.path.exists(ARCHIVO_FONDO):  
            self.fondo_raw = cv2.imread(ARCHIVO_FONDO)  
        return self.calibrar()  
   
# ---------------------------------------------------------------------  
# Dibujo  
# ---------------------------------------------------------------------  
def texto(img, s, org, escala=0.5, color=BLANCO, grosor=1):  
    cv2.putText(img, s, org, FONT, escala, (0, 0, 0), grosor + 2, cv2.LINE_AA)  
    cv2.putText(img, s, org, FONT, escala, color, grosor, cv2.LINE_AA)  
   
def dibujar_tablero(rect, t, origen=None, debug=False):  
    out = rect.copy()  
    capa = out.copy()  
    for row in range(8):  
        for col in range(8):  
            if t.estable[row, col]:  
                c = VERDE if t.color[row, col] == "W" else NARANJA  
                cv2.rectangle(capa, (col * STEP + 3, row * STEP + 3),  
                              ((col + 1) * STEP - 3, (row + 1) * STEP - 3), c, -1)  
    out = cv2.addWeighted(capa, 0.35, out, 0.65, 0)  
   
    for k in range(9):  
        cv2.line(out, (k * STEP, 0), (k * STEP, BOARD_PIXELS), (60, 60, 60), 1)  
        cv2.line(out, (0, k * STEP), (BOARD_PIXELS, k * STEP), (60, 60, 60), 1)  
   
    for row in range(8):  
        for col in range(8):  
            x, y = col * STEP, row * STEP  
            n = nombre_casilla(col, row)  
            texto(out, n, (x + 22, y + 46), 0.65, BLANCO, 1)  
            if t.estable[row, col]:  
                texto(out, t.color[row, col], (x + STEP - 18, y + 16), 0.5, BLANCO, 1)  
            if debug:  
                texto(out, f"{t.frac[row, col] * 100:.0f}/{t.fbor[row, col] * 100:.0f}",  
                      (x + 4, y + STEP - 6), 0.38, AMARILLO, 1)  
    if origen:  
        c, r = indices(origen)  
        cv2.rectangle(out, (c * STEP + 2, r * STEP + 2), ((c + 1) * STEP - 2, (r + 1) * STEP - 2), AMARILLO, 3)  
    cv2.line(out, (0, BOARD_PIXELS - 2), (BOARD_PIXELS, BOARD_PIXELS - 2), ROJO, 3)  
    texto(out, "LADO DEL ROBOT", (BOARD_PIXELS // 2 - 70, BOARD_PIXELS - 8), 0.5, ROJO, 1)  
    return out  
   
def dibujar_camara(frame, t, ayuda=""):  
    d = frame.copy()  
    for i, p in enumerate(t.esquinas):  
        cv2.circle(d, (int(p[0]), int(p[1])), 7, (0, 0, 255), -1)  
        texto(d, str(i + 1), (int(p[0]) + 8, int(p[1]) - 8), 0.7, (0, 0, 255), 2)  
    if t.Hinv is not None:  
        for k in range(9):  
            a = k * STEP  
            for p0, p1 in (((a, 0), (a, BOARD_PIXELS)), ((0, a), (BOARD_PIXELS, a))):  
                q = proyectar([p0, p1], t.Hinv).astype(int)  
                cv2.line(d, tuple(q[0]), tuple(q[1]), (0, 255, 255), 1)  
        centros = [((c + 0.5) * STEP, (r + 0.5) * STEP) for r in range(8) for c in range(8)]  
        for (c, r), q in zip([(c, r) for r in range(8) for c in range(8)], proyectar(centros, t.Hinv)):  
            texto(d, nombre_casilla(c, r), (int(q[0]) - 10, int(q[1]) + 5), 0.4, (0, 255, 255), 1)  
    if ayuda:  
        texto(d, ayuda, (10, 25), 0.6, AMARILLO, 2)  
    return d  
   
# ---------------------------------------------------------------------  
# Aplicacion  
# ---------------------------------------------------------------------  
class App:  
    def __init__(self, brazo):  
        self.t = Tablero()  
        self.brazo = brazo  
        self.origen = None  
        self.entrada = ""  
        self.modo_jugada = False  
        self.debug = False  
        self.mensaje = ("", BLANCO, 0)  
        self.verificar = None  
   
    def msg(self, s, color=BLANCO, dur=5.0):  
        self.mensaje = (s, color, time.time() + dur)  
   
    # ---- mouse ----  
    def clic_camara(self, event, x, y, flags, param):  
        if event == cv2.EVENT_LBUTTONDOWN and len(self.t.esquinas) < 4:  
            self.t.esquinas.append((x, y))  
            print(f"Esquina {len(self.t.esquinas)}: ({x}, {y})")  
            if len(self.t.esquinas) == 4:  
                self.msg("4 esquinas listas. Pulsa C para rectificar", AMARILLO)  
   
    def clic_tablero(self, event, x, y, flags, param):  
        if event != cv2.EVENT_LBUTTONDOWN or self.t.H is None:  
            return  
        if not (0 <= x < BOARD_PIXELS and 0 <= y < BOARD_PIXELS):  
            return  
        self.ingresar_casilla(nombre_casilla(min(7, x // STEP), min(7, y // STEP)))  
   
    # ---- jugada ----  
    def ingresar_casilla(self, nombre):  
        if self.origen is None:  
            self.origen = nombre  
            self.msg(f"Origen {nombre}. Elige el DESTINO", AMARILLO, 30)  
        else:  
            origen, self.origen = self.origen, None  
            self.solicitar(origen, nombre)  
   
    def validar(self, origen, destino):  
        """Devuelve (ok, mensaje, conservar_origen)."""  
        t = self.t  
        if self.brazo.ocupado:  
            return False, "Robot ocupado: espera a que termine", False  
        if t.fondo_rect is None:  
            return False, "Falta capturar el tablero VACIO (tecla E)", False  
        if origen == destino:  
            return False, "Origen y destino son la misma casilla", False  
        if not t.ocupada(origen):  
            return False, f"No hay pieza en {origen}", False  
        if t.ocupada(destino):  
            return False, f"{destino} esta OCUPADA: no se puede mover ahi. Elige otra casilla", True  
        try:  
            robot.planificar(origen, destino)  
        except robot.FueraDeAlcance as e:  
            return False, f"Fuera de alcance: {e}", False  
        return True, "", False  
   
    def solicitar(self, origen, destino):  
        ok, texto_error, conservar = self.validar(origen, destino)  
        if not ok:  
            print("RECHAZADO:", texto_error)  
            self.msg(texto_error, ROJO, 8)  
            if conservar:  
                self.origen = origen          # solo falta elegir otro destino  
            return  
        self.msg(f"Moviendo {origen} -> {destino}", VERDE, 60)  
        print(f"Moviendo {origen} -> {destino}")  
        self.brazo.ocupado = True             # bloquea nuevas ordenes de inmediato  
   
        def tarea():  
            try:  
                self.brazo.mover_pieza(origen, destino,  
                                       progreso=lambda s: self.msg(f"{origen}->{destino}: {s}", VERDE, 60))  
                self.msg(f"Listo {origen} -> {destino}. Verificando con la camara...", VERDE, 10)  
                self.verificar = (time.time() + VERIF_ESPERA_S, origen, destino)  
            except robot.Abortado:  
                self.msg("Movimiento DETENIDO", ROJO, 10)  
            except Exception as e:  
                print("ERROR del robot:", e)  
                self.msg(f"Error del robot: {e}", ROJO, 15)  
            finally:  
                self.brazo.ocupado = False  
   
        threading.Thread(target=tarea, daemon=True).start()  
   
    def revisar_verificacion(self):  
        if not self.verificar or time.time() < self.verificar[0]:  
            return  
        _, o, d = self.verificar  
        self.verificar = None  
        if self.t.ocupada(d) and not self.t.ocupada(o):  
            self.msg(f"Verificado por camara: pieza en {d}, {o} libre", VERDE, 10)  
        else:  
            self.msg(f"ATENCION: la camara no confirma el movimiento {o}->{d}", ROJO, 15)  
   
    # ---- teclado ----  
    def teclado(self, key, frame):  
        """Devuelve False para salir."""  
        if key == 255:  
            return True  
        c = chr(key).lower()  
        if c == "x":  
            self.brazo.parar()  
            self.msg("PARADA DE EMERGENCIA", ROJO, 10)  
            return True  
        if self.modo_jugada:  
            if key == 27:  
                self.modo_jugada, self.entrada, self.origen = False, "", None  
                self.msg("Modo jugada terminado")  
            elif key in (8, 127):  
                if self.entrada:  
                    self.entrada = self.entrada[:-1]  
                else:  
                    self.origen = None  
            else:  
                ch = c.upper()  
                if (len(self.entrada) == 0 and ch in "ABCDEFGH") or \  
                   (len(self.entrada) == 1 and ch in "12345678"):  
                    self.entrada += ch  
                    if len(self.entrada) == 2:  
                        nombre, self.entrada = self.entrada, ""  
                        self.ingresar_casilla(nombre)  
            return True  
   
        if key == 27 or c == "q":  
            return False  
        t = self.t  
        if c == "r":  
            t.reiniciar()  
            self.origen = None  
            self.msg("Reiniciado. Haz clic en las 4 esquinas", AMARILLO)  
        elif c == "c":  
            if t.calibrar():  
                t.guardar()  
                self.msg("Calibrado. Pulsa O hasta que A1 quede abajo-izq (lado del robot)", AMARILLO, 15)  
            else:  
                self.msg("Faltan esquinas (haz 4 clics en la camara)", ROJO)  
        elif c == "e" and t.H is not None:  
            t.capturar_fondo(frame)  
            t.guardar()  
            self.msg("Tablero vacio capturado", VERDE)  
        elif c == "o" and t.H is not None:  
            t.rotar()  
            t.guardar()  
            self.msg(f"Orientacion {t.rot * 90} deg: A1 debe quedar abajo-izq (lado del robot)", AMARILLO, 8)  
        elif c == "m":  
            self.modo_jugada = True  
            self.msg("Modo jugada: escribe origen y destino (ej. E 3 G 5)", AMARILLO, 10)  
        elif c == "t" and t.H is not None:  
            exportar_mapa(t)  
            self.msg(f"Mapa guardado en {ARCHIVO_MAPA}", VERDE)  
        elif c == "d":  
            self.debug = not self.debug  
        return True  
   
    # ---- vistas ----  
    def vista_camara(self, frame):  
        t = self.t  
        if len(t.esquinas) < 4:  
            ayuda = f"Clic en las 4 esquinas del tablero ({len(t.esquinas)}/4)"  
        elif t.H is None:  
            ayuda = "Pulsa C para rectificar"  
        elif t.fondo_rect is None:  
            ayuda = "Quita las piezas y pulsa E (tablero vacio)"  
        else:  
            ayuda = ""  
        return dibujar_camara(frame, t, ayuda)  
   
    def vista_tablero(self, rect):  
        out = dibujar_tablero(rect, self.t, self.origen, self.debug)  
        barra = np.zeros((BARRA_PX, BOARD_PIXELS, 3), np.uint8)  
        if self.modo_jugada:  
            l1 = f"JUGADA  origen: {self.origen or '--'}  escribiendo: {self.entrada or '_'}  (X=parar Esc=salir)"  
        else:  
            l1 = "C calibrar E vacio O girar M jugada T mapa D diag R reiniciar Q salir"  
        texto(barra, l1, (6, 22), 0.45, BLANCO, 1)  
        s, color, hasta = self.mensaje  
        if s and time.time() < hasta:  
            texto(barra, s[:70], (6, 52), 0.5, color, 1)  
        return np.vstack([out, barra])  
   
def exportar_mapa(t):  
    """Guarda las 64 casillas (nombre, centro en pixeles, centro en mm, ocupacion) y las muestra."""  
    centros = [((c + 0.5) * STEP, (r + 0.5) * STEP) for r in range(8) for c in range(8)]  
    cam = proyectar(centros, t.Hinv)  
    with open(ARCHIVO_MAPA, "w", newline="") as f:  
        w = csv.writer(f)  
        w.writerow(["casilla", "rect_x", "rect_y", "camara_x", "camara_y", "x_mm", "y_mm", "ocupada", "color"])  
        for i, (c, r) in enumerate([(c, r) for r in range(8) for c in range(8)]):  
            n = nombre_casilla(c, r)  
            x_mm, y_mm = robot.centro_casilla_mm(n)  
            w.writerow([n, int(centros[i][0]), int(centros[i][1]), int(cam[i][0]), int(cam[i][1]),  
                        f"{x_mm:.1f}", f"{y_mm:.1f}", int(t.estable[r, c]), t.color[r, c]])  
    print("\n    " + " ".join(f" {ch} " for ch in "ABCDEFGH"))  
    for r in range(8):  
        fila = " ".join(f" {t.color[r, c] if t.estable[r, c] else '.'} " for c in range(8))  
        print(f" {8 - r}  {fila}")  
    print(f"\nMapa guardado en {ARCHIVO_MAPA}")  
   
def abrir_camara(idx):  
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(idx)  
    if not cap.isOpened():  
        return None  
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUCION[0])  
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUCION[1])  
    if BLOQUEAR_ENFOQUE:  
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)  
    if FOCO_MANUAL is not None:  
        cap.set(cv2.CAP_PROP_FOCUS, FOCO_MANUAL)  
    return cap  
   
def listar_camaras():  
    """Prueba los indices 0..5 y dice cuales abren y entregan imagen."""  
    print("Buscando camaras (indices 0 a 5)...")  
    hallada = False  
    for i in range(6):  
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(i)  
        if cap.isOpened():  
            ok, frame = cap.read()  
            if ok:  
                print(f"  --camara {i}: funciona ({frame.shape[1]}x{frame.shape[0]})")  
                hallada = True  
        cap.release()  
    if not hallada:  
        print("  No se encontro ninguna. Revisa: cable USB, que otro programa (Zoom, Teams, la app de "  
              "Camara) no la este usando, y los permisos de camara de Windows.")  
    else:  
        print("Usa el numero que corresponda a TU camara web (0 suele ser la del portatil, 1 la externa).")  
   
def main():  
    ap = argparse.ArgumentParser()  
    ap.add_argument("--camara", type=int, default=CAMERA_INDEX)  
    ap.add_argument("--puerto", help="puerto del Arduino (ej. COM5). Sin puerto = simulacion")  
    ap.add_argument("--listar", action="store_true", help="prueba los numeros de camara y sale")  
    args = ap.parse_args()  
    if args.listar:  
        listar_camaras()  
        return  
   
    try:  
        brazo = robot.Brazo(args.puerto)  
    except RuntimeError as e:  
        print("ERROR:", e)  
        return  
    if args.puerto:  
        if not robot.confirmar_encendido():  
            return  
        try:  
            brazo.activar()  
        except (RuntimeError, TimeoutError) as e:  
            print("ERROR:", e)  
            return  
   
    cap = abrir_camara(args.camara)  
    if cap is None:  
        print("Error: no se pudo abrir la camara", args.camara)  
        return  
   
    app = App(brazo)  
    if app.t.cargar():  
        print("Calibracion anterior cargada (si la camara se movio, pulsa R y recalibra).")  
        app.msg("Calibracion cargada. Revisa que el cuadro calce con el tablero", AMARILLO, 10)  
   
    cv2.namedWindow(WINDOW_CAMERA)  
    cv2.namedWindow(WINDOW_BOARD)  
    cv2.setMouseCallback(WINDOW_CAMERA, app.clic_camara)  
    cv2.setMouseCallback(WINDOW_BOARD, app.clic_tablero)  
   
    while True:  
        ok, frame = cap.read()  
        if not ok:  
            print("Error: la camara dejo de responder")  
            break  
        cv2.imshow(WINDOW_CAMERA, app.vista_camara(frame))  
        if app.t.H is not None:  
            rect = app.t.rectificar(frame)  
            app.t.procesar(rect)  
            cv2.imshow(WINDOW_BOARD, app.vista_tablero(rect))  
        app.revisar_verificacion()  
        if not app.teclado(cv2.waitKey(1) & 0xFF, frame):  
            break  
   
    cap.release()  
    cv2.destroyAllWindows()  
   
if __name__ == "__main__":  
    main()  
Robot  
"""  
robot.py - Casilla -> angulos de servo, y comunicacion con el brazo de ajedrez  
==============================================================================  
Convierte una casilla (A1..H8) en angulos de servo y ejecuta la secuencia  
agarrar -> mover -> soltar por el puerto serial (firmware: brazo_serial.ino).  
   
Hay DOS modos para saber a que angulos va cada casilla:  
   
  1) POSES ENSENADAS (recomendado: no hay que medir nada).  
     teach.py graba 16 casillas con el brazo en la mano (a mano, con teclas) y  
     aqui se calculan las otras 48 por interpolacion. Se usa solo, si existe  
     poses_ensenadas.json completo.  
  2) GEOMETRIA: cinematica inversa con las medidas del brazo (ver CONFIGURACION).  
   
Sistema de coordenadas del tablero (mm), usado por el modo geometria:  
    origen = centro de A1, +X hacia la columna H, +Y hacia la fila 8  
El robot mira al tablero: fila 1 cerca de el, columna A a su izquierda.  
   
Uso (sin --puerto es SIMULACION, no mueve nada):  
    python robot.py tabla                    # que casillas alcanza el brazo  
    python robot.py angulos E3               # angulos para una casilla  
    python robot.py mover E3 G5              # secuencia completa E3 -> G5  
    python robot.py ir E3 --bajar --puerto COM5   # solo ir a una casilla (para afinar)  
    python robot.py reposo --puerto COM5  
"""  
import argparse  
import json  
import math  
import os  
import sys  
import time  
   
try:  
    import serial  
except ImportError:  # pyserial solo hace falta con el robot real  
    serial = None  
   
# =====================================================================  
# CONFIGURACION COMUN  
# =====================================================================  
ARCHIVO_POSES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poses_ensenadas.json")  
   
PASOS_VERTICALES = 3           # la bajada/subida se divide en estos pasos  
PAUSA_PINZA_S = 0.8            # espera tras abrir/cerrar  
   
# Valores por defecto (en modo poses ensenadas se reemplazan por los del archivo,  
# que a su vez salen del firmware: asi la tabla vive en UN solo sitio, el .ino).  
PINZA_ABIERTA = 90  
PINZA_AGARRE = 40  
MN = (3, 60, 3, 3, 3, 10)  
MX = (170, 140, 177, 178, 175, 110)  
REPOSO = (50, 90, 120, 178, 175, 25)  
NOMBRES = ("Base", "Hombro", "Codo", "Muneca", "Gancho", "Pinza")  
   
# Casillas que se ensenan: columnas A,C,F,H x filas 1,3,6,8 (indices 0,2,5,7)  
NODOS_IDX = (0, 2, 5, 7)  
NODOS = [f"{chr(65 + c)}{r + 1}" for r in NODOS_IDX for c in NODOS_IDX]  
   
# =====================================================================  
# CONFIGURACION SOLO PARA EL MODO GEOMETRIA (ignorar si usas teach.py)  
# =====================================================================  
GEOMETRIA_CONFIRMADA = False   # mientras sea False, el modo geometria no mueve el robot real  
   
CASILLA_MM = 30.0              # lado de UNA casilla  
BASE_X_MM = 3.5 * CASILLA_MM   # eje de la base, desde el centro de A1 (+X hacia H)  
BASE_Y_MM = -70.0              # negativo = detras de la fila 1  
H_HOMBRO_MM = 90.0             # altura del eje del hombro sobre el tablero  
L1_MM = 110.0                  # eje del hombro -> eje del codo  
L2_MM = 110.0                  # eje del codo   -> eje del gancho (servo 5)  
LG_MM = 100.0                  # eje del gancho -> punta de la pinza  
Z_AGARRE_MM = 20.0             # altura de la punta al agarrar  
Z_SEGURA_MM = 90.0             # altura de la punta al desplazarse  
CORR_X_MM = 0.0  
CORR_Y_MM = 0.0  
# servo = OFFSET + SIGNO * angulo_geometrico (grados)  
BASE_OFFSET, BASE_SIGNO = 90.0, +1       # 0 = recto al frente (+Y); + = hacia la derecha  
HOMBRO_OFFSET, HOMBRO_SIGNO = 90.0, +1   # 0 = brazo superior vertical; + = hacia adelante  
CODO_OFFSET, CODO_SIGNO = 90.0, +1       # 0 = antebrazo recto; + = antebrazo baja hacia adelante  
GANCHO_OFFSET, GANCHO_SIGNO = 90.0, +1   # 0 = pinza alineada con el antebrazo; + = mas hacia abajo  
INCLINACIONES_PINZA = (0, 10, 20, 30, 40)   # 0 = pinza vertical hacia abajo  
MUNECA_ROLL = REPOSO[3]  
# =====================================================================  
   
class FueraDeAlcance(Exception):  
    pass  
   
class Abortado(Exception):  
    pass  
   
# ---------------------------------------------------------------------  
# Casillas  
# ---------------------------------------------------------------------  
def nombre_a_indices(nombre):  
    """'E3' -> (col=4, fila=2). Lanza ValueError si el nombre no es valido."""  
    n = str(nombre).strip().upper()  
    if len(n) != 2 or n[0] not in "ABCDEFGH" or n[1] not in "12345678":  
        raise ValueError(f"Casilla invalida: {nombre!r}")  
    return ord(n[0]) - ord("A"), int(n[1]) - 1  
   
def centro_casilla_mm(nombre):  
    col, fila = nombre_a_indices(nombre)  
    return col * CASILLA_MM + CORR_X_MM, fila * CASILLA_MM + CORR_Y_MM  
   
# ---------------------------------------------------------------------  
# MODO 1: poses ensenadas (interpolacion)  
# ---------------------------------------------------------------------  
POSES = None  
AVISO_POSES = ""  
_LIM_ARCHIVO = None  
   
def cargar_poses(ruta=ARCHIVO_POSES):  
    """Carga poses_ensenadas.json y activa el modo 1. Lanza ValueError si esta incompleto."""  
    global POSES, MN, MX, REPOSO, MUNECA_ROLL, PINZA_ABIERTA, PINZA_AGARRE, _LIM_ARCHIVO  
    with open(ruta, encoding="utf-8") as f:  
        d = json.load(f)  
    poses = d.get("poses", {})  
    faltan = [f"{n}/{nivel}" for n in NODOS for nivel in ("segura", "agarre") if nivel not in poses.get(n, {})]  
    if faltan:  
        raise ValueError("faltan por ensenar: " + ", ".join(faltan[:6]) + (" ..." if len(faltan) > 6 else ""))  
    if not all(k in d.get("pinza", {}) for k in ("abierta", "agarre")):  
        raise ValueError("falta ensenar la pinza (abierta / agarre)")  
    lim = d["limites"]  
    MN, MX, REPOSO = tuple(lim["mn"]), tuple(lim["mx"]), tuple(lim["reposo"])  
    MUNECA_ROLL = REPOSO[3]  
    PINZA_ABIERTA, PINZA_AGARRE = int(d["pinza"]["abierta"]), int(d["pinza"]["agarre"])  
    _LIM_ARCHIVO = [list(MN), list(MX), list(REPOSO)]  
    POSES = poses  
    return True  
   
def _lagrange(i, x):  
    p = 1.0  
    for j, nj in enumerate(NODOS_IDX):  
        if j != i:  
            p *= (x - nj) / (NODOS_IDX[i] - nj)  
    return p  
   
def _pose_ensenada(casilla, nivel, pinza):  
    """nivel 0 = altura segura, 1 = altura de agarre (se mezclan linealmente)."""  
    col, fila = nombre_a_indices(casilla)  
    p = [0.0] * 6  
    for i, c in enumerate(NODOS_IDX):  
        for k, f in enumerate(NODOS_IDX):  
            w = _lagrange(i, col) * _lagrange(k, fila)  
            nodo = POSES[f"{chr(65 + c)}{f + 1}"]  
            for j in range(6):  
                p[j] += w * ((1 - nivel) * nodo["segura"][j] + nivel * nodo["agarre"][j])  
    p[5] = pinza  
    for j in range(6):  
        if not (MN[j] <= round(p[j]) <= MX[j]):  
            raise FueraDeAlcance(f"{casilla}: {NOMBRES[j]} pediria {p[j]:.0f} (rango {MN[j]}-{MX[j]})")  
    return [int(round(v)) for v in p]  
   
# ---------------------------------------------------------------------  
# MODO 2: cinematica inversa (geometria medida)  
# ---------------------------------------------------------------------  
def _clamp(v):  
    return max(-1.0, min(1.0, v))  
   
def _plano(r, z, phi_deg):  
    """Plano vertical del brazo. Devuelve (alfa, beta, gamma) en grados o None."""  
    phi = math.radians(phi_deg)  
    rw = r - LG_MM * math.sin(phi)  
    zw = z + LG_MM * math.cos(phi)  
    dz = zw - H_HOMBRO_MM  
    d = math.hypot(rw, dz)  
    if d > L1_MM + L2_MM - 1e-6 or d < abs(L1_MM - L2_MM) + 1e-6 or d < 1e-6:  
        return None  
    theta_codo = math.degrees(math.acos(_clamp((L1_MM**2 + L2_MM**2 - d**2) / (2 * L1_MM * L2_MM))))  
    beta = 180.0 - theta_codo  
    eps = math.degrees(math.acos(_clamp((L1_MM**2 + d**2 - L2_MM**2) / (2 * L1_MM * d))))  
    delta = math.degrees(math.atan2(rw, dz))  
    alfa = delta - eps  
    gamma = (180.0 - phi_deg) - (alfa + beta)  
    return alfa, beta, gamma  
   
def resolver(x_mm, y_mm, z_mm, pinza, redondear=True):  
    """Pose [base, hombro, codo, muñeca, gancho, pinza] para llevar la punta a (x, y, z)."""  
    dx = x_mm - BASE_X_MM  
    dy = y_mm - BASE_Y_MM  
    r = math.hypot(dx, dy)  
    psi = math.degrees(math.atan2(dx, dy))  
    primer_motivo = None  
    for phi in INCLINACIONES_PINZA:  
        ang = _plano(r, z_mm, phi)  
        if ang is None:  
            motivo = f"a {r:.0f} mm de la base no llega el brazo"  
        else:  
            alfa, beta, gamma = ang  
            servos = [  
                BASE_OFFSET + BASE_SIGNO * psi,  
                HOMBRO_OFFSET + HOMBRO_SIGNO * alfa,  
                CODO_OFFSET + CODO_SIGNO * beta,  
                MUNECA_ROLL,  
                GANCHO_OFFSET + GANCHO_SIGNO * gamma,  
                pinza,  
            ]  
            fuera = [i for i in range(6) if not (MN[i] <= round(servos[i]) <= MX[i])]  
            if not fuera:  
                return [int(round(s)) for s in servos] if redondear else servos  
            i = fuera[0]  
            motivo = f"{NOMBRES[i]} pediria {servos[i]:.0f} (rango {MN[i]}-{MX[i]})"  
        if primer_motivo is None:  
            primer_motivo = motivo  
    raise FueraDeAlcance(primer_motivo)  
   
def cinematica_directa(servos):  
    """(x, y, z) en mm de la punta de la pinza para una pose de servos (modo geometria)."""  
    psi = math.radians((servos[0] - BASE_OFFSET) / BASE_SIGNO)  
    alfa = (servos[1] - HOMBRO_OFFSET) / HOMBRO_SIGNO  
    beta = (servos[2] - CODO_OFFSET) / CODO_SIGNO  
    gamma = (servos[4] - GANCHO_OFFSET) / GANCHO_SIGNO  
    a1 = math.radians(alfa)  
    a2 = math.radians(alfa + beta)  
    a3 = math.radians(alfa + beta + gamma)  
    r = L1_MM * math.sin(a1) + L2_MM * math.sin(a2) + LG_MM * math.sin(a3)  
    z = H_HOMBRO_MM + L1_MM * math.cos(a1) + L2_MM * math.cos(a2) + LG_MM * math.cos(a3)  
    return BASE_X_MM + r * math.sin(psi), BASE_Y_MM + r * math.cos(psi), z  
   
# ---------------------------------------------------------------------  
# Interfaz comun a los dos modos  
# ---------------------------------------------------------------------  
def modo():  
    return "poses ensenadas" if POSES is not None else "geometria"  
   
def pose_en(casilla, nivel, pinza):  
    """Pose de servos sobre una casilla. nivel: 0 = altura segura, 1 = altura de agarre."""  
    if POSES is not None:  
        return _pose_ensenada(casilla, nivel, pinza)  
    x, y = centro_casilla_mm(casilla)  
    return resolver(x, y, Z_SEGURA_MM + (Z_AGARRE_MM - Z_SEGURA_MM) * nivel, pinza)  
   
def alcanzable(casilla):  
    """(True, '') si el brazo llega a la casilla en altura segura y de agarre."""  
    try:  
        pose_en(casilla, 0, PINZA_ABIERTA)  
        pose_en(casilla, 1, PINZA_ABIERTA)  
        return True, ""  
    except FueraDeAlcance as e:  
        return False, str(e)  
   
def _niveles_bajada():  
    n = max(1, PASOS_VERTICALES)  
    return [k / n for k in range(1, n + 1)]  
   
def planificar(origen, destino):  
    """Calcula TODAS las poses antes de mover nada. Devuelve [(descripcion, pose), ...].  
    Lanza FueraDeAlcance (indicando la casilla) si alguna pose no es posible."""  
    A, C = PINZA_ABIERTA, PINZA_AGARRE  
    bajada = _niveles_bajada()  
    subida = [1 - v for v in bajada]  
    pasos = []  
   
    def ik(casilla, nivel, pinza):  
        try:  
            return pose_en(casilla, nivel, pinza)  
        except FueraDeAlcance as e:  
            msg = str(e)  
            raise FueraDeAlcance(msg if msg.startswith(casilla) else f"{casilla}: {msg}") from None  
   
    def tramo(casilla, niveles, pinza, texto):  
        for v in niveles:  
            pasos.append((texto, ik(casilla, v, pinza)))  
   
    pasos.append((f"Sobre {origen}", ik(origen, 0, A)))  
    tramo(origen, bajada, A, f"Bajando a {origen}")  
    pasos.append(("Cerrando pinza", ik(origen, 1, C)))  
    tramo(origen, subida, C, f"Subiendo de {origen}")  
    pasos.append((f"Sobre {destino}", ik(destino, 0, C)))  
    tramo(destino, bajada, C, f"Bajando a {destino}")  
    pasos.append(("Abriendo pinza", ik(destino, 1, A)))  
    tramo(destino, subida, A, f"Subiendo de {destino}")  
    pasos.append(("Reposo", list(REPOSO)))  
    return pasos  
   
def verificar_modo_real():  
    """Impide mover el robot REAL sin poses ensenadas ni geometria confirmada."""  
    if POSES is None and not GEOMETRIA_CONFIRMADA:  
        extra = f" ({AVISO_POSES})" if AVISO_POSES else ""  
        raise RuntimeError("No hay poses ensenadas completas" + extra + ". Ejecuta teach.py "  
                           "(recomendado) o mide el brazo y pon GEOMETRIA_CONFIRMADA = True")  
   
def confirmar_encendido():  
    """Secuencia segura. El Arduino se REINICIA al abrir el puerto y los servos pierden la senal  
    (un servo sin senal no sujeta nada), por eso la fuente de los servos debe estar apagada hasta aqui."""  
    print("\n1) El brazo debe estar FISICAMENTE en la pose de reposo, apoyado en sus topes.")  
    print("2) Enciende AHORA la fuente de los servos (hasta este momento debia estar apagada).")  
    return input("Pulsa Enter para activar (n = cancelar): ").strip().lower() != "n"  
   
# ---------------------------------------------------------------------  
# Comunicacion con el Arduino  
# ---------------------------------------------------------------------  
class Brazo:  
    def __init__(self, puerto=None, baudios=9600):  
        self.ser = None  
        self.activo = False  
        self.ocupado = False  
        self._abortar = False  
        self._lineas = []  
        if puerto:  
            if serial is None:  
                raise RuntimeError("Falta pyserial: pip install pyserial")  
            try:  
                self.ser = serial.Serial(puerto, baudios, timeout=0.5)  
            except serial.SerialException as e:  
                raise RuntimeError(f"No se pudo abrir {puerto} (cierra el Monitor Serial del IDE): {e}") from None  
            time.sleep(2.0)                    # el Arduino se reinicia al abrir el puerto  
            self.ser.reset_input_buffer()  
   
    @property  
    def simulado(self):  
        return self.ser is None  
   
    def _enviar(self, linea, timeout=60.0):  
        if self.simulado:  
            print(f"   [SIM] {linea}")  
            return  
        self._lineas = []  
        self.ser.write((linea + "\n").encode("ascii"))  
        fin = time.time() + timeout  
        while time.time() < fin:  
            resp = self.ser.readline().decode("ascii", errors="ignore").strip()  
            if not resp:  
                continue  
            if resp.startswith("OK"):  
                return  
            if resp.startswith("ERR"):  
                raise RuntimeError(f"Arduino respondio: {resp}")  
            self._lineas.append(resp)  
        raise TimeoutError(f"El Arduino no respondio OK a '{linea}'")  
   
    def leer_limites(self):  
        """(mn, mx, reposo) tal como estan en el firmware. En simulacion, los de robot.py."""  
        if self.simulado:  
            return list(MN), list(MX), list(REPOSO)  
        self._enviar("L", timeout=5)  
        datos = {}  
        for linea in self._lineas:  
            p = linea.split()  
            if len(p) == 8 and p[0] == "LIM":  
                datos[p[1]] = [int(v) for v in p[2:]]  
        if not all(k in datos for k in "nxi"):  
            raise RuntimeError("El firmware no informo sus limites: sube la version nueva de brazo_serial.ino")  
        return datos["n"], datos["x"], datos["i"]  
   
    def activar(self):  
        """El brazo debe estar FISICAMENTE en la pose de reposo."""  
        global MN, MX, REPOSO, MUNECA_ROLL  
        mn, mx, ini = self.leer_limites()          # se leen ANTES de activar  
        if POSES is not None and _LIM_ARCHIVO is not None and [mn, mx, ini] != _LIM_ARCHIVO:  
            raise RuntimeError("Los limites del firmware cambiaron desde que ensenaste las casillas "  
                               "(recalibraste?). Vuelve a ejecutar teach.py --rehacer")  
        if POSES is None:  
            MN, MX, REPOSO = tuple(mn), tuple(mx), tuple(ini)  
            MUNECA_ROLL = REPOSO[3]  
        self._enviar("A", timeout=30)  
        self.activo = True  
   
    def ir_pose(self, pose):  
        if self._abortar:  
            raise Abortado()  
        self._enviar("G " + " ".join(str(int(a)) for a in pose))  
        if self._abortar:  
            raise Abortado()  
   
    def parar(self):  
        """Parada de emergencia: congela los servos donde esten y cancela la secuencia."""  
        self._abortar = True  
        if self.ser is not None:  
            try:  
                self.ser.write(b"X\n")  
            except Exception:  
                pass  
   
    def mover_pieza(self, origen, destino, progreso=None):  
        self.ocupado = True  
        try:  
            pasos = planificar(origen, destino)   # falla ANTES de mover si no hay alcance  
            if not self.simulado:  
                verificar_modo_real()  
            self._abortar = False  
            if not self.activo:  
                self.activar()  
            for desc, pose in pasos:  
                if progreso:  
                    progreso(desc)  
                self.ir_pose(pose)  
                if desc.startswith(("Cerrando", "Abriendo")):  
                    time.sleep(PAUSA_PINZA_S if not self.simulado else 0.1)  
                elif self.simulado:  
                    time.sleep(0.1)  
        finally:  
            self.ocupado = False  
   
    def ir_a_casilla(self, casilla, bajar=False):  
        """Solo para afinar: va sobre una casilla (y opcionalmente baja a la altura de agarre)."""  
        if not self.simulado:  
            verificar_modo_real()  
        self._abortar = False  
        if not self.activo:  
            self.activar()  
        self.ir_pose(pose_en(casilla, 0, PINZA_ABIERTA))  
        if bajar:  
            for v in _niveles_bajada():  
                self.ir_pose(pose_en(casilla, v, PINZA_ABIERTA))  
   
    def reposo(self):  
        if not self.activo:  
            self.activar()  
        self.ir_pose(list(REPOSO))  
   
# ---------------------------------------------------------------------  
# Carga automatica de poses ensenadas  
# ---------------------------------------------------------------------  
if os.path.exists(ARCHIVO_POSES):  
    try:  
        cargar_poses()  
    except (ValueError, KeyError, json.JSONDecodeError) as _e:  
        AVISO_POSES = str(_e)  
        print(f"[robot] poses_ensenadas.json incompleto: {AVISO_POSES}")  
   
# ---------------------------------------------------------------------  
# Linea de comandos  
# ---------------------------------------------------------------------  
def cmd_tabla():  
    print(f"Modo: {modo()}\nAlcance por casilla (OK = llega en altura segura y de agarre)\n")  
    print("    " + "".join(f"{c:^5}" for c in "ABCDEFGH"))  
    fallos = []  
    for fila in range(8, 0, -1):  
        celdas = ""  
        for col in "ABCDEFGH":  
            ok, motivo = alcanzable(f"{col}{fila}")  
            celdas += f"{'OK' if ok else '--':^5}"  
            if not ok:  
                fallos.append((f"{col}{fila}", motivo))  
        print(f"{fila:>3} {celdas}")  
    print(f"\nAlcanzables: {64 - len(fallos)}/64")  
    for n, m in fallos[:8]:  
        print(f"  {n}: {m}")  
    if len(fallos) > 8:  
        print(f"  ... y {len(fallos) - 8} mas")  
   
def cmd_angulos(casilla):  
    print(f"{casilla.upper()}  (modo: {modo()})")  
    print(f"{'':<14}" + "".join(f"{n:>8}" for n in NOMBRES))  
    for texto, nivel, p in (("Sobre (segura)", 0, PINZA_ABIERTA), ("Agarre", 1, PINZA_AGARRE)):  
        pose = pose_en(casilla, nivel, p)  
        print(f"{texto:<14}" + "".join(f"{a:>8}" for a in pose))  
   
def main():  
    ap = argparse.ArgumentParser(description="Cinematica del brazo de ajedrez")  
    ap.add_argument("accion", choices=["tabla", "angulos", "ir", "mover", "reposo"])  
    ap.add_argument("casillas", nargs="*")  
    ap.add_argument("--puerto", help="ej. COM5. Sin puerto = simulacion")  
    ap.add_argument("--bajar", action="store_true", help="con 'ir': baja hasta la altura de agarre")  
    a = ap.parse_args()  
   
    try:  
        if a.accion == "tabla":  
            return cmd_tabla()  
        if a.accion == "angulos":  
            return cmd_angulos(a.casillas[0])  
        brazo = Brazo(a.puerto)  
        if a.puerto and not confirmar_encendido():  
            return  
        if a.accion == "reposo":  
            brazo.reposo()  
        elif a.accion == "ir":  
            brazo.ir_a_casilla(a.casillas[0], a.bajar)  
        else:  
            brazo.mover_pieza(a.casillas[0], a.casillas[1], progreso=lambda s: print(" -", s))  
        print("Listo.")  
    except (IndexError, ValueError, FueraDeAlcance, RuntimeError, TimeoutError) as e:  
        print("ERROR:", e)  
        sys.exit(1)  
   
if __name__ == "__main__":  
    main()  
   
ARDUINO:  
#include <Servo.h>  
   
const byte NUM = 6;  
const byte pines[NUM] = {5, 6, 7, 8, 9, 10};  
   
// Rangos con margen en los extremos 0/180  
const int mn[NUM]  = {3,   60,  3,   3,   3,   10};  
const int mx[NUM]  = {170, 140, 177, 178, 175, 110};  
const int ini[NUM] = {50,  90,  120, 178, 175, 25};  
   
// Velocidad en modo manual: 1ms por grado (mas alto = mas lento)  
const int tickMs[NUM] = {20, 35, 25, 20, 20, 20};  
const int HOLD_MS = 150;        // sin tecla por este tiempo = frena  
const int pausaGradoMs = 20;    // para test e inicial  
   
Servo servos[NUM];  
int pos[NUM];  
int tgt[NUM];  
bool hold[NUM];  
bool moving[NUM];  
unsigned long lastKey[NUM];  
unsigned long lastTick[NUM];  
bool activo = false;  
bool pinzaAlt = false;  
   
enum Modo { MENU, MANUAL };  
Modo modo = MENU;  
   
void nombre(byte i) {  
  switch (i) {  
    case 0: Serial.print(F("Base")); break;  
    case 1: Serial.print(F("Hombro")); break;  
    case 2: Serial.print(F("Codo")); break;  
    case 3: Serial.print(F("Muneca")); break;  
    case 4: Serial.print(F("Gancho")); break;  
    case 5: Serial.print(F("Pinza")); break;  
  }  
}  
   
void setup() {  
  Serial.begin(9600);  
  for (byte i = 0; i < NUM; i++) { pos[i] = ini[i]; tgt[i] = ini[i]; }  
  Serial.println(F("=== BRAZO ROBOTICO ==="));  
  Serial.println(F("Usa PuTTY/Tera Term (9600) para mantener teclas."));  
  Serial.println(F("Deja el brazo en su pose inicial ANTES de la opcion 1."));  
  mostrarMenu();  
}  
   
void loop() {  
  while (Serial.available()) {  
    char c = toupper(Serial.read());  
    if (c == '\n' || c == '\r') continue;  
    if (modo == MENU) menu(c);  
    else manual(c);  
  }  
  if (modo == MANUAL) actualizar();  
}  
   
// ---------- Menus ----------  
void mostrarMenu() {  
  Serial.println(F("\n--- MENU ---"));  
  Serial.println(F("1. Posicion inicial"));  
  Serial.println(F("2. Test"));  
  Serial.println(F("3. Control manual"));  
}  
   
void leyenda() {  
  Serial.println(F("\n--- CONTROL MANUAL (mantener tecla) ---"));  
  Serial.println(F("A / D : Base"));  
  Serial.println(F("W / S : Hombro"));  
  Serial.println(F("E / Q : Codo"));  
  Serial.println(F("Z / C : Muneca"));  
  Serial.println(F("R / F : Gancho"));  
  Serial.println(F("ESPACIO: Pinza (alterna abrir/cerrar)"));  
  Serial.println(F("P: Estado | L: Leyenda | I: Pos. inicial | 0: Menu"));  
}  
   
void menu(char c) {  
  if (c == '1') posicionInicial();  
  else if (c == '2') {  
    if (!activo) { Serial.println(F("Primero opcion 1.")); return; }  
    test();  
    mostrarMenu();  
  }  
  else if (c == '3') {  
    if (!activo) { Serial.println(F("Primero opcion 1.")); return; }  
    modo = MANUAL;  
    leyenda();  
  }  
  else mostrarMenu();  
}  
   
// ---------- Control manual ----------  
void setHold(byte i, int dir) {  
  hold[i] = true;  
  lastKey[i] = millis();  
  tgt[i] = (dir > 0) ? mx[i] : mn[i];   // el limite del codigo es el destino  
}  
   
void manual(char c) {  
  switch (c) {  
    case 'A': setHold(0, -1); break;  
    case 'D': setHold(0, +1); break;  
    case 'W': setHold(1, +1); break;  
    case 'S': setHold(1, -1); break;  
    case 'E': setHold(2, +1); break;  
    case 'Q': setHold(2, -1); break;  
    case 'Z': setHold(3, -1); break;  
    case 'C': setHold(3, +1); break;  
    case 'R': setHold(4, +1); break;  
    case 'F': setHold(4, -1); break;  
    case ' ':  
      pinzaAlt = !pinzaAlt;  
      hold[5] = false;                       // va hasta el extremo sin mantener  
      tgt[5] = pinzaAlt ? mx[5] : ini[5];  
      break;  
    case 'I': detener(); posicionInicial(); break;  
    case 'P': estado(); break;  
    case 'L': leyenda(); break;  
    case '0': detener(); modo = MENU; mostrarMenu(); break;  
  }  
}  
   
void detener() {  
  for (byte i = 0; i < NUM; i++) { hold[i] = false; tgt[i] = pos[i]; moving[i] = false; }  
}  
   
void actualizar() {  
  unsigned long ahora = millis();  
  for (byte i = 0; i < NUM; i++) {  
    if (hold[i] && ahora - lastKey[i] > HOLD_MS) {   // solto la tecla  
      hold[i] = false;  
      tgt[i] = pos[i];  
    }  
    if (pos[i] != tgt[i]) {  
      if (ahora - lastTick[i] >= tickMs[i]) {  
        lastTick[i] = ahora;  
        pos[i] += (tgt[i] > pos[i]) ? 1 : -1;  
        pos[i] = constrain(pos[i], mn[i], mx[i]);   // limite duro  
        servos[i].write(pos[i]);  
        moving[i] = true;  
      }  
    } else if (moving[i]) {  
      moving[i] = false;  
      nombre(i); Serial.print(F(": ")); Serial.print(pos[i]);  
      if (pos[i] <= mn[i] || pos[i] >= mx[i]) Serial.print(F("  (LIMITE)"));  
      Serial.println();  
    }  
  }  
}  
   
// ---------- Movimiento bloqueante (inicial y test) ----------  
void mover(byte i, int destino) {  
  destino = constrain(destino, mn[i], mx[i]);  
  while (pos[i] != destino) {  
    pos[i] += (destino > pos[i]) ? 1 : -1;  
    servos[i].write(pos[i]);  
    delay(pausaGradoMs);  
  }  
  tgt[i] = pos[i];  
}  
   
void posicionInicial() {  
  Serial.println(F("Yendo a posicion inicial..."));  
  if (!activo) {  
    // write ANTES de attach: el primer pulso ya sale en la pose inicial  
    for (byte i = 0; i < NUM; i++) {  
      pos[i] = ini[i];  
      tgt[i] = ini[i];  
      servos[i].write(ini[i]);  
      servos[i].attach(pines[i]);  
      nombre(i); Serial.print(F(" activo en ")); Serial.println(ini[i]);  
      delay(600);   // uno por uno para evitar picos de corriente  
    }  
    activo = true;  
  } else {  
    for (int i = NUM - 1; i >= 0; i--) mover(i, ini[i]);   // de liviano a pesado  
  }  
  pinzaAlt = false;  
  Serial.println(F("Listo."));  
  if (modo == MENU) mostrarMenu();  
}  
   
void estado() {  
  for (byte i = 0; i < NUM; i++) {  
    nombre(i);  
    Serial.print(F(": ")); Serial.print(pos[i]);  
    Serial.print(F("  (")); Serial.print(mn[i]);  
    Serial.print(F("-")); Serial.print(mx[i]); Serial.println(F(")"));  
  }  
}  
   
// ---------- Test ----------  
void idaVuelta(byte i, int d) {  
  int base = pos[i];  
  nombre(i); Serial.println(F("..."));  
  mover(i, base + d);  
  delay(300);  
  mover(i, base - d);  
  delay(300);  
  mover(i, base);  
  delay(400);  
}  
   
void test() {  
  Serial.println(F("--- TEST (brazo libre de obstaculos) ---"));  
  idaVuelta(5, 30);   // pinza  
  idaVuelta(4, 30);   // gancho  
  idaVuelta(3, 30);   // muneca  
  idaVuelta(2, 20);   // codo  
  idaVuelta(1, 15);   // hombro  
  idaVuelta(0, 30);   // base  
  Serial.println(F("Volviendo a posicion inicial..."));  
  for (int i = NUM - 1; i >= 0; i--) mover(i, ini[i]);  
  Serial.println(F("--- Fin del test ---"));  
}  
   
