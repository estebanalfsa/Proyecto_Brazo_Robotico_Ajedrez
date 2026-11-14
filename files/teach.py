"""
teach.py - Ensenarle al robot las casillas, como una maquina de garra
=====================================================================
Necesitas UNA sola pieza. El robot la lleva de casilla en casilla. En cada casilla TU enseñas
solo dos posiciones (G = guardar); abrir, cerrar, subir, soltar y volver a agarrar lo hace el robot.

PREPARACION (solo la primera vez): el robot aun no sabe que angulo es "pinza abierta" y cual "pinza
agarrando"; se los ensenas una vez (2 pulsaciones de G) y no vuelve a preguntar.
Guardas el angulo donde la pinza TOCA la pieza; al sujetarla el robot aprieta solo unos grados mas
(APRIETE_PINZA en robot.py) para que no se le caiga.

PRIMERA CASILLA (A1), con la pieza puesta en su centro:
  PASO 1  llevas la pinza encima de la pieza (altura segura)                  G -> la pinza se ABRE sola
  PASO 2  bajas hasta que la pinza rodee la pieza a media altura              G -> la pinza se CIERRA sola,
                                                                                   sube con la pieza y espera
SIGUIENTES CASILLAS (C1, F1, H1, ...), el robot lleva la pieza agarrada:
  PASO 1  la llevas encima de la casilla (altura segura)                      G
  PASO 2  bajas hasta apoyarla en el centro                                   G -> la SUELTA, sube, baja,
                                                                                   la agarra y sube (comprobacion)
  Despues:  G = seguir | B = repetir esa casilla | T = terminar aqui (deja la pieza y vuelve a reposo)

Se guarda tras cada G: puedes parar cuando quieras (por ejemplo, tras la fila 1) y seguir otro dia.
Despues:   python robot.py tabla                       (que casillas ya puede)
           python robot.py mover A1 H1 --puerto COM6   (reproduce: agarra en A1, suelta en H1)
           python robot.py consola --puerto COM6       (escribes "A1 H1" y se mueve)

Uso (en una terminal, no en IDLE):
    python teach.py --puerto COM6                # sigue donde lo dejaste (orden: A1 C1 F1 H1 H3 F3 ...)
    python teach.py --puerto COM6 --fila 1       # solo la primera fila (A1 C1 F1 H1) y termina
    python teach.py --puerto COM6 --rehacer      # empieza de cero (guarda copia de lo anterior en .bak)
    python teach.py --puerto COM6 --solo A1,C1   # solo esas casillas (ej. para una prueba rapida A1 -> C1)
    python teach.py --puerto COM6 --pinza        # reensena SOLO los dos angulos de la pinza (no borra casillas)
    python teach.py                              # simulacion, para ver como funciona

ORIENTACION (importante): ponte DETRAS del robot, mirando hacia el tablero.
    A1 = la esquina del tablero MAS CERCANA al robot, a SU IZQUIERDA.
    H1 = cercana, a su derecha | A8 = lejana, a su izquierda | H8 = lejana, a su derecha.
    Las filas se cuentan desde el robot (fila 1 = la mas cercana). NO muevas el tablero
    despues de ensenar (marca su posicion con cinta).

Teclas:
    A / D   base  -/+            W / S   hombro +/-        E / Q   codo +/-
    R / F   gancho +/-           Z / C   pinza -/+  (tambien [ y ] )
    ESPACIO alterna la pinza entre sus dos extremos (los ensenados, cuando ya existen)
    1 / 2 / 3   tamano del paso (1, 3 o 6 grados)   (mantener una tecla = mover continuo)
    G guardar y seguir | B volver al paso anterior | L repetir esta ayuda | 0 o Esc salir
    (con la pieza agarrada la pinza queda bloqueada, para que no se suelte por error)
"""
import argparse
import json
import os
import sys
import time

import robot

ARCHIVO = robot.ARCHIVO_POSES
PASOS_GRADOS = {"1": 1, "2": 3, "3": 6}
TECLAS = {
    "a": (0, -1), "d": (0, +1),
    "w": (1, +1), "s": (1, -1),
    "e": (2, +1), "q": (2, -1),
    "r": (4, +1), "f": (4, -1),
    "z": (5, -1), "c": (5, +1),        # pinza (en teclado espanol [ y ] cuestan: AltGr)
    "[": (5, -1), "]": (5, +1),
}
SOLO_PINZA = (5,)


class Salir(Exception):
    pass


class ErrorRobot(Exception):
    pass


class Teclado:
    """Lee teclas sin pulsar Enter. Windows: msvcrt. Linux/Mac: termios."""

    def __enter__(self):
        if os.name != "nt":
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            self.viejo = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        return self

    def __exit__(self, *args):
        if os.name != "nt":
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.viejo)

    def _hay(self):
        if os.name == "nt":
            import msvcrt
            return msvcrt.kbhit()
        import select
        return bool(select.select([self.fd], [], [], 0)[0])

    def _char(self):
        if os.name == "nt":
            import msvcrt
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):      # tecla especial (flechas...): se descarta
                msvcrt.getwch()
                return ""
            return ch
        return os.read(self.fd, 1).decode(errors="ignore")

    def leer(self):
        """Espera una tecla y la devuelve en minuscula."""
        while True:
            ch = self._char()
            if ch:
                return ch.lower()

    def repeticiones(self, tecla):
        """Cuenta (y consume) las repeticiones pendientes de la MISMA tecla (tecla mantenida)."""
        n = 0
        while self._hay():
            if self._char().lower() == tecla:
                n += 1
        return n


# ---------------------------------------------------------------------
# Ayudas visuales
# ---------------------------------------------------------------------
def orden_casillas():
    cols = [chr(65 + c) for c in robot.COLS_IDX]
    orden = []
    for i, r in enumerate(robot.FILAS_IDX):
        for c in (cols if i % 2 == 0 else cols[::-1]):
            orden.append(f"{c}{r + 1}")
    return orden


def descripcion(nombre):
    """Donde esta la casilla, vista desde detras del robot."""
    c, f = robot.nombre_a_indices(nombre)
    esquinas = {"A1": "ESQUINA cercana al robot, a su izquierda", "H1": "ESQUINA cercana al robot, a su derecha",
                "A8": "ESQUINA lejana, a la izquierda del robot", "H8": "ESQUINA lejana, a la derecha del robot"}
    if nombre in esquinas:
        return esquinas[nombre]
    return f"columna {c + 1} de 8 contando desde la izquierda del robot, fila {f + 1} de 8 contando desde el robot"


def hecha(datos, n):
    return len(datos["poses"].get(n, {})) == 2


def mapa(datos, actual):
    """Tablero en ASCII: X = casilla actual, # = ya ensenada, o = pendiente, . = se calcula sola."""
    lineas = ["        A  B  C  D  E  F  G  H"]
    for r in range(8, 0, -1):
        fila = f"    {r}   "
        for col in "ABCDEFGH":
            n = f"{col}{r}"
            if n == actual:
                marca = "X"
            elif hecha(datos, n):
                marca = "#"
            elif n in robot.NODOS:
                marca = "o"
            else:
                marca = "."
            fila += marca + "  "
        lineas.append(fila)
    lineas.append("        ^ abajo = LADO DEL ROBOT")
    lineas.append("    X = esta   # = hecha   o = pendiente   . = se calcula sola")
    return "\n".join(lineas)


def guardar(datos):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=1)


# ---------------------------------------------------------------------
# Sesion de ensenanza
# ---------------------------------------------------------------------
class Sesion:
    def __init__(self, brazo, datos, mn, mx, ini, tec):
        self.brazo, self.datos, self.mn, self.mx, self.ini, self.tec = brazo, datos, mn, mx, ini, tec
        self.pose = list(ini)
        self.paso = 3
        self.agf = None                  # angulo con que se SUJETA la pieza (ensenado + apriete)

    def calcular_apriete(self):
        pz = self.datos["pinza"]
        self.agf = robot.apretar(pz["abierta"], pz["agarre"])
        return self.agf

    # --- movimiento ---
    def ir(self, pose=None):
        if pose is not None:
            self.pose = list(pose)
        try:
            self.brazo.ir_pose(self.pose)
        except (RuntimeError, TimeoutError, robot.Abortado) as e:
            raise ErrorRobot(str(e)) from None

    def pinza(self, grados):
        if self.pose[5] == grados:
            return
        self.pose[5] = grados
        self.ir()
        if not self.brazo.simulado:
            time.sleep(robot.PAUSA_PINZA_S)

    def _mezcla(self, nombre, v, pinza):
        p = self.datos["poses"][nombre]
        pose = [int(round((1 - v) * a + v * b)) for a, b in zip(p["segura"], p["agarre"])]
        pose[5] = pinza
        return pose

    def bajar(self, nombre, pinza):
        n = max(1, robot.PASOS_VERTICALES)
        for k in range(1, n + 1):
            self.ir(self._mezcla(nombre, k / n, pinza))

    def subir(self, nombre, pinza):
        n = max(1, robot.PASOS_VERTICALES)
        for k in range(1, n + 1):
            self.ir(self._mezcla(nombre, 1 - k / n, pinza))

    # --- teclado ---
    def jog(self, titulo, texto, bloquear_pinza=False):
        """Mueve el brazo con el teclado. Devuelve 'g' (guardar) o 'b' (volver)."""
        print("\n" + titulo)
        print(texto)
        while True:
            print(f"\r  pose {self.pose}  paso {self.paso} grados  ", end="", flush=True)
            k = self.tec.leer()
            if k in TECLAS:
                j, d = TECLAS[k]
                if j in SOLO_PINZA and bloquear_pinza:
                    print("\n  la pinza esta bloqueada: lleva la pieza agarrada")
                    continue
                n = 1 + self.tec.repeticiones(k)
                nuevo = max(self.mn[j], min(self.mx[j], self.pose[j] + d * self.paso * n))
                if nuevo != self.pose[j]:
                    self.pose[j] = nuevo
                    self.ir()
                else:
                    print(f"\n  limite del {robot.NOMBRES[j]} ({nuevo})")
            elif k == " ":
                if bloquear_pinza:
                    print("\n  la pinza esta bloqueada: lleva la pieza agarrada")
                    continue
                a, g = self.datos["pinza"].get("abierta"), self.datos["pinza"].get("agarre")
                if a is not None and g is not None:
                    destino = g if self.pose[5] == a else a
                else:                               # aun sin ensenar: va al extremo mas lejano
                    destino = self.mn[5] if abs(self.pose[5] - self.mn[5]) > abs(self.pose[5] - self.mx[5]) else self.mx[5]
                self.pinza(destino)
            elif k in PASOS_GRADOS:
                self.paso = PASOS_GRADOS[k]
            elif k == "l":
                print("\nTeclas:" + __doc__.split("Teclas:")[1])
            elif k in ("g", "b"):
                print()
                return k
            elif k in ("0", "\x1b"):
                raise Salir()

    def esperar(self, texto, validas=("g",)):
        """Imprime un mensaje y espera una de las teclas validas."""
        print("\n" + texto)
        while True:
            k = self.tec.leer()
            if k in validas:
                return k
            if k in ("0", "\x1b"):
                raise Salir()

    def guardar_pose(self, nombre, nivel):
        self.datos["poses"].setdefault(nombre, {})[nivel] = list(self.pose)
        guardar(self.datos)
        print(f"  guardado: {nombre} / {nivel}")


# ---------------------------------------------------------------------
# Preparacion de la pinza (solo la primera vez)
# ---------------------------------------------------------------------
def ensenar_pinza(ses, forzar=False):
    pz = ses.datos["pinza"]
    if forzar:
        pz.pop("abierta", None)
        pz.pop("agarre", None)
    if "abierta" not in pz:
        while ses.jog("PINZA 1 de 2 - ABIERTA",
                      "  Abre la pinza (ESPACIO o Z/C) lo justo para rodear una pieza con holgura.   G = guardar") != "g":
            pass
        pz["abierta"] = ses.pose[5]
        guardar(ses.datos)
        print(f"  guardado: pinza abierta = {pz['abierta']}")
    if "agarre" not in pz:
        while ses.jog("PINZA 2 de 2 - AGARRE",
                      "  Pon una pieza entre los dedos con la mano y cierra (Z / C) justo hasta que la TOQUE\n"
                      "  y quede sujeta (el robot apretara solo unos grados mas).   G = guardar") != "g":
            pass
        pz["agarre"] = ses.pose[5]
        guardar(ses.datos)
        print(f"  guardado: pinza agarre = {pz['agarre']}")
        print("  La pinza se abre sola. Retira la pieza.")
        ses.pinza(pz["abierta"])


# ---------------------------------------------------------------------
# Las dos clases de casilla
# ---------------------------------------------------------------------
def casilla_inicial(ses, n):
    """La pieza esta puesta (por ti) en el centro de n y el robot todavia NO la lleva."""
    pz = ses.datos["pinza"]
    ab, ag = pz["abierta"], ses.calcular_apriete()
    ses.pinza(ag)                                      # pinza cerrada para posicionar
    j = 0
    while j < 2:
        if j == 0:
            r = ses.jog("PASO 1 - ALTURA SEGURA",
                        f"  Pon la pinza (cerrada) encima de la pieza en {n}, bien centrada y a una altura que\n"
                        f"  pase por encima de cualquier otra pieza.   G = guardar (el robot abrira la pinza)")
        else:
            r = ses.jog("PASO 2 - ALTURA DE AGARRE",
                        "  Baja hasta que la pinza abierta rodee la pieza a media altura.\n"
                        "  G = guardar (el robot cerrara la pinza y subira con la pieza)")
        if r == "b":
            if j == 0:
                print("  (ya estas en el primer paso de esta casilla)")
            j = max(0, j - 1)
            continue
        ses.guardar_pose(n, "segura" if j == 0 else "agarre")
        if j == 0:
            print("  El robot abre la pinza...")
            ses.pinza(ab)
        j += 1
    print("  El robot cierra la pinza y sube con la pieza...")
    ses.pinza(ag)
    ses.subir(n, ag)


def casilla_llevando(ses, n):
    """El robot lleva la pieza agarrada. Devuelve 'ok', 'repetir' o 'terminar'."""
    pz = ses.datos["pinza"]
    ab, ag = pz["abierta"], ses.calcular_apriete()
    j = 0
    while j < 2:
        if j == 0:
            r = ses.jog("PASO 1 - ALTURA SEGURA",
                        f"  El robot LLEVA la pieza (pinza cerrada). Llevala encima de {n}, centrada y a la\n"
                        f"  misma altura segura de antes.   G = guardar", bloquear_pinza=True)
        else:
            r = ses.jog("PASO 2 - ALTURA DE APOYO",
                        f"  Baja hasta que la pieza quede apoyada en el centro de {n}.\n"
                        f"  G = guardar (el robot suelta la pieza, sube, baja, la agarra y sube: comprobacion)",
                        bloquear_pinza=True)
        if r == "b":
            if j == 0:
                print("  (ya estas en el primer paso de esta casilla)")
            j = max(0, j - 1)
            continue
        ses.guardar_pose(n, "segura" if j == 0 else "agarre")
        j += 1
    print("  El robot comprueba: suelta la pieza, sube, baja, la agarra y sube...")
    ses.pinza(ab)
    ses.subir(n, ab)
    ses.bajar(n, ab)
    ses.pinza(ag)
    ses.subir(n, ag)
    r = ses.esperar(f"COMPROBACION de {n}: agarro bien la pieza?\n"
                    f"  G = si, seguir | B = no, repetir {n} | T = terminar aqui (deja la pieza y vuelve a reposo)",
                    validas=("g", "b", "t"))
    if r == "g":
        return "ok"
    if r == "t":
        return "terminar"
    print(f"  El robot suelta la pieza. Ponla a mano en el centro de {n} y repite esta casilla.")
    ses.pinza(ab)
    ses.esperar(f"Cuando la pieza este en el centro de {n}, pulsa G.")
    return "repetir"


def ensenar(ses, nodos):
    inicio_manual = True          # en la primera casilla de la corrida la pieza la pones tu
    i = 0
    while i < len(nodos):
        n = nodos[i]
        print("\n" + "=" * 70)
        print(f"CASILLA {i + 1} de {len(nodos)}: {n} - {descripcion(n)}")
        print(mapa(ses.datos, n))
        if inicio_manual:
            if i == 0:
                ses.esperar(f"Pon UNA pieza en el centro de {n} y pulsa G para empezar.")
            casilla_inicial(ses, n)
            r = "ok"
        else:
            r = casilla_llevando(ses, n)
        if r == "repetir":
            inicio_manual = True
            continue
        if r == "terminar":
            break
        inicio_manual = False
        i += 1
    n = nodos[min(i, len(nodos) - 1)]
    pz = ses.datos["pinza"]
    print(f"\nFin. El robot deja la pieza en {n} y vuelve a reposo...")
    ses.bajar(n, ses.calcular_apriete())
    ses.pinza(pz["abierta"])
    ses.subir(n, pz["abierta"])
    ses.ir(list(ses.ini))


# ---------------------------------------------------------------------
def main(argv=None, teclado=None, brazo=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", help="ej. COM6. Sin puerto = simulacion")
    ap.add_argument("--rehacer", action="store_true", help="empieza de cero (copia de lo anterior en .bak)")
    ap.add_argument("--solo", help="repite solo estas casillas, ej. C1,H3 (no borra las demas)")
    ap.add_argument("--fila", help="solo las casillas de esta(s) fila(s), ej. 1  o  1,3")
    ap.add_argument("--pinza", action="store_true", help="reensena SOLO los angulos de la pinza (no borra casillas)")
    args = ap.parse_args(argv)

    solo = [x.strip().upper() for x in args.solo.split(",")] if args.solo else None
    if solo:
        malas = [n for n in solo if n not in robot.NODOS]
        if malas:
            print(f"ERROR: {', '.join(malas)} no se ensena. Las casillas ensenadas son: {' '.join(orden_casillas())}")
            return 1
    filas = None
    if args.fila:
        try:
            filas = [int(x) for x in args.fila.split(",")]
        except ValueError:
            filas = []
        if not filas or any(f not in [r + 1 for r in robot.NODOS_IDX] for f in filas):
            print(f"ERROR: --fila debe ser una o varias de {', '.join(str(r + 1) for r in robot.NODOS_IDX)} (ej. --fila 1)")
            return 1

    try:
        if brazo is None:
            brazo = robot.Brazo(args.puerto)
        mn, mx, ini = brazo.leer_limites()
    except (RuntimeError, TimeoutError) as e:
        print("ERROR:", e)
        return 1

    datos = {"limites": {"mn": mn, "mx": mx, "reposo": ini}, "pinza": {}, "poses": {}}
    if os.path.exists(ARCHIVO):
        if args.rehacer:
            os.replace(ARCHIVO, ARCHIVO + ".bak")
            print(f"--rehacer: se empieza de cero (copia de lo anterior en {os.path.basename(ARCHIVO)}.bak)")
        else:
            with open(ARCHIVO, encoding="utf-8") as f:
                previo = json.load(f)
            if previo.get("limites") == datos["limites"]:
                datos = previo
            else:
                print("AVISO: los limites del firmware cambiaron desde la ultima vez (recalibraste).")
                print("Lo ensenado antes ya no vale: se empieza de cero (copia en poses_ensenadas.json.bak).")
                os.replace(ARCHIVO, ARCHIVO + ".bak")

    orden = orden_casillas()
    if args.pinza:
        nodos = []
    elif solo:
        nodos = [n for n in orden if n in solo]
    else:
        nodos = [n for n in orden if not hecha(datos, n)]
    if filas:
        nodos = [n for n in nodos if int(n[1]) in filas]
    if not nodos and not args.pinza:
        print("No queda nada por ensenar con esas opciones. Usa --rehacer (todo) o --solo C1,H3 (casillas sueltas).")
        print("Mira lo que ya hay con:  python robot.py tabla")
        return 0

    hechas = [n for n in orden if hecha(datos, n)]
    print(f"\nCasillas ya ensenadas: {len(hechas)} de 16" + (f" ({' '.join(hechas)})" if hechas else ""))
    print("Voy a reensenar la pinza." if args.pinza else "Voy a ensenar: " + " > ".join(nodos))
    if args.puerto and not robot.confirmar_encendido():
        return 0
    robot.POSES = None          # al ensenar no se usan las poses viejas (activar() las compararia)
    try:
        brazo.activar()
    except (RuntimeError, TimeoutError) as e:
        print("ERROR:", e)
        return 1

    print("\nORIENTACION" + __doc__.split("ORIENTACION")[1])
    try:
        with (teclado or Teclado()) as tec:
            ses = Sesion(brazo, datos, mn, mx, ini, tec)
            ensenar_pinza(ses, forzar=args.pinza)
            if args.pinza:
                pz = datos["pinza"]
                print(f"\nListo. Pinza: abierta={pz['abierta']}, toca la pieza en {pz['agarre']}, "
                      f"se cerrara a {ses.calcular_apriete()} (apriete +{robot.APRIETE_PINZA}).")
                return 0
            ensenar(ses, nodos)
    except Salir:
        print("\nSaliendo. El brazo queda donde esta y lo guardado se conserva.")
        return 0
    except ErrorRobot as e:
        print(f"\nERROR DEL ROBOT: {e}")
        print("El brazo puede haber quedado en una posicion inesperada. Lo guardado se conserva.")
        return 1
    hechas = [n for n in orden if hecha(datos, n)]
    print("\n\nListo. Casillas ensenadas ahora: " + " ".join(hechas))
    print("Mira que casillas ya puede usar:  python robot.py tabla")
    if len(hechas) >= 2:
        print(f"Prueba el movimiento:  python robot.py mover {hechas[0]} {hechas[-1]} --puerto COM6")
    return 0


if __name__ == "__main__":
    sys.exit(main())