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
  PASO 1  llevas la pinza encima de la pieza (altura segura)                  G -> la pinza se ABRE sola  
  PASO 2  bajas hasta que la pinza rodee la pieza a media altura              G -> la pinza se CIERRA sola,  
                                                                                   sube con la pieza y espera  
SIGUIENTES CASILLAS (C1, F1, H1, ...), el robot lleva la pieza agarrada:  
  PASO 1  la llevas encima de la casilla (altura segura)                      G  
  PASO 2  bajas hasta apoyarla en el centro                                   G -> la SUELTA, sube, baja,  
                                                                                   la agarra y sube (comprobacion)  
  Despues:  G = seguir | B = repetir esa casilla | T = terminar aqui (deja la pieza y vuelve a reposo)  
   
Se guarda tras cada G: puedes parar cuando quieras (por ejemplo, tras la fila 1) y seguir otro dia.  
Despues:   python robot.py tabla                       (que casillas ya puede)  
           python robot.py mover A1 H1 --puerto COM6   (reproduce: agarra en A1, suelta en H1)  
           python robot.py consola --puerto COM6       (escribes "A1 H1" y se mueve)  
   
Uso (en una terminal, no en IDLE):  
    python teach.py --puerto COM6                # sigue donde lo dejaste (orden: A1 C1 F1 H1 H3 F3 ...)  
    python teach.py --puerto COM6 --fila 1       # solo la primera fila (A1 C1 F1 H1) y termina  
    python teach.py --puerto COM6 --rehacer      # empieza de cero (guarda copia de lo anterior en .bak)  
    python teach.py --puerto COM6 --solo A1,C1   # solo esas casillas (ej. para una prueba rapida A1 -> C1)  
    python teach.py --puerto COM6 --pinza        # reensena SOLO los dos angulos de la pinza (no borra casillas)  
    python teach.py                              # simulacion, para ver como funciona  
   
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
        self.agf = None                  # angulo con que se SUJETA la pieza (ensenado + apriete)  
   
    def calcular_apriete(self):  
        pz = self.datos["pinza"]  
        self.agf = robot.apretar(pz["abierta"], pz["agarre"])  
        return self.agf  
   
    # --- movimiento ---  
    def ir(self, pose=None):  
        if pose is not None:  
            self.pose = list(pose)  
        try:  
            self.brazo.ir_pose(self.pose)  
        except (RuntimeError, TimeoutError, robot.Abortado) as e:  
            raise ErrorRobot(str(e)) from None  
   
    def pinza(self, grados):  
        if self.pose[5] == grados:  
            return  
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
   
    def esperar(self, texto, validas=("g",)):  
        """Imprime un mensaje y espera una de las teclas validas."""  
        print("\n" + texto)  
        while True:  
            k = self.tec.leer()  
            if k in validas:  
                return k  
            if k in ("0", "\x1b"):  
                raise Salir()  
   
    def guardar_pose(self, nombre, nivel):  
        self.datos["poses"].setdefault(nombre, {})[nivel] = list(self.pose)  
        guardar(self.datos)  
        print(f"  guardado: {nombre} / {nivel}")  
   
# ---------------------------------------------------------------------  
# Preparacion de la pinza (solo la primera vez)  
# ---------------------------------------------------------------------  
def ensenar_pinza(ses, forzar=False):  
    pz = ses.datos["pinza"]  
    if forzar:  
        pz.pop("abierta", None)  
        pz.pop("agarre", None)  
    if "abierta" not in pz:  
        while ses.jog("PINZA 1 de 2 - ABIERTA",  
                      "  Abre la pinza (ESPACIO o Z/C) lo justo para rodear una pieza con holgura.   G = guardar") != "g":  
            pass  
        pz["abierta"] = ses.pose[5]  
        guardar(ses.datos)  
        print(f"  guardado: pinza abierta = {pz['abierta']}")  
    if "agarre" not in pz:  
        while ses.jog("PINZA 2 de 2 - AGARRE",  
                      "  Pon una pieza entre los dedos con la mano y cierra (Z / C) justo hasta que la TOQUE\n"  
                      "  y quede sujeta (el robot apretara solo unos grados mas).   G = guardar") != "g":  
            pass  
        pz["agarre"] = ses.pose[5]  
        guardar(ses.datos)  
        print(f"  guardado: pinza agarre = {pz['agarre']}")  
        print("  La pinza se abre sola. Retira la pieza.")  
        ses.pinza(pz["abierta"])  
   
# ---------------------------------------------------------------------  
# Las dos clases de casilla  
# ---------------------------------------------------------------------  
def casilla_inicial(ses, n):  
    """La pieza esta puesta (por ti) en el centro de n y el robot todavia NO la lleva."""  
    pz = ses.datos["pinza"]  
    ab, ag = pz["abierta"], ses.calcular_apriete()  
    ses.pinza(ag)                                      # pinza cerrada para posicionar  
    j = 0  
    while j < 2:  
        if j == 0:  
            r = ses.jog("PASO 1 - ALTURA SEGURA",  
                        f"  Pon la pinza (cerrada) encima de la pieza en {n}, bien centrada y a una altura que\n"  
                        f"  pase por encima de cualquier otra pieza.   G = guardar (el robot abrira la pinza)")  
        else:  
            r = ses.jog("PASO 2 - ALTURA DE AGARRE",  
                        "  Baja hasta que la pinza abierta rodee la pieza a media altura.\n"  
                        "  G = guardar (el robot cerrara la pinza y subira con la pieza)")  
        if r == "b":  
            if j == 0:  
                print("  (ya estas en el primer paso de esta casilla)")  
            j = max(0, j - 1)  
            continue  
        ses.guardar_pose(n, "segura" if j == 0 else "agarre")  
        if j == 0:  
            print("  El robot abre la pinza...")  
            ses.pinza(ab)  
        j += 1  
    print("  El robot cierra la pinza y sube con la pieza...")  
    ses.pinza(ag)  
    ses.subir(n, ag)  
   
def casilla_llevando(ses, n):  
    """El robot lleva la pieza agarrada. Devuelve 'ok', 'repetir' o 'terminar'."""  
    pz = ses.datos["pinza"]  
    ab, ag = pz["abierta"], ses.calcular_apriete()  
    j = 0  
    while j < 2:  
        if j == 0:  
            r = ses.jog("PASO 1 - ALTURA SEGURA",  
                        f"  El robot LLEVA la pieza (pinza cerrada). Llevala encima de {n}, centrada y a la\n"  
                        f"  misma altura segura de antes.   G = guardar", bloquear_pinza=True)  
        else:  
            r = ses.jog("PASO 2 - ALTURA DE APOYO",  
                        f"  Baja hasta que la pieza quede apoyada en el centro de {n}.\n"  
                        f"  G = guardar (el robot suelta la pieza, sube, baja, la agarra y sube: comprobacion)",  
                        bloquear_pinza=True)  
        if r == "b":  
            if j == 0:  
                print("  (ya estas en el primer paso de esta casilla)")  
            j = max(0, j - 1)  
            continue  
        ses.guardar_pose(n, "segura" if j == 0 else "agarre")  
        j += 1  
    print("  El robot comprueba: suelta la pieza, sube, baja, la agarra y sube...")  
    ses.pinza(ab)  
    ses.subir(n, ab)  
    ses.bajar(n, ab)  
    ses.pinza(ag)  
    ses.subir(n, ag)  
    r = ses.esperar(f"COMPROBACION de {n}: agarro bien la pieza?\n"  
                    f"  G = si, seguir | B = no, repetir {n} | T = terminar aqui (deja la pieza y vuelve a reposo)",  
                    validas=("g", "b", "t"))  
    if r == "g":  
        return "ok"  
    if r == "t":  
        return "terminar"  
    print(f"  El robot suelta la pieza. Ponla a mano en el centro de {n} y repite esta casilla.")  
    ses.pinza(ab)  
    ses.esperar(f"Cuando la pieza este en el centro de {n}, pulsa G.")  
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
            if i == 0:  
                ses.esperar(f"Pon UNA pieza en el centro de {n} y pulsa G para empezar.")  
            casilla_inicial(ses, n)  
            r = "ok"  
        else:  
            r = casilla_llevando(ses, n)  
        if r == "repetir":  
            inicio_manual = True  
            continue  
        if r == "terminar":  
            break  
        inicio_manual = False  
        i += 1  
    n = nodos[min(i, len(nodos) - 1)]  
    pz = ses.datos["pinza"]  
    print(f"\nFin. El robot deja la pieza en {n} y vuelve a reposo...")  
    ses.bajar(n, ses.calcular_apriete())  
    ses.pinza(pz["abierta"])  
    ses.subir(n, pz["abierta"])  
    ses.ir(list(ses.ini))  
   
# ---------------------------------------------------------------------  
def main(argv=None, teclado=None, brazo=None):  
    ap = argparse.ArgumentParser()  
    ap.add_argument("--puerto", help="ej. COM6. Sin puerto = simulacion")  
    ap.add_argument("--rehacer", action="store_true", help="empieza de cero (copia de lo anterior en .bak)")  
    ap.add_argument("--solo", help="repite solo estas casillas, ej. C1,H3 (no borra las demas)")  
    ap.add_argument("--fila", help="solo las casillas de esta(s) fila(s), ej. 1  o  1,3")  
    ap.add_argument("--pinza", action="store_true", help="reensena SOLO los angulos de la pinza (no borra casillas)")  
    args = ap.parse_args(argv)  
   
    solo = [x.strip().upper() for x in args.solo.split(",")] if args.solo else None  
    if solo:  
        malas = [n for n in solo if n not in robot.NODOS]  
        if malas:  
            print(f"ERROR: {', '.join(malas)} no se ensena. Las casillas ensenadas son: {' '.join(orden_casillas())}")  
            return 1  
    filas = None  
    if args.fila:  
        try:  
            filas = [int(x) for x in args.fila.split(",")]  
        except ValueError:  
            filas = []  
        if not filas or any(f not in [r + 1 for r in robot.NODOS_IDX] for f in filas):  
            print(f"ERROR: --fila debe ser una o varias de {', '.join(str(r + 1) for r in robot.NODOS_IDX)} (ej. --fila 1)")  
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
    if args.pinza:  
        nodos = []  
    elif solo:  
        nodos = [n for n in orden if n in solo]  
    else:  
        nodos = [n for n in orden if not hecha(datos, n)]  
    if filas:  
        nodos = [n for n in nodos if int(n[1]) in filas]  
    if not nodos and not args.pinza:  
        print("No queda nada por ensenar con esas opciones. Usa --rehacer (todo) o --solo C1,H3 (casillas sueltas).")  
        print("Mira lo que ya hay con:  python robot.py tabla")  
        return 0  
   
    hechas = [n for n in orden if hecha(datos, n)]  
    print(f"\nCasillas ya ensenadas: {len(hechas)} de 16" + (f" ({' '.join(hechas)})" if hechas else ""))  
    print("Voy a reensenar la pinza." if args.pinza else "Voy a ensenar: " + " > ".join(nodos))  
    if args.puerto and not robot.confirmar_encendido():  
        return 0  
    robot.POSES = None          # al ensenar no se usan las poses viejas (activar() las compararia)  
    try:  
        brazo.activar()  
    except (RuntimeError, TimeoutError) as e:  
        print("ERROR:", e)  
        return 1  
   
    print("\nORIENTACION" + __doc__.split("ORIENTACION")[1])  
    try:  
        with (teclado or Teclado()) as tec:  
            ses = Sesion(brazo, datos, mn, mx, ini, tec)  
            ensenar_pinza(ses, forzar=args.pinza)  
            if args.pinza:  
                pz = datos["pinza"]  
                print(f"\nListo. Pinza: abierta={pz['abierta']}, toca la pieza en {pz['agarre']}, "  
                      f"se cerrara a {ses.calcular_apriete()} (apriete +{robot.APRIETE_PINZA}).")  
                return 0  
            ensenar(ses, nodos)  
    except Salir:  
        print("\nSaliendo. El brazo queda donde esta y lo guardado se conserva.")  
        return 0  
    except ErrorRobot as e:  
        print(f"\nERROR DEL ROBOT: {e}")  
        print("El brazo puede haber quedado en una posicion inesperada. Lo guardado se conserva.")  
        return 1  
    hechas = [n for n in orden if hecha(datos, n)]  
    print("\n\nListo. Casillas ensenadas ahora: " + " ".join(hechas))  
    print("Mira que casillas ya puede usar:  python robot.py tabla")  
    if len(hechas) >= 2:  
        print(f"Prueba el movimiento:  python robot.py mover {hechas[0]} {hechas[-1]} --puerto COM6")  
    return 0  
   
if __name__ == "__main__":  
    sys.exit(main())  
   
   
"""  
retirada.py - Ensenarle al robot una pose de RETIRADA (el brazo fuera del encuadre de la camara)  
================================================================================================  
El reposo de fabrica deja el brazo encima del tablero y la camara lo ve. La retirada es otra pose,  
mas atras, a la que el robot vuelve despues de cada movimiento y al arrancar.  
   
El brazo arranca siempre en el reposo de siempre (apoyado, no se cae). Aqui lo mueves con el teclado  
hacia atras, hasta que NINGUNA parte quede dentro del tablero que ve la camara, y pulsas G.  
   
Uso (en una terminal):  
    python retirada.py --puerto COM6          # robot real  
    python retirada.py                        # simulacion  
   
Teclas: A/D base | W/S hombro | E/Q codo | R/F gancho | 1/2/3 tamano del paso | G guardar | 0 salir  
(Antes tienes que haber ensenado casillas con teach.py: la retirada se guarda en el mismo archivo.)  
"""  
import argparse  
import json  
import os  
import sys  
   
import robot  
import teach  
   
def main(argv=None, teclado=None, brazo=None):  
    ap = argparse.ArgumentParser()  
    ap.add_argument("--puerto", help="ej. COM6. Sin puerto = simulacion")  
    args = ap.parse_args(argv)  
   
    if not os.path.exists(teach.ARCHIVO):  
        print("ERROR: todavia no hay casillas ensenadas. Ejecuta antes teach.py")  
        return 1  
    try:  
        if brazo is None:  
            brazo = robot.Brazo(args.puerto)  
        mn, mx, ini = brazo.leer_limites()  
    except (RuntimeError, TimeoutError) as e:  
        print("ERROR:", e)  
        return 1  
    with open(teach.ARCHIVO, encoding="utf-8") as f:  
        datos = json.load(f)  
    if datos.get("limites") != {"mn": mn, "mx": mx, "reposo": ini}:  
        print("ERROR: los limites del firmware cambiaron desde que ensenaste las casillas. Usa teach.py --rehacer")  
        return 1  
   
    if args.puerto and not robot.confirmar_encendido():  
        return 0  
    robot.POSES = None  
    try:  
        brazo.activar()  
    except (RuntimeError, TimeoutError) as e:  
        print("ERROR:", e)  
        return 1  
   
    previa = datos.get("retirada")  
    try:  
        with (teclado or teach.Teclado()) as tec:  
            ses = teach.Sesion(brazo, datos, mn, mx, ini, tec)  
            if previa:  
                print("Ya habia una retirada guardada: el brazo va hacia ella para que la ajustes.")  
                ses.ir(previa)  
            while ses.jog("POSE DE RETIRADA",  
                          "  Mueve el brazo HACIA ATRAS hasta que ninguna parte quede dentro del tablero que ve\n"  
                          "  la camara, sin que choque con nada.   G = guardar") != "g":  
                pass  
            datos["retirada"] = list(ses.pose)  
            teach.guardar(datos)  
    except teach.Salir:  
        print("\nSaliendo sin guardar cambios.")  
        return 0  
    except teach.ErrorRobot as e:  
        print(f"\nERROR DEL ROBOT: {e}")  
        return 1  
    print(f"\nRetirada guardada: {datos['retirada']}")  
    print("Se usa sola: despues de cada movimiento el brazo se retira ahi.")  
    print("Antes de APAGAR la fuente, usa el boton REPOSO SEGURO (el brazo apoyado no se cae).")  
    return 0  
   
if __name__ == "__main__":  
    sys.exit(main())  
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
    python robot.py info                     # que casillas y que angulos de pinza usa de verdad  
    python robot.py tabla                    # que casillas alcanza el brazo  
    python robot.py angulos E3               # angulos para una casilla  
    python robot.py mover E3 G5              # secuencia completa E3 -> G5  
    python robot.py ir E3 --bajar --puerto COM5   # solo ir a una casilla (para afinar)  
    python robot.py reposo --puerto COM5  
    python robot.py consola --puerto COM5    # escribes "A1 H1" y el robot mueve la pieza  
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
# Grados EXTRA que se cierra la pinza mas alla del angulo en que TOCO la pieza al ensenarla.  
# Sin esto la sujeta sin fuerza y se le cae. Si resbala: subelo (10, 12...). Si el servo de la  
# pinza se calienta o zumba demasiado: bajalo (4, 5...).  
APRIETE_PINZA = 8  
   
# Valores por defecto (en modo poses ensenadas se reemplazan por los del archivo,  
# que a su vez salen del firmware: asi la tabla vive en UN solo sitio, el .ino).  
PINZA_ABIERTA = 90  
PINZA_AGARRE = 40  
MN = (3, 60, 3, 3, 3, 10)  
MX = (170, 140, 177, 178, 175, 110)  
REPOSO = (50, 90, 120, 178, 175, 25)  
RETIRADA = None                # pose para que el brazo NO tape la camara (se ensena con retirada.py)  
NOMBRES = ("Base", "Hombro", "Codo", "Muneca", "Gancho", "Pinza")  
   
def apretar(abierta, agarre):  
    """Angulo con el que se SUJETA la pieza: el ensenado + APRIETE_PINZA hacia el lado de cerrar,  
    sin pasar del limite del firmware (MN/MX de la pinza)."""  
    sentido = 1 if agarre > abierta else -1          # cerrar = alejarse del angulo de 'abierta'  
    return max(MN[5], min(MX[5], agarre + sentido * APRIETE_PINZA))  
   
def pinza_apretada():  
    return apretar(PINZA_ABIERTA, PINZA_AGARRE)  
   
def info_pinza():  
    return (f"Pinza: abierta={PINZA_ABIERTA}, toca la pieza en {PINZA_AGARRE}, "  
            f"se cierra a {pinza_apretada()} (apriete +{APRIETE_PINZA}); limites del firmware {MN[5]}-{MX[5]}")  
   
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
    """Carga poses_ensenadas.json y activa el modo 1. Sirve aunque solo haya UNA parte del  
    tablero ensenada: se usan las casillas completas (segura + agarre). Lanza ValueError si no hay ninguna."""  
    global POSES, MN, MX, REPOSO, MUNECA_ROLL, PINZA_ABIERTA, PINZA_AGARRE, _LIM_ARCHIVO, RETIRADA  
    with open(ruta, encoding="utf-8") as f:  
        d = json.load(f)  
    completas = {n: v for n, v in d.get("poses", {}).items() if "segura" in v and "agarre" in v}  
    if not completas:  
        raise ValueError("todavia no hay ninguna casilla ensenada completa (segura y agarre)")  
    if not all(k in d.get("pinza", {}) for k in ("abierta", "agarre")):  
        raise ValueError("falta ensenar la pinza (abierta / agarre)")  
    lim = d["limites"]  
    MN, MX, REPOSO = tuple(lim["mn"]), tuple(lim["mx"]), tuple(lim["reposo"])  
    MUNECA_ROLL = REPOSO[3]  
    PINZA_ABIERTA, PINZA_AGARRE = int(d["pinza"]["abierta"]), int(d["pinza"]["agarre"])  
    r = d.get("retirada")  
    RETIRADA = tuple(r) if r and len(r) == 6 and all(MN[i] <= r[i] <= MX[i] for i in range(6)) else None  
    _LIM_ARCHIVO = [list(MN), list(MX), list(REPOSO)]  
    POSES = completas  
    return True  
   
def _lagrange(nodos, i, x):  
    p = 1.0  
    for j, nj in enumerate(nodos):  
        if j != i:  
            p *= (x - nj) / (nodos[i] - nj)  
    return p  
   
def _tramos_filas():  
    """Grupos de filas COMPLETAS (las 4 columnas ensenadas) y CONSECUTIVAS entre las filas de NODOS_IDX."""  
    tramos, actual = [], []  
    for r in NODOS_IDX:  
        if all(f"{chr(65 + c)}{r + 1}" in POSES for c in NODOS_IDX):  
            actual.append(r)  
        elif actual:  
            tramos.append(actual)  
            actual = []  
    if actual:  
        tramos.append(actual)  
    return tramos  
   
def disponible(casilla):  
    """'ensenada' (pose exacta), 'calculada' (interpolada entre filas completas) o None."""  
    if POSES is None:  
        return None  
    if casilla in POSES:  
        return "ensenada"  
    _, fila = nombre_a_indices(casilla)  
    if any(t[0] <= fila <= t[-1] for t in _tramos_filas()):  
        return "calculada"  
    return None  
   
def _mezcla(nodo, nivel):  
    return [(1 - nivel) * a + nivel * b for a, b in zip(nodo["segura"], nodo["agarre"])]  
   
def _pose_ensenada(casilla, nivel, pinza):  
    """nivel 0 = altura segura, 1 = altura de agarre (se mezclan linealmente)."""  
    col, fila = nombre_a_indices(casilla)  
    if casilla in POSES:                                   # casilla ensenada: pose exacta  
        p = _mezcla(POSES[casilla], nivel)  
    else:  
        tramo = next((t for t in _tramos_filas() if t[0] <= fila <= t[-1]), None)  
        if tramo is None:  
            raise FueraDeAlcance(f"{casilla}: todavia no ensenada (graba esa zona con teach.py)")  
        p = [0.0] * 6  
        for k, f in enumerate(tramo):  
            wf = _lagrange(tramo, k, fila)  
            for i, c in enumerate(NODOS_IDX):  
                w = wf * _lagrange(NODOS_IDX, i, col)  
                m = _mezcla(POSES[f"{chr(65 + c)}{f + 1}"], nivel)  
                for j in range(6):  
                    p[j] += w * m[j]  
    p[5] = pinza  
    for j in range(6):  
        if not (MN[j] <= round(p[j]) <= MX[j]):  
            raise FueraDeAlcance(f"{casilla}: {NOMBRES[j]} pediria {p[j]:.0f} (rango {MN[j]}-{MX[j]})")  
    return [int(round(v)) for v in p]  
   
def casillas_disponibles():  
    return [f"{c}{f}" for f in range(1, 9) for c in "ABCDEFGH" if disponible(f"{c}{f}")]  
   
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
    if POSES is not None:  
        return f"poses ensenadas ({len(casillas_disponibles())} de 64 casillas disponibles)"  
    return "geometria"  
   
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
   
def pose_retirada():  
    """Pose con la que el brazo se aparta del tablero (la pinza queda abierta). Si no se ensenio, el reposo."""  
    if RETIRADA is None:  
        return list(REPOSO)  
    p = list(RETIRADA)  
    p[5] = PINZA_ABIERTA  
    return p  
   
def planificar(origen, destino):  
    """Calcula TODAS las poses antes de mover nada. Devuelve [(descripcion, pose), ...].  
    Lanza FueraDeAlcance (indicando la casilla) si alguna pose no es posible."""  
    A, C = PINZA_ABIERTA, pinza_apretada()  
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
    pasos.append(("Retirando el brazo", pose_retirada()))  
    return pasos  
   
def verificar_modo_real():  
    """Impide mover el robot REAL sin poses ensenadas ni geometria confirmada."""  
    if POSES is None and not GEOMETRIA_CONFIRMADA:  
        extra = f" ({AVISO_POSES})" if AVISO_POSES else ""  
        raise RuntimeError("No hay casillas ensenadas utilizables" + extra + ". Ejecuta teach.py "  
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
   
    def ir_a_casilla(self, casilla, bajar=False, progreso=None):  
        """Solo para afinar: va sobre una casilla (y opcionalmente baja a la altura de agarre)."""  
        poses = [("Sobre " + casilla, pose_en(casilla, 0, PINZA_ABIERTA))]  
        if bajar:  
            poses += [("Bajando", pose_en(casilla, v, PINZA_ABIERTA)) for v in _niveles_bajada()]  
        if not self.simulado:  
            verificar_modo_real()  
        self._abortar = False  
        if not self.activo:  
            self.activar()  
        for texto, pose in poses:  
            if progreso:  
                progreso(texto)  
            self.ir_pose(pose)  
   
    def retirar(self):  
        """Lleva el brazo a la pose de retirada (fuera del encuadre de la camara)."""  
        if not self.activo:  
            self.activar()  
        self.ir_pose(pose_retirada())  
   
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
    print(f"Modo: {modo()}")  
    print("##  = casilla ENSENADA (pose exacta)   OK = casilla CALCULADA entre filas ensenadas   -- = todavia no\n")  
    print("    " + "".join(f"{c:^5}" for c in "ABCDEFGH"))  
    sin = []  
    for fila in range(8, 0, -1):  
        celdas = ""  
        for col in "ABCDEFGH":  
            n = f"{col}{fila}"  
            ok, motivo = alcanzable(n)  
            tipo = disponible(n) if POSES is not None else ("calculada" if ok else None)  
            marca = "##" if tipo == "ensenada" else ("OK" if ok else "--")  
            celdas += f"{marca:^5}"  
            if not ok:  
                sin.append((n, motivo))  
        print(f"{fila:>3} {celdas}")  
    print(f"\nUtilizables: {64 - len(sin)}/64")  
    for n, m in sin[:6]:  
        print(f"  {n}: {m}")  
    if len(sin) > 6:  
        print(f"  ... y {len(sin) - 6} mas")  
   
def cmd_info():  
    print(f"Modo: {modo()}")  
    print(info_pinza())  
    print("Retirada:", list(RETIRADA) if RETIRADA else "no ensenada (usa retirada.py): se vuelve al reposo")  
    if POSES is not None:  
        print("Casillas ensenadas:", " ".join(sorted(POSES)))  
        print("Limites del firmware (mn):", list(MN))  
        print("Limites del firmware (mx):", list(MX))  
        print("Reposo:", list(REPOSO))  
    else:  
        print("Aun no hay casillas ensenadas utilizables (usa teach.py).")  
   
def cmd_angulos(casilla):  
    print(f"{casilla.upper()}  (modo: {modo()})")  
    print(f"{'':<14}" + "".join(f"{n:>8}" for n in NOMBRES))  
    for texto, nivel, p in (("Sobre (segura)", 0, PINZA_ABIERTA), ("Agarre", 1, pinza_apretada())):  
        pose = pose_en(casilla, nivel, p)  
        print(f"{texto:<14}" + "".join(f"{a:>8}" for a in pose))  
   
def cmd_consola(brazo, piezas):  
    """Escribes 'A1 H1' y el robot lleva la pieza. Lleva la cuenta de que casillas tienen pieza  
    (a mano, hasta que se enlace con la camara): no deja mover desde una casilla vacia ni hacia una ocupada."""  
    ocupadas = set(piezas)  
    piezas_anotadas = bool(ocupadas)  
    print(f"Modo: {modo()}")  
    print(info_pinza())  
    print("Escribe  ORIGEN DESTINO  (ej. A1 H1).  Otros comandos:")  
    print("  pon A1 / quita A1 = anotar a mano una pieza | piezas = ver | tabla | reposo | q = salir")  
    print("  (Ctrl+C durante un movimiento = PARADA)")  
    if not ocupadas:  
        print("Sin piezas anotadas: la primera orden asume que hay una pieza en el origen.")  
    while True:  
        try:  
            txt = input("\n> ").strip().upper().replace(",", " ").replace("->", " ")  
        except (EOFError, KeyboardInterrupt):  
            break  
        partes = txt.split()  
        if not partes:  
            continue  
        try:  
            if partes[0] in ("Q", "SALIR", "EXIT"):  
                break  
            elif partes[0] == "TABLA":  
                cmd_tabla()  
            elif partes[0] == "PIEZAS":  
                print("Piezas anotadas:", " ".join(sorted(ocupadas)) or "ninguna")  
            elif partes[0] == "REPOSO":  
                brazo.reposo()  
                print("En reposo.")  
            elif partes[0] in ("PON", "QUITA") and len(partes) == 2:  
                nombre_a_indices(partes[1])  
                (ocupadas.add if partes[0] == "PON" else ocupadas.discard)(partes[1])  
                print("Piezas anotadas:", " ".join(sorted(ocupadas)) or "ninguna")  
            elif len(partes) == 2:  
                o, d = partes  
                nombre_a_indices(o)  
                nombre_a_indices(d)  
                if not ocupadas and not piezas_anotadas:  
                    ocupadas.add(o)                       # primera orden sin anotar nada: se asume pieza en el origen  
                    piezas_anotadas = True  
                    print(f"(No habias anotado piezas: asumo que hay una en {o}.)")  
                if o == d:  
                    print("Origen y destino son la misma casilla.")  
                elif o not in ocupadas:  
                    print(f"No hay pieza en {o} (si la hay, anotala con:  pon {o})")  
                elif d in ocupadas:  
                    print(f"{d} esta OCUPADA: no se puede mover ahi. Elige otra casilla de destino.")  
                else:  
                    planificar(o, d)                      # avisa antes de mover si falta alcance  
                    brazo.mover_pieza(o, d, progreso=lambda t: print("  -", t))  
                    ocupadas.discard(o)  
                    ocupadas.add(d)  
                    print(f"Listo: {o} -> {d}.  Piezas anotadas:", " ".join(sorted(ocupadas)))  
            else:  
                print("No entendi. Ejemplo:  A1 H1")  
        except KeyboardInterrupt:  
            brazo.parar()  
            print("\nPARADA. El brazo se detuvo donde estaba (revisa la pieza).")  
        except (ValueError, FueraDeAlcance, RuntimeError, TimeoutError, Abortado) as e:  
            print("ERROR:", e)  
   
def main():  
    ap = argparse.ArgumentParser(description="Cinematica del brazo de ajedrez")  
    ap.add_argument("accion", choices=["tabla", "info", "angulos", "ir", "mover", "reposo", "consola"])  
    ap.add_argument("casillas", nargs="*")  
    ap.add_argument("--puerto", help="ej. COM5. Sin puerto = simulacion")  
    ap.add_argument("--bajar", action="store_true", help="con 'ir': baja hasta la altura de agarre")  
    ap.add_argument("--piezas", default="", help="con 'consola': casillas con pieza al empezar, ej. A1,B1")  
    a = ap.parse_args()  
   
    try:  
        if a.accion == "tabla":  
            return cmd_tabla()  
        if a.accion == "info":  
            return cmd_info()  
        if a.accion == "angulos":  
            return cmd_angulos(a.casillas[0])  
        print(f"Modo: {modo()}")  
        print(info_pinza())  
        brazo = Brazo(a.puerto)  
        if a.puerto and not confirmar_encendido():  
            return  
        if a.accion == "consola":  
            return cmd_consola(brazo, [x.strip().upper() for x in a.piezas.split(",") if x.strip()])  
        if a.accion == "reposo":  
            brazo.reposo()  
        elif a.accion == "ir":  
            brazo.ir_a_casilla(a.casillas[0], a.bajar, progreso=lambda t: print(" -", t))  
        else:  
            brazo.mover_pieza(a.casillas[0], a.casillas[1], progreso=lambda t: print(" -", t))  
        print("Listo.")  
    except (IndexError, ValueError, FueraDeAlcance, RuntimeError, TimeoutError) as e:  
        print("ERROR:", e)  
        sys.exit(1)  
   
if __name__ == "__main__":  
    main()  
   
{  
 "limites": {  
  "mn": [  
   3,  
   60,  
   3,  
   3,  
   3,  
   10  
  ],  
  "mx": [  
   170,  
   140,  
   177,  
   178,  
   175,  
   110  
  ],  
  "reposo": [  
   50,  
   90,  
   120,  
   178,  
   175,  
   25  
  ]  
 },  
 "pinza": {  
  "abierta": 64,  
  "agarre": 40  
 },  
 "poses": {  
  "A1": {  
   "segura": [  
    119,  
    72,  
    45,  
    178,  
    145,  
    32  
   ],  
   "agarre": [  
    119,  
    87,  
    45,  
    178,  
    133,  
    64  
   ]  
  },  
  "C1": {  
   "segura": [  
    95,  
    72,  
    45,  
    178,  
    160,  
    32  
   ],  
   "agarre": [  
    95,  
    93,  
    45,  
    178,  
    151,  
    64  
   ]  
  },  
  "F1": {  
   "segura": [  
    38,  
    63,  
    30,  
    178,  
    142,  
    64  
   ],  
   "agarre": [  
    38,  
    81,  
    30,  
    178,  
    133,  
    64  
   ]  
  },  
  "H1": {  
   "segura": [  
    11,  
    90,  
    72,  
    178,  
    160,  
    32  
   ],  
   "agarre": [  
    11,  
    105,  
    72,  
    178,  
    157,  
    64  
   ]  
  },  
  "H3": {  
   "segura": [  
    29,  
    111,  
    108,  
    178,  
    172,  
    40  
   ],  
   "agarre": [  
    29,  
    123,  
    108,  
    178,  
    166,  
    64  
   ]  
  },  
  "F3": {  
   "segura": [  
    47,  
    114,  
    96,  
    178,  
    175,  
    32  
   ],  
   "agarre": [  
    47,  
    120,  
    96,  
    178,  
    172,  
    32  
   ]  
  },  
  "C3": {  
   "segura": [  
    71,  
    114,  
    90,  
    178,  
    172,  
    32  
   ],  
   "agarre": [  
    71,  
    117,  
    90,  
    178,  
    169,  
    32  
   ]  
  },  
  "A3": {  
   "segura": [  
    104,  
    114,  
    99,  
    178,  
    166,  
    32  
   ],  
   "agarre": [  
    104,  
    120,  
    99,  
    178,  
    166,  
    32  
   ]  
  },  
  "A6": {  
   "segura": [  
    89,  
    117,  
    108,  
    178,  
    139,  
    32  
   ],  
   "agarre": [  
    89,  
    126,  
    108,  
    178,  
    130,  
    32  
   ]  
  },  
  "C6": {  
   "segura": [  
    74,  
    117,  
    108,  
    178,  
    145,  
    32  
   ],  
   "agarre": [  
    74,  
    123,  
    108,  
    178,  
    142,  
    32  
   ]  
  },  
  "F6": {  
   "segura": [  
    53,  
    117,  
    108,  
    178,  
    142,  
    32  
   ],  
   "agarre": [  
    53,  
    123,  
    108,  
    178,  
    142,  
    32  
   ]  
  },  
  "H6": {  
   "segura": [  
    38,  
    120,  
    111,  
    178,  
    133,  
    32  
   ],  
   "agarre": [  
    38,  
    126,  
    111,  
    178,  
    127,  
    32  
   ]  
  },  
  "H8": {  
   "segura": [  
    44,  
    131,  
    120,  
    178,  
    85,  
    31  
   ],  
   "agarre": [  
    44,  
    140,  
    123,  
    178,  
    79,  
    110  
   ]  
  },  
  "F8": {  
   "segura": [  
    56,  
    126,  
    105,  
    178,  
    88,  
    32  
   ],  
   "agarre": [  
    53,  
    134,  
    105,  
    178,  
    88,  
    32  
   ]  
  },  
  "C8": {  
   "segura": [  
    71,  
    126,  
    105,  
    178,  
    91,  
    32  
   ],  
   "agarre": [  
    71,  
    129,  
    105,  
    178,  
    91,  
    32  
   ]  
  },  
  "A8": {  
   "segura": [  
    83,  
    132,  
    105,  
    178,  
    79,  
    32  
   ],  
   "agarre": [  
    83,  
    135,  
    105,  
    178,  
    79,  
    32  
   ]  
  }  
 },  
 "retirada": [  
  164,  
  60,  
  30,  
  178,  
  157,  
  22  
 ]  
}  
ARDUINO  
/*  
  BRAZO DE AJEDREZ - FIRMWARE CONTROLADO POR PC (robot.py)  
   
  Comandos (texto, terminan en salto de linea, 9600 baudios):  
    A                    Activar servos en la pose de reposo (el brazo debe estar YA en reposo)  
    G b h c m g p        Ir a la pose: base hombro codo muneca gancho pinza (grados)  
    H                    Volver al reposo  
    X                    Parada: congela los servos donde esten  
    P                    Imprime la posicion actual  
    L                    Imprime sus limites y reposo (los lee el PC: la tabla vive SOLO aqui)  
  Respuestas: "OK" al terminar, "ERR ..." si algo falla.  
   
  Los servos llegan JUNTOS al destino y nunca superan su velocidad maxima (tickMs).  
  Los limites mn/mx se aplican aqui tambien: aunque el PC se equivoque, no los excede.  
*/  
#include <Servo.h>  
   
const byte NUM = 6;  
const byte pines[NUM] = {5, 6, 7, 8, 9, 10};  
   
const int mn[NUM]  = {3,   60,  3,   3,   3,   10};  
const int mx[NUM]  = {170, 140, 177, 178, 175, 110};  
const int ini[NUM] = {50,  90,  120, 178, 175, 25};  
   
// ms por grado: velocidad MAXIMA de cada servo (mas alto = mas lento)  
const int tickMs[NUM] = {20, 35, 25, 20, 20, 20};  
   
Servo servos[NUM];  
int pos[NUM];  
int tgt[NUM];  
unsigned long intervalo[NUM];  
unsigned long lastTick[NUM];  
bool activo = false;  
bool enMovimiento = false;  
   
char buf[40];  
byte nbuf = 0;  
   
void activar() {  
  if (activo) { Serial.println(F("OK")); return; }  
  for (byte i = 0; i < NUM; i++) {  
    pos[i] = ini[i];  
    tgt[i] = ini[i];  
    servos[i].write(ini[i]);     // write ANTES de attach: sin salto  
    servos[i].attach(pines[i]);  
    delay(600);                  // uno por uno: evita picos de corriente  
  }  
  activo = true;  
  Serial.println(F("OK"));  
}  
   
void irA(const int* d) {  
  int delta[NUM];  
  unsigned long T = 0;  
  for (byte i = 0; i < NUM; i++) {  
    tgt[i] = constrain(d[i], mn[i], mx[i]);  
    delta[i] = abs(tgt[i] - pos[i]);  
    unsigned long t = (unsigned long)delta[i] * tickMs[i];  
    if (t > T) T = t;  
  }  
  if (T == 0) { Serial.println(F("OK")); return; }  
  unsigned long ahora = millis();  
  for (byte i = 0; i < NUM; i++) {  
    intervalo[i] = delta[i] ? T / delta[i] : 0;   // todos terminan a la vez  
    lastTick[i] = ahora;  
  }  
  enMovimiento = true;  
}  
   
void imprimirLim(char clave, const int* v) {  
  Serial.print(F("LIM "));  
  Serial.print(clave);  
  for (byte i = 0; i < NUM; i++) { Serial.print(' '); Serial.print(v[i]); }  
  Serial.println();  
}  
   
void comando(char* s) {  
  char c = toupper(s[0]);  
  if (c == 'A') {  
    activar();  
  } else if (c == 'G') {  
    if (!activo) { Serial.println(F("ERR no activo")); return; }  
    int v[NUM];  
    int n = sscanf(s + 1, "%d %d %d %d %d %d", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]);  
    if (n != NUM) { Serial.println(F("ERR formato")); return; }  
    irA(v);  
  } else if (c == 'H') {  
    if (!activo) { Serial.println(F("ERR no activo")); return; }  
    irA(ini);  
  } else if (c == 'X') {  
    for (byte i = 0; i < NUM; i++) tgt[i] = pos[i];  
    enMovimiento = false;  
    Serial.println(F("OK"));  
  } else if (c == 'L') {  
    imprimirLim('n', mn);  
    imprimirLim('x', mx);  
    imprimirLim('i', ini);  
    Serial.println(F("OK"));  
  } else if (c == 'P') {  
    Serial.print(F("POS"));  
    for (byte i = 0; i < NUM; i++) { Serial.print(' '); Serial.print(pos[i]); }  
    Serial.println();  
    Serial.println(F("OK"));  
  } else {  
    Serial.println(F("ERR comando"));  
  }  
}  
   
void leerSerial() {  
  while (Serial.available()) {  
    char c = Serial.read();  
    if (c == '\r') continue;  
    if (c == '\n') {  
      buf[nbuf] = 0;  
      if (nbuf > 0) comando(buf);  
      nbuf = 0;  
    } else if (nbuf < sizeof(buf) - 1) {  
      buf[nbuf++] = c;  
    }  
  }  
}  
   
void avanzar() {  
  if (!enMovimiento) return;  
  unsigned long ahora = millis();  
  bool pendiente = false;  
  for (byte i = 0; i < NUM; i++) {  
    if (pos[i] == tgt[i]) continue;  
    if (ahora - lastTick[i] >= intervalo[i]) {  
      lastTick[i] = ahora;  
      pos[i] += (tgt[i] > pos[i]) ? 1 : -1;  
      servos[i].write(pos[i]);  
    }  
    if (pos[i] != tgt[i]) pendiente = true;  
  }  
  if (!pendiente) {  
    enMovimiento = false;  
    Serial.println(F("OK"));  
  }  
}  
   
void setup() {  
  Serial.begin(9600);  
  for (byte i = 0; i < NUM; i++) { pos[i] = ini[i]; tgt[i] = ini[i]; }  
  Serial.println(F("LISTO"));  
}  
   
void loop() {  
  leerSerial();  
  avanzar();  
}  
   
"""  
juego.py - Interfaz de juego: tablero con lo que ve la camara + ORIGEN / DESTINO + boton JUGAR  
==============================================================================================  
Une los dos programas en uno solo (usa vision_tablero.py y robot.py, sin tocarlos):  
   
   camara -> que casillas tienen pieza -> se comprueba la jugada -> el robot la hace -> la camara la verifica  
   
Antes de dejar jugar comprueba, con lo que ve la camara AHORA:  
   1. la casilla de ORIGEN tiene pieza           (si esta vacia: no se puede)  
   2. la casilla de DESTINO esta libre           (si esta ocupada: no se puede, elige otra)  
   3. el brazo llega a esas casillas (estan ensenadas o se calculan)  
   4. el tablero no esta tapado por una mano o el brazo y la lectura es estable  
   5. el robot no esta ocupado con otro movimiento  
   
Uso:  
    python juego.py --listar                       (que numero de camara funciona)  
    python juego.py --camara 1                     (simulacion, sin robot)  
    python juego.py --camara 1 --puerto COM6       (con robot)  
   
Primera vez (ventana de la camara): clic en las 4 esquinas, C, O hasta que A1 quede abajo-izquierda  
(lado del robot), quita las piezas y pulsa E, vuelve a poner las piezas. Se guarda y no hay que repetirlo  
mientras la camara no se mueva (si se mueve: R y recalibrar).  
   
En la ventana del juego: clic en una casilla = ORIGEN, otro clic = DESTINO, boton JUGAR (o tecla J).  
Teclas: J jugar | L limpiar | X PARADA | U releer el tablero | D diagnostico | Q salir  
"""  
import argparse  
import textwrap  
import threading  
import time  
   
import cv2  
import numpy as np  
   
import robot  
import vision_tablero as V  
   
if not hasattr(robot.Brazo, "retirar"):  
    raise SystemExit("Actualiza robot.py: falta la pose de retirada (Brazo.retirar).")  
   
VENTANA = "Ajedrez robot"  
PANEL_W = 360  
ALTO = V.BOARD_PIXELS  
FONDO = (38, 38, 38)  
GRIS = (110, 110, 110)  
GRIS_CLARO = (170, 170, 170)  
   
class Juego(V.App):  
    def __init__(self, brazo):  
        super().__init__(brazo)  
        self.sel_o = None  
        self.sel_d = None  
        x0, x1 = V.BOARD_PIXELS + 20, V.BOARD_PIXELS + PANEL_W - 20  
        mitad = (x0 + x1) // 2  
        self.botones = [  
            {"rect": (x0, 440, x1, 505), "texto": "JUGAR", "color": V.VERDE, "accion": self.jugar, "id": "jugar"},  
            {"rect": (x0, 518, mitad - 8, 558), "texto": "LIMPIAR", "color": GRIS, "accion": self.limpiar, "id": "limpiar"},  
            {"rect": (mitad + 8, 518, x1, 558), "texto": "PARAR", "color": V.ROJO, "accion": self.parar, "id": "parar"},  
            {"rect": (x0, 572, mitad - 8, 612), "texto": "REPOSO SEGURO", "color": (0, 120, 200), "accion": self.reposo_seguro, "id": "reposo"},  
            {"rect": (mitad + 8, 572, x1, 612), "texto": "RETIRAR BRAZO", "color": (150, 100, 0), "accion": self.retirar_brazo, "id": "retirar"},  
        ]  
   
    # ---------------- seleccion ----------------  
    def seleccionar(self, nombre):  
        if self.sel_o is None or self.sel_d is not None:       # empezar una jugada nueva  
            self.sel_o, self.sel_d = nombre, None  
        elif nombre == self.sel_o:                             # clic otra vez en el origen: anula  
            self.sel_o = None  
        else:  
            self.sel_d = nombre  
   
    def ingresar_casilla(self, nombre):                        # tambien las que se escriben con M  
        self.seleccionar(nombre)  
   
    def limpiar(self):  
        self.sel_o = self.sel_d = None  
   
    # ---------------- comprobaciones ----------------  
    def estado_jugada(self):  
        """(ok, texto, color, que_limpiar) segun lo que ve la camara AHORA.  
        que_limpiar si falla: 'nada' (motivo pasajero), 'destino' (elegir otro destino) o 'todo'."""  
        t, o, d = self.t, self.sel_o, self.sel_d  
        if o is None:  
            return False, "Elige la casilla de ORIGEN (clic en el tablero).", V.BLANCO, "nada"  
        if d is None:  
            if t.fondo_rect is not None and not t.ocupada(o):  
                return False, f"En {o} NO hay pieza (segun la camara). Elige otro origen.", V.ROJO, "todo"  
            if t.fondo_rect is not None:  
                return False, f"Origen {o} con pieza. Ahora elige la casilla de DESTINO.", V.AMARILLO, "nada"  
            return False, f"Origen {o}. Ahora elige el DESTINO.", V.AMARILLO, "nada"  
        if self.brazo.ocupado:  
            return False, "Robot ocupado: espera a que termine el movimiento.", V.NARANJA, "nada"  
        if t.fondo_rect is None:  
            return False, "Falta capturar el tablero VACIO (tecla E en la ventana de la camara).", V.ROJO, "nada"  
        ok, texto, conservar = self.validar(o, d)  
        if not ok:  
            return False, texto, V.ROJO, ("destino" if conservar else "todo")  
        if t.ocluido:  
            return False, "El tablero esta TAPADO (mano o brazo). Espera un momento.", V.ROJO, "nada"  
        if self.congelado():  
            return False, "Estabilizando la lectura de la camara...", V.AMARILLO, "nada"  
        if (t.cuenta > 0).any():  
            return False, "Leyendo el tablero, espera un instante...", V.AMARILLO, "nada"  
        return True, f"{o} -> {d}: origen con pieza y destino libre. Listo para JUGAR.", V.VERDE, "nada"  
   
    # ---------------- acciones ----------------  
    def jugar(self):  
        ok, texto, color, limpiar = self.estado_jugada()  
        if not ok:  
            print("RECHAZADO:", texto)  
            self.msg(texto, V.ROJO, 8)  
            if limpiar == "destino":  
                self.sel_d = None                       # el origen vale: solo falta otro destino  
            elif limpiar == "todo":  
                self.limpiar()  
            return                                      # 'nada': la seleccion se queda para reintentar  
        o, d = self.sel_o, self.sel_d  
        self.limpiar()  
        self.solicitar(o, d)  
   
    def parar(self):  
        self.brazo.parar()  
        self.msg("PARADA DE EMERGENCIA", V.ROJO, 10)  
   
    def _en_hilo(self, hacer, ok_msg):  
        if self.brazo.ocupado:  
            self.msg("Robot ocupado: espera a que termine", V.ROJO, 6)  
            return  
        self.brazo.ocupado = True  
   
        def tarea():  
            try:  
                hacer()  
                self.msg(ok_msg, V.VERDE, 15)  
            except Exception as e:  
                print("ERROR del robot:", e)  
                self.msg(f"Error del robot: {e}", V.ROJO, 15)  
            finally:  
                self.libre_desde = time.time() + V.DESCANSO_S  
                self.brazo.ocupado = False  
   
        threading.Thread(target=tarea, daemon=True).start()  
   
    def reposo_seguro(self):  
        self._en_hilo(self.brazo.reposo, "Brazo en REPOSO SEGURO (apoyado). Ya puedes apagar la fuente.")  
   
    def retirar_brazo(self):  
        self._en_hilo(self.brazo.retirar, "Brazo retirado (fuera del encuadre de la camara).")  
   
    # ---------------- entrada ----------------  
    def clic(self, event, x, y, flags, param):  
        if event != cv2.EVENT_LBUTTONDOWN:  
            return  
        if x < V.BOARD_PIXELS and y < V.BOARD_PIXELS:  
            if self.t.H is not None:  
                self.seleccionar(V.nombre_casilla(min(7, x // V.STEP), min(7, y // V.STEP)))  
            return  
        for b in self.botones:  
            x1, y1, x2, y2 = b["rect"]  
            if x1 <= x <= x2 and y1 <= y <= y2:  
                b["accion"]()  
                return  
   
    def teclado(self, key, frame):  
        if key != 255:  
            c = chr(key).lower()  
            if c == "j":  
                self.jugar()  
                return True  
            if c == "l":  
                self.limpiar()  
                return True  
        return super().teclado(key, frame)  
   
    # ---------------- dibujo ----------------  
    def _caja(self, panel, titulo, valor, rect, color, activa):  
        x1, y1, x2, y2 = rect  
        cv2.rectangle(panel, (x1, y1), (x2, y2), color if activa else GRIS, 3 if activa else 1)  
        V.texto(panel, titulo, (x1 + 10, y1 + 20), 0.5, GRIS_CLARO, 1)  
        V.texto(panel, valor, (x1 + 10, y2 - 12), 1.0, color if valor != "--" else GRIS, 2)  
   
    def render(self, rect):  
        t = self.t  
        if rect is None:  
            tab = np.full((ALTO, V.BOARD_PIXELS, 3), (70, 70, 70), np.uint8)  
            pasos = ["Falta calibrar el tablero.", "En la ventana de la camara:", "1) clic en las 4 esquinas",  
                     "2) pulsa C", "3) pulsa O hasta que A1", "    quede abajo-izquierda", "4) quita las piezas, pulsa E"]  
            for i, linea in enumerate(pasos):  
                V.texto(tab, linea, (40, 200 + 34 * i), 0.7, V.BLANCO, 1)  
        else:  
            tab = V.dibujar_tablero(rect, t, None, self.debug)  
            for nombre, color, rotulo in ((self.sel_o, V.AMARILLO, "ORIGEN"), (self.sel_d, V.CIAN, "DESTINO")):  
                if nombre:  
                    c, r = V.indices(nombre)  
                    cv2.rectangle(tab, (c * V.STEP + 2, r * V.STEP + 2),  
                                  ((c + 1) * V.STEP - 2, (r + 1) * V.STEP - 2), color, 4)  
                    V.texto(tab, rotulo, (c * V.STEP + 6, (r + 1) * V.STEP - 8), 0.4, color, 1)  
            if self.congelado():  
                V.texto(tab, "ROBOT MOVIENDO - lectura congelada", (V.BOARD_PIXELS // 2 - 160, 20), 0.6, V.ROJO, 2)  
            elif t.ocluido:  
                V.texto(tab, "TAPADO (mano o brazo): sin actualizar", (V.BOARD_PIXELS // 2 - 170, 20), 0.6, V.ROJO, 2)  
   
        panel = np.full((ALTO, PANEL_W, 3), FONDO, np.uint8)  
        x0, x1 = 20, PANEL_W - 20  
        V.texto(panel, "AJEDREZ ROBOT", (x0, 38), 0.9, V.BLANCO, 2)  
        V.texto(panel, "Clic en el tablero: 1) origen  2) destino", (x0, 64), 0.45, GRIS_CLARO, 1)  
        self._caja(panel, "ORIGEN", self.sel_o or "--", (x0, 80, x1, 148), V.AMARILLO, self.sel_o is None)  
        self._caja(panel, "DESTINO", self.sel_d or "--", (x0, 158, x1, 226), V.CIAN, self.sel_o is not None and self.sel_d is None)  
   
        ok, texto, color, _ = self.estado_jugada()  
        y = 252  
        for linea in textwrap.wrap(texto, 34)[:3]:  
            V.texto(panel, linea, (x0, y), 0.55, color, 1)  
            y += 24  
        V.texto(panel, "ROBOT: MOVIENDO" if self.brazo.ocupado else "ROBOT: listo", (x0, 340), 0.5,  
                V.NARANJA if self.brazo.ocupado else V.VERDE, 1)  
        if t.H is None or t.fondo_rect is None:  
            cam, ccol = "CAMARA: falta calibrar / tablero vacio (E)", V.ROJO  
        elif t.ocluido:  
            cam, ccol = "CAMARA: tablero tapado", V.ROJO  
        elif self.congelado():  
            cam, ccol = "CAMARA: lectura congelada", V.NARANJA  
        else:  
            cam, ccol = "CAMARA: leyendo bien", V.VERDE  
        V.texto(panel, cam, (x0, 364), 0.5, ccol, 1)  
        s, scol, hasta = self.mensaje  
        if s and time.time() < hasta:  
            y = 394  
            for linea in textwrap.wrap(s, 40)[:2]:  
                V.texto(panel, linea, (x0, y), 0.45, scol, 1)  
                y += 20  
   
        for b in self.botones:  
            x1b, y1b, x2b, y2b = b["rect"]  
            col = b["color"] if (b["id"] != "jugar" or ok) else (80, 80, 80)  
            cv2.rectangle(panel, (x1b - V.BOARD_PIXELS, y1b), (x2b - V.BOARD_PIXELS, y2b), col, -1)  
            esc = 1.0 if b["id"] == "jugar" else 0.5  
            (w, h), _ = cv2.getTextSize(b["texto"], V.FONT, esc, 2 if b["id"] == "jugar" else 1)  
            cx = (x1b + x2b) // 2 - V.BOARD_PIXELS  
            V.texto(panel, b["texto"], (cx - w // 2, (y1b + y2b) // 2 + h // 2), esc, V.BLANCO,  
                    2 if b["id"] == "jugar" else 1)  
        return np.hstack([tab, panel])  
   
def main():  
    ap = argparse.ArgumentParser()  
    ap.add_argument("--camara", type=int, default=V.CAMERA_INDEX)  
    ap.add_argument("--puerto", help="puerto del Arduino (ej. COM6). Sin puerto = simulacion")  
    ap.add_argument("--listar", action="store_true", help="prueba los numeros de camara y sale")  
    args = ap.parse_args()  
    if args.listar:  
        V.listar_camaras()  
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
            print("Retirando el brazo fuera del encuadre de la camara...")  
            brazo.retirar()  
        except (RuntimeError, TimeoutError) as e:  
            print("ERROR:", e)  
            return  
   
    cap = V.abrir_camara(args.camara)  
    if cap is None:  
        print("Error: no se pudo abrir la camara", args.camara, "(prueba:  python juego.py --listar)")  
        return  
   
    app = Juego(brazo)  
    app.libre_desde = time.time() + 1.5               # espera a que el brazo termine de retirarse  
    if app.t.cargar():  
        print("Calibracion anterior cargada (si la camara se movio, pulsa R y recalibra).")  
        app.msg("Calibracion cargada. Revisa que el cuadro calce con el tablero", V.AMARILLO, 10)  
   
    cv2.namedWindow(V.WINDOW_CAMERA)  
    cv2.namedWindow(VENTANA)  
    cv2.setMouseCallback(V.WINDOW_CAMERA, app.clic_camara)  
    cv2.setMouseCallback(VENTANA, app.clic)  
   
    while True:  
        ok, frame = cap.read()  
        if not ok:  
            print("Error: la camara dejo de responder")  
            break  
        cv2.imshow(V.WINDOW_CAMERA, app.vista_camara(frame))  
        rect = None  
        if app.t.H is not None:  
            rect = app.t.rectificar(frame)  
            app.procesar(rect)  
        cv2.imshow(VENTANA, app.render(rect))  
        app.revisar_verificacion()  
        if not app.teclado(cv2.waitKey(1) & 0xFF, frame):  
            break  
   
    cap.release()  
    cv2.destroyAllWindows()  
    if args.puerto and brazo.activo:  
        if input("Llevar el brazo al REPOSO SEGURO antes de salir? (S/n): ").strip().lower() != "n":  
            try:  
                brazo.reposo()  
                print("Brazo en reposo seguro. Ya puedes apagar la fuente.")  
            except (RuntimeError, TimeoutError) as e:  
                print("ERROR:", e)  
   
if __name__ == "__main__":  
    main()  
   
