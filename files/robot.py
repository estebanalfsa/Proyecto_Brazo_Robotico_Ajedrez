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
    python robot.py info                     # que casillas y que angulos de pinza usa de verdad
    python robot.py tabla                    # que casillas alcanza el brazo
    python robot.py angulos E3               # angulos para una casilla
    python robot.py mover E3 G5              # secuencia completa E3 -> G5
    python robot.py ir E3 --bajar --puerto COM5   # solo ir a una casilla (para afinar)
    python robot.py reposo --puerto COM5
    python robot.py consola --puerto COM5    # escribes "A1 H1" y el robot mueve la pieza
"""
import argparse
import json
import math
import os
import sys
import time

try:
    import serial
except ImportError:  # pyserial solo hace falta con el robot real
    serial = None

# =====================================================================
# CONFIGURACION COMUN
# =====================================================================
ARCHIVO_POSES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poses_ensenadas.json")

PASOS_VERTICALES = 3           # la bajada/subida se divide en estos pasos
LEVANTE_TRASLADO = 12   # grados de hombro que se levanta el brazo al ir de una casilla a otra
PAUSA_PINZA_S = 0.8            # espera tras abrir/cerrar
# Grados EXTRA que se cierra la pinza mas alla del angulo en que TOCO la pieza al ensenarla.
# Sin esto la sujeta sin fuerza y se le cae. Si resbala: subelo (27...). Si el servo de la
# pinza se calienta o zumba demasiado: bajalo (19, 12...).
APRIETE_PINZA = 25

# Valores por defecto (en modo poses ensenadas se reemplazan por los del archivo,
# que a su vez salen del firmware: asi la tabla vive en UN solo sitio, el .ino).
PINZA_ABIERTA = 90
PINZA_AGARRE = 40
MN = (3, 60, 3, 3, 3, 10)
MX = (170, 140, 177, 178, 175, 110)
REPOSO = (50, 90, 120, 178, 175, 25)
RETIRADA = None                # pose para que el brazo NO tape la camara (se ensena con retirada.py)
NOMBRES = ("Base", "Hombro", "Codo", "Muneca", "Gancho", "Pinza")

def apretar(abierta, agarre):
    """Angulo con el que se SUJETA la pieza: el ensenado + APRIETE_PINZA hacia el lado de cerrar,
    sin pasar del limite del firmware (MN/MX de la pinza)."""
    sentido = 1 if agarre > abierta else -1          # cerrar = alejarse del angulo de 'abierta'
    return max(MN[5], min(MX[5], agarre + sentido * APRIETE_PINZA))


def pinza_apretada():
    return apretar(PINZA_ABIERTA, PINZA_AGARRE)


def info_pinza():
    return (f"Pinza: abierta={PINZA_ABIERTA}, toca la pieza en {PINZA_AGARRE}, "
            f"se cierra a {pinza_apretada()} (apriete +{APRIETE_PINZA}); limites del firmware {MN[5]}-{MX[5]}")


# Casillas que se ensenan: columnas A,C,F,H x filas 1,3,6,8 (indices 0,2,5,7)
NODOS_IDX = (0, 2, 5, 7)
COLS_IDX = (0, 2, 5, 7)                  # columnas A, C, F, H
FILAS_IDX = (0, 1, 2, 3, 4, 5, 6, 7)     # las 8 filas
NODOS = [f"{chr(65 + c)}{r + 1}" for r in FILAS_IDX for c in COLS_IDX]

# =====================================================================
# CONFIGURACION SOLO PARA EL MODO GEOMETRIA (ignorar si usas teach.py)
# =====================================================================
GEOMETRIA_CONFIRMADA = False   # mientras sea False, el modo geometria no mueve el robot real

CASILLA_MM = 30.0              # lado de UNA casilla
BASE_X_MM = 3.5 * CASILLA_MM   # eje de la base, desde el centro de A1 (+X hacia H)
BASE_Y_MM = -70.0              # negativo = detras de la fila 1
H_HOMBRO_MM = 90.0             # altura del eje del hombro sobre el tablero
L1_MM = 110.0                  # eje del hombro -> eje del codo
L2_MM = 110.0                  # eje del codo   -> eje del gancho (servo 5)
LG_MM = 100.0                  # eje del gancho -> punta de la pinza
Z_AGARRE_MM = 20.0             # altura de la punta al agarrar
Z_SEGURA_MM = 90.0             # altura de la punta al desplazarse
CORR_X_MM = 0.0
CORR_Y_MM = 0.0
# servo = OFFSET + SIGNO * angulo_geometrico (grados)
BASE_OFFSET, BASE_SIGNO = 90.0, +1       # 0 = recto al frente (+Y); + = hacia la derecha
HOMBRO_OFFSET, HOMBRO_SIGNO = 90.0, +1   # 0 = brazo superior vertical; + = hacia adelante
CODO_OFFSET, CODO_SIGNO = 90.0, +1       # 0 = antebrazo recto; + = antebrazo baja hacia adelante
GANCHO_OFFSET, GANCHO_SIGNO = 90.0, +1   # 0 = pinza alineada con el antebrazo; + = mas hacia abajo
INCLINACIONES_PINZA = (0, 10, 20, 30, 40)   # 0 = pinza vertical hacia abajo
MUNECA_ROLL = REPOSO[3]
# =====================================================================


class FueraDeAlcance(Exception):
    pass


class Abortado(Exception):
    pass


# ---------------------------------------------------------------------
# Casillas
# ---------------------------------------------------------------------
def nombre_a_indices(nombre):
    """'E3' -> (col=4, fila=2). Lanza ValueError si el nombre no es valido."""
    n = str(nombre).strip().upper()
    if len(n) != 2 or n[0] not in "ABCDEFGH" or n[1] not in "12345678":
        raise ValueError(f"Casilla invalida: {nombre!r}")
    return ord(n[0]) - ord("A"), int(n[1]) - 1


def centro_casilla_mm(nombre):
    col, fila = nombre_a_indices(nombre)
    return col * CASILLA_MM + CORR_X_MM, fila * CASILLA_MM + CORR_Y_MM


# ---------------------------------------------------------------------
# MODO 1: poses ensenadas (interpolacion)
# ---------------------------------------------------------------------
POSES = None
AVISO_POSES = ""
_LIM_ARCHIVO = None


def cargar_poses(ruta=ARCHIVO_POSES):
    """Carga poses_ensenadas.json y activa el modo 1. Sirve aunque solo haya UNA parte del
    tablero ensenada: se usan las casillas completas (segura + agarre). Lanza ValueError si no hay ninguna."""
    global POSES, MN, MX, REPOSO, MUNECA_ROLL, PINZA_ABIERTA, PINZA_AGARRE, _LIM_ARCHIVO, RETIRADA
    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)
    completas = {n: v for n, v in d.get("poses", {}).items() if "segura" in v and "agarre" in v}
    if not completas:
        raise ValueError("todavia no hay ninguna casilla ensenada completa (segura y agarre)")
    if not all(k in d.get("pinza", {}) for k in ("abierta", "agarre")):
        raise ValueError("falta ensenar la pinza (abierta / agarre)")
    lim = d["limites"]
    MN, MX, REPOSO = tuple(lim["mn"]), tuple(lim["mx"]), tuple(lim["reposo"])
    MUNECA_ROLL = REPOSO[3]
    PINZA_ABIERTA, PINZA_AGARRE = int(d["pinza"]["abierta"]), int(d["pinza"]["agarre"])
    r = d.get("retirada")
    RETIRADA = tuple(r) if r and len(r) == 6 and all(MN[i] <= r[i] <= MX[i] for i in range(6)) else None
    _LIM_ARCHIVO = [list(MN), list(MX), list(REPOSO)]
    POSES = completas
    return True


def _lagrange(nodos, i, x):
    """Peso lineal a tramos: 1 en el nodo i, 0 en los demas, recta entre vecinos."""
    xi = nodos[i]
    if i > 0 and nodos[i - 1] <= x <= xi:
        return (x - nodos[i - 1]) / (xi - nodos[i - 1])
    if i < len(nodos) - 1 and xi <= x <= nodos[i + 1]:
        return (nodos[i + 1] - x) / (nodos[i + 1] - xi)
    return 1.0 if x == xi else 0.0


def _tramos_filas():
    """Grupos de filas COMPLETAS (las 4 columnas ensenadas) y CONSECUTIVAS entre las filas de NODOS_IDX."""
    tramos, actual = [], []
    for r in FILAS_IDX:
        if all(f"{chr(65 + c)}{r + 1}" in POSES for c in COLS_IDX):
            actual.append(r)
        elif actual:
            tramos.append(actual)
            actual = []
    if actual:
        tramos.append(actual)
    return tramos


def disponible(casilla):
    """'ensenada' (pose exacta), 'calculada' (interpolada entre filas completas) o None."""
    if POSES is None:
        return None
    if casilla in POSES:
        return "ensenada"
    _, fila = nombre_a_indices(casilla)
    if any(t[0] <= fila <= t[-1] for t in _tramos_filas()):
        return "calculada"
    return None


def _mezcla(nodo, nivel):
    return [(1 - nivel) * a + nivel * b for a, b in zip(nodo["segura"], nodo["agarre"])]


def _pose_ensenada(casilla, nivel, pinza):
    """nivel 0 = altura segura, 1 = altura de agarre (se mezclan linealmente)."""
    col, fila = nombre_a_indices(casilla)
    if casilla in POSES:                                   # casilla ensenada: pose exacta
        p = _mezcla(POSES[casilla], nivel)
    else:
        tramo = next((t for t in _tramos_filas() if t[0] <= fila <= t[-1]), None)
        if tramo is None:
            raise FueraDeAlcance(f"{casilla}: todavia no ensenada (graba esa zona con teach.py)")
        p = [0.0] * 6
        for k, f in enumerate(tramo):
            wf = _lagrange(tramo, k, fila)
            for i, c in enumerate(COLS_IDX):
                w = wf * _lagrange(COLS_IDX, i, col)
                m = _mezcla(POSES[f"{chr(65 + c)}{f + 1}"], nivel)
                for j in range(6):
                    p[j] += w * m[j]
    p[5] = pinza
    for j in range(6):
        if not (MN[j] <= round(p[j]) <= MX[j]):
            raise FueraDeAlcance(f"{casilla}: {NOMBRES[j]} pediria {p[j]:.0f} (rango {MN[j]}-{MX[j]})")
    return [int(round(v)) for v in p]


def casillas_disponibles():
    return [f"{c}{f}" for f in range(1, 9) for c in "ABCDEFGH" if disponible(f"{c}{f}")]


# ---------------------------------------------------------------------
# MODO 2: cinematica inversa (geometria medida)
# ---------------------------------------------------------------------
def _clamp(v):
    return max(-1.0, min(1.0, v))


def _plano(r, z, phi_deg):
    """Plano vertical del brazo. Devuelve (alfa, beta, gamma) en grados o None."""
    phi = math.radians(phi_deg)
    rw = r - LG_MM * math.sin(phi)
    zw = z + LG_MM * math.cos(phi)
    dz = zw - H_HOMBRO_MM
    d = math.hypot(rw, dz)
    if d > L1_MM + L2_MM - 1e-6 or d < abs(L1_MM - L2_MM) + 1e-6 or d < 1e-6:
        return None
    theta_codo = math.degrees(math.acos(_clamp((L1_MM**2 + L2_MM**2 - d**2) / (2 * L1_MM * L2_MM))))
    beta = 180.0 - theta_codo
    eps = math.degrees(math.acos(_clamp((L1_MM**2 + d**2 - L2_MM**2) / (2 * L1_MM * d))))
    delta = math.degrees(math.atan2(rw, dz))
    alfa = delta - eps
    gamma = (180.0 - phi_deg) - (alfa + beta)
    return alfa, beta, gamma


def resolver(x_mm, y_mm, z_mm, pinza, redondear=True):
    """Pose [base, hombro, codo, muñeca, gancho, pinza] para llevar la punta a (x, y, z)."""
    dx = x_mm - BASE_X_MM
    dy = y_mm - BASE_Y_MM
    r = math.hypot(dx, dy)
    psi = math.degrees(math.atan2(dx, dy))
    primer_motivo = None
    for phi in INCLINACIONES_PINZA:
        ang = _plano(r, z_mm, phi)
        if ang is None:
            motivo = f"a {r:.0f} mm de la base no llega el brazo"
        else:
            alfa, beta, gamma = ang
            servos = [
                BASE_OFFSET + BASE_SIGNO * psi,
                HOMBRO_OFFSET + HOMBRO_SIGNO * alfa,
                CODO_OFFSET + CODO_SIGNO * beta,
                MUNECA_ROLL,
                GANCHO_OFFSET + GANCHO_SIGNO * gamma,
                pinza,
            ]
            fuera = [i for i in range(6) if not (MN[i] <= round(servos[i]) <= MX[i])]
            if not fuera:
                return [int(round(s)) for s in servos] if redondear else servos
            i = fuera[0]
            motivo = f"{NOMBRES[i]} pediria {servos[i]:.0f} (rango {MN[i]}-{MX[i]})"
        if primer_motivo is None:
            primer_motivo = motivo
    raise FueraDeAlcance(primer_motivo)


def cinematica_directa(servos):
    """(x, y, z) en mm de la punta de la pinza para una pose de servos (modo geometria)."""
    psi = math.radians((servos[0] - BASE_OFFSET) / BASE_SIGNO)
    alfa = (servos[1] - HOMBRO_OFFSET) / HOMBRO_SIGNO
    beta = (servos[2] - CODO_OFFSET) / CODO_SIGNO
    gamma = (servos[4] - GANCHO_OFFSET) / GANCHO_SIGNO
    a1 = math.radians(alfa)
    a2 = math.radians(alfa + beta)
    a3 = math.radians(alfa + beta + gamma)
    r = L1_MM * math.sin(a1) + L2_MM * math.sin(a2) + LG_MM * math.sin(a3)
    z = H_HOMBRO_MM + L1_MM * math.cos(a1) + L2_MM * math.cos(a2) + LG_MM * math.cos(a3)
    return BASE_X_MM + r * math.sin(psi), BASE_Y_MM + r * math.cos(psi), z


# ---------------------------------------------------------------------
# Interfaz comun a los dos modos
# ---------------------------------------------------------------------
def modo():
    if POSES is not None:
        return f"poses ensenadas ({len(casillas_disponibles())} de 64 casillas disponibles)"
    return "geometria"


def pose_en(casilla, nivel, pinza):
    """Pose de servos sobre una casilla. nivel: 0 = altura segura, 1 = altura de agarre."""
    if POSES is not None:
        return _pose_ensenada(casilla, nivel, pinza)
    x, y = centro_casilla_mm(casilla)
    return resolver(x, y, Z_SEGURA_MM + (Z_AGARRE_MM - Z_SEGURA_MM) * nivel, pinza)


def alcanzable(casilla):
    """(True, '') si el brazo llega a la casilla en altura segura y de agarre."""
    try:
        pose_en(casilla, 0, PINZA_ABIERTA)
        pose_en(casilla, 1, PINZA_ABIERTA)
        return True, ""
    except FueraDeAlcance as e:
        return False, str(e)


def _niveles_bajada():
    n = max(1, PASOS_VERTICALES)
    return [k / n for k in range(1, n + 1)]


def pose_retirada():
    """Pose guardada con retirada.py, tal cual (la pinza conserva el angulo ensenado).
    Si no se ensenio, el reposo."""
    if RETIRADA is None:
        return list(REPOSO)
    return list(RETIRADA)

def elevar(pose):
    p = list(pose)
    p[1] = max(MN[1], p[1] - LEVANTE_TRASLADO)   # menos hombro = punta mas alta
    return p

def planificar(origen, destino):
    """Calcula TODAS las poses antes de mover nada. Devuelve [(descripcion, pose), ...].
    Lanza FueraDeAlcance (indicando la casilla) si alguna pose no es posible."""
    A, C = PINZA_ABIERTA, pinza_apretada()
    bajada = _niveles_bajada()
    subida = [1 - v for v in bajada]
    pasos = []

    def ik(casilla, nivel, pinza):
        try:
            return pose_en(casilla, nivel, pinza)
        except FueraDeAlcance as e:
            msg = str(e)
            raise FueraDeAlcance(msg if msg.startswith(casilla) else f"{casilla}: {msg}") from None

    def tramo(casilla, niveles, pinza, texto):
        for v in niveles:
            pasos.append((texto, ik(casilla, v, pinza)))

    pasos.append((f"Sobre {origen}", ik(origen, 0, A)))
    tramo(origen, bajada, A, f"Bajando a {origen}")
    pasos.append(("Cerrando pinza", ik(origen, 1, C)))
    tramo(origen, subida, C, f"Subiendo de {origen}")
    pasos.append(("Levantando para trasladar", elevar(ik(origen, 0, C))))
    pasos.append((f"Trasladando a {destino}", elevar(ik(destino, 0, C))))
    pasos.append((f"Sobre {destino}", ik(destino, 0, C)))
    tramo(destino, bajada, C, f"Bajando a {destino}")
    pasos.append(("Abriendo pinza", ik(destino, 1, A)))
    tramo(destino, subida, A, f"Subiendo de {destino}")
    pasos.append(("Retirando el brazo", pose_retirada()))
    return pasos


def verificar_modo_real():
    """Impide mover el robot REAL sin poses ensenadas ni geometria confirmada."""
    if POSES is None and not GEOMETRIA_CONFIRMADA:
        extra = f" ({AVISO_POSES})" if AVISO_POSES else ""
        raise RuntimeError("No hay casillas ensenadas utilizables" + extra + ". Ejecuta teach.py "
                           "(recomendado) o mide el brazo y pon GEOMETRIA_CONFIRMADA = True")


def confirmar_encendido(pose="de reposo, apoyado en sus topes"):
    """Secuencia segura. El Arduino se REINICIA al abrir el puerto y los servos pierden la senal
    (un servo sin senal no sujeta nada), por eso la fuente de los servos debe estar apagada hasta aqui."""
    print(f"\n1) El brazo debe estar FISICAMENTE en la pose {pose}.")
    print("2) Enciende AHORA la fuente de los servos (hasta este momento debia estar apagada).")
    return input("Pulsa Enter para activar (n = cancelar): ").strip().lower() != "n"


# ---------------------------------------------------------------------
# Comunicacion con el Arduino
# ---------------------------------------------------------------------
class Brazo:
    def __init__(self, puerto=None, baudios=9600):
        self.ser = None
        self.activo = False
        self.ocupado = False
        self._abortar = False
        self._lineas = []
        if puerto:
            if serial is None:
                raise RuntimeError("Falta pyserial: pip install pyserial")
            try:
                self.ser = serial.Serial(puerto, baudios, timeout=0.5)
            except serial.SerialException as e:
                raise RuntimeError(f"No se pudo abrir {puerto} (cierra el Monitor Serial del IDE): {e}") from None
            time.sleep(2.0)                    # el Arduino se reinicia al abrir el puerto
            self.ser.reset_input_buffer()

    @property
    def simulado(self):
        return self.ser is None

    def _enviar(self, linea, timeout=60.0):
        if self.simulado:
            print(f"   [SIM] {linea}")
            return
        self._lineas = []
        self.ser.write((linea + "\n").encode("ascii"))
        fin = time.time() + timeout
        while time.time() < fin:
            resp = self.ser.readline().decode("ascii", errors="ignore").strip()
            if not resp:
                continue
            if resp.startswith("OK"):
                return
            if resp.startswith("ERR"):
                raise RuntimeError(f"Arduino respondio: {resp}")
            self._lineas.append(resp)
        raise TimeoutError(f"El Arduino no respondio OK a '{linea}'")

    def leer_limites(self):
        """(mn, mx, reposo) tal como estan en el firmware. En simulacion, los de robot.py."""
        if self.simulado:
            return list(MN), list(MX), list(REPOSO)
        self._enviar("L", timeout=5)
        datos = {}
        for linea in self._lineas:
            p = linea.split()
            if len(p) == 8 and p[0] == "LIM":
                datos[p[1]] = [int(v) for v in p[2:]]
        if not all(k in datos for k in "nxi"):
            raise RuntimeError("El firmware no informo sus limites: sube la version nueva de brazo_serial.ino")
        return datos["n"], datos["x"], datos["i"]

    def activar(self, desde=None):
        """El brazo debe estar FISICAMENTE en 'desde' (o en reposo si desde es None)."""
        global MN, MX, REPOSO, MUNECA_ROLL
        mn, mx, ini = self.leer_limites()          # se leen ANTES de activar
        if POSES is not None and _LIM_ARCHIVO is not None and [mn, mx, ini] != _LIM_ARCHIVO:
            raise RuntimeError("Los limites del firmware cambiaron desde que ensenaste las casillas "
                               "(recalibraste?). Vuelve a ejecutar teach.py --rehacer")
        if POSES is None:
            MN, MX, REPOSO = tuple(mn), tuple(mx), tuple(ini)
            MUNECA_ROLL = REPOSO[3]
        cmd = "A" if desde is None else "A " + " ".join(str(int(a)) for a in desde)
        self._enviar(cmd, timeout=30)
        self.activo = True

    def ir_pose(self, pose):
        if self._abortar:
            raise Abortado()
        self._enviar("G " + " ".join(str(int(a)) for a in pose))
        if self._abortar:
            raise Abortado()

    def parar(self):
        """Parada de emergencia: congela los servos donde esten y cancela la secuencia."""
        self._abortar = True
        if self.ser is not None:
            try:
                self.ser.write(b"X\n")
            except Exception:
                pass

    def mover_pieza(self, origen, destino, progreso=None):
        self.ocupado = True
        try:
            pasos = planificar(origen, destino)   # falla ANTES de mover si no hay alcance
            if not self.simulado:
                verificar_modo_real()
            self._abortar = False
            if not self.activo:
                self.activar()
            for desc, pose in pasos:
                if progreso:
                    progreso(desc)
                self.ir_pose(pose)
                if desc.startswith(("Cerrando", "Abriendo")):
                    time.sleep(PAUSA_PINZA_S if not self.simulado else 0.1)
                elif self.simulado:
                    time.sleep(0.1)
        finally:
            self.ocupado = False

    def ir_a_casilla(self, casilla, bajar=False, progreso=None):
        """Solo para afinar: va sobre una casilla (y opcionalmente baja a la altura de agarre)."""
        poses = [("Sobre " + casilla, pose_en(casilla, 0, PINZA_ABIERTA))]
        if bajar:
            poses += [("Bajando", pose_en(casilla, v, PINZA_ABIERTA)) for v in _niveles_bajada()]
        if not self.simulado:
            verificar_modo_real()
        self._abortar = False
        if not self.activo:
            self.activar()
        for texto, pose in poses:
            if progreso:
                progreso(texto)
            self.ir_pose(pose)

    def retirar(self):
        """Lleva el brazo a la pose de retirada (fuera del encuadre de la camara)."""
        if not self.activo:
            self.activar()
        self.ir_pose(pose_retirada())

    def reposo(self):
        if not self.activo:
            self.activar()
        self.ir_pose(list(REPOSO))


# ---------------------------------------------------------------------
# Carga automatica de poses ensenadas
# ---------------------------------------------------------------------
if os.path.exists(ARCHIVO_POSES):
    try:
        cargar_poses()
    except (ValueError, KeyError, json.JSONDecodeError) as _e:
        AVISO_POSES = str(_e)
        print(f"[robot] poses_ensenadas.json incompleto: {AVISO_POSES}")


# ---------------------------------------------------------------------
# Linea de comandos
# ---------------------------------------------------------------------
def cmd_tabla():
    print(f"Modo: {modo()}")
    print("##  = casilla ENSENADA (pose exacta)   OK = casilla CALCULADA entre filas ensenadas   -- = todavia no\n")
    print("    " + "".join(f"{c:^5}" for c in "ABCDEFGH"))
    sin = []
    for fila in range(8, 0, -1):
        celdas = ""
        for col in "ABCDEFGH":
            n = f"{col}{fila}"
            ok, motivo = alcanzable(n)
            tipo = disponible(n) if POSES is not None else ("calculada" if ok else None)
            marca = "##" if tipo == "ensenada" else ("OK" if ok else "--")
            celdas += f"{marca:^5}"
            if not ok:
                sin.append((n, motivo))
        print(f"{fila:>3} {celdas}")
    print(f"\nUtilizables: {64 - len(sin)}/64")
    for n, m in sin[:6]:
        print(f"  {n}: {m}")
    if len(sin) > 6:
        print(f"  ... y {len(sin) - 6} mas")


def cmd_info():
    print(f"Modo: {modo()}")
    print(info_pinza())
    print("Retirada:", list(RETIRADA) if RETIRADA else "no ensenada (usa retirada.py): se vuelve al reposo")
    if POSES is not None:
        print("Casillas ensenadas:", " ".join(sorted(POSES)))
        print("Limites del firmware (mn):", list(MN))
        print("Limites del firmware (mx):", list(MX))
        print("Reposo:", list(REPOSO))
    else:
        print("Aun no hay casillas ensenadas utilizables (usa teach.py).")


def cmd_angulos(casilla):
    print(f"{casilla.upper()}  (modo: {modo()})")
    print(f"{'':<14}" + "".join(f"{n:>8}" for n in NOMBRES))
    for texto, nivel, p in (("Sobre (segura)", 0, PINZA_ABIERTA), ("Agarre", 1, pinza_apretada())):
        pose = pose_en(casilla, nivel, p)
        print(f"{texto:<14}" + "".join(f"{a:>8}" for a in pose))


def cmd_consola(brazo, piezas):
    """Escribes 'A1 H1' y el robot lleva la pieza. Lleva la cuenta de que casillas tienen pieza
    (a mano, hasta que se enlace con la camara): no deja mover desde una casilla vacia ni hacia una ocupada."""
    ocupadas = set(piezas)
    piezas_anotadas = bool(ocupadas)
    print(f"Modo: {modo()}")
    print(info_pinza())
    print("Escribe  ORIGEN DESTINO  (ej. A1 H1).  Otros comandos:")
    print("  pon A1 / quita A1 = anotar a mano una pieza | piezas = ver | tabla | reposo | q = salir")
    print("  (Ctrl+C durante un movimiento = PARADA)")
    if not ocupadas:
        print("Sin piezas anotadas: la primera orden asume que hay una pieza en el origen.")
    while True:
        try:
            txt = input("\n> ").strip().upper().replace(",", " ").replace("->", " ")
        except (EOFError, KeyboardInterrupt):
            break
        partes = txt.split()
        if not partes:
            continue
        try:
            if partes[0] in ("Q", "SALIR", "EXIT"):
                break
            elif partes[0] == "TABLA":
                cmd_tabla()
            elif partes[0] == "PIEZAS":
                print("Piezas anotadas:", " ".join(sorted(ocupadas)) or "ninguna")
            elif partes[0] == "REPOSO":
                brazo.reposo()
                print("En reposo.")
            elif partes[0] in ("PON", "QUITA") and len(partes) == 2:
                nombre_a_indices(partes[1])
                (ocupadas.add if partes[0] == "PON" else ocupadas.discard)(partes[1])
                print("Piezas anotadas:", " ".join(sorted(ocupadas)) or "ninguna")
            elif len(partes) == 2:
                o, d = partes
                nombre_a_indices(o)
                nombre_a_indices(d)
                if not ocupadas and not piezas_anotadas:
                    ocupadas.add(o)                       # primera orden sin anotar nada: se asume pieza en el origen
                    piezas_anotadas = True
                    print(f"(No habias anotado piezas: asumo que hay una en {o}.)")
                if o == d:
                    print("Origen y destino son la misma casilla.")
                elif o not in ocupadas:
                    print(f"No hay pieza en {o} (si la hay, anotala con:  pon {o})")
                elif d in ocupadas:
                    print(f"{d} esta OCUPADA: no se puede mover ahi. Elige otra casilla de destino.")
                else:
                    planificar(o, d)                      # avisa antes de mover si falta alcance
                    brazo.mover_pieza(o, d, progreso=lambda t: print("  -", t))
                    ocupadas.discard(o)
                    ocupadas.add(d)
                    print(f"Listo: {o} -> {d}.  Piezas anotadas:", " ".join(sorted(ocupadas)))
            else:
                print("No entendi. Ejemplo:  A1 H1")
        except KeyboardInterrupt:
            brazo.parar()
            print("\nPARADA. El brazo se detuvo donde estaba (revisa la pieza).")
        except (ValueError, FueraDeAlcance, RuntimeError, TimeoutError, Abortado) as e:
            print("ERROR:", e)


def main():
    ap = argparse.ArgumentParser(description="Cinematica del brazo de ajedrez")
    ap.add_argument("accion", choices=["tabla", "info", "angulos", "ir", "mover", "reposo", "consola"])
    ap.add_argument("casillas", nargs="*")
    ap.add_argument("--puerto", help="ej. COM5. Sin puerto = simulacion")
    ap.add_argument("--bajar", action="store_true", help="con 'ir': baja hasta la altura de agarre")
    ap.add_argument("--piezas", default="", help="con 'consola': casillas con pieza al empezar, ej. A1,B1")
    a = ap.parse_args()

    try:
        if a.accion == "tabla":
            return cmd_tabla()
        if a.accion == "info":
            return cmd_info()
        if a.accion == "angulos":
            return cmd_angulos(a.casillas[0])
        print(f"Modo: {modo()}")
        print(info_pinza())
        brazo = Brazo(a.puerto)
        if a.puerto and not confirmar_encendido():
            return
        if a.accion == "consola":
            return cmd_consola(brazo, [x.strip().upper() for x in a.piezas.split(",") if x.strip()])
        if a.accion == "reposo":
            brazo.reposo()
        elif a.accion == "ir":
            brazo.ir_a_casilla(a.casillas[0], a.bajar, progreso=lambda t: print(" -", t))
        else:
            brazo.mover_pieza(a.casillas[0], a.casillas[1], progreso=lambda t: print(" -", t))
        print("Listo.")
    except (IndexError, ValueError, FueraDeAlcance, RuntimeError, TimeoutError) as e:
        print("ERROR:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()