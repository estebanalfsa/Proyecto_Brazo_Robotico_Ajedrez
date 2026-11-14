"""
retirada.py - Ensenarle al robot una pose de RETIRADA (el brazo fuera del encuadre de la camara)
================================================================================================
El reposo de fabrica deja el brazo encima del tablero y la camara lo ve. La retirada es otra pose,
mas atras, a la que el robot vuelve despues de cada movimiento y al arrancar.

El brazo arranca siempre en el reposo de siempre (apoyado, no se cae). Aqui lo mueves con el teclado
hacia atras, hasta que NINGUNA parte quede dentro del tablero que ve la camara, y pulsas G.

Uso (en una terminal):
    python retirada.py --puerto COM6          # robot real
    python retirada.py                        # simulacion

Teclas: A/D base | W/S hombro | E/Q codo | R/F gancho | 1/2/3 tamano del paso | G guardar | 0 salir
(Antes tienes que haber ensenado casillas con teach.py: la retirada se guarda en el mismo archivo.)
"""
import argparse
import json
import os
import sys

import robot
import teach


def main(argv=None, teclado=None, brazo=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", help="ej. COM6. Sin puerto = simulacion")
    args = ap.parse_args(argv)

    if not os.path.exists(teach.ARCHIVO):
        print("ERROR: todavia no hay casillas ensenadas. Ejecuta antes teach.py")
        return 1
    try:
        if brazo is None:
            brazo = robot.Brazo(args.puerto)
        mn, mx, ini = brazo.leer_limites()
    except (RuntimeError, TimeoutError) as e:
        print("ERROR:", e)
        return 1
    with open(teach.ARCHIVO, encoding="utf-8") as f:
        datos = json.load(f)
    if datos.get("limites") != {"mn": mn, "mx": mx, "reposo": ini}:
        print("ERROR: los limites del firmware cambiaron desde que ensenaste las casillas. Usa teach.py --rehacer")
        return 1

    if args.puerto and not robot.confirmar_encendido():
        return 0
    robot.POSES = None
    try:
        brazo.activar()
    except (RuntimeError, TimeoutError) as e:
        print("ERROR:", e)
        return 1

    previa = datos.get("retirada")
    try:
        with (teclado or teach.Teclado()) as tec:
            ses = teach.Sesion(brazo, datos, mn, mx, ini, tec)
            if previa:
                print("Ya habia una retirada guardada: el brazo va hacia ella para que la ajustes.")
                ses.ir(previa)
            while ses.jog("POSE DE RETIRADA",
                          "  Mueve el brazo HACIA ATRAS hasta que ninguna parte quede dentro del tablero que ve\n"
                          "  la camara, sin que choque con nada.   G = guardar") != "g":
                pass
            datos["retirada"] = list(ses.pose)
            teach.guardar(datos)
    except teach.Salir:
        print("\nSaliendo sin guardar cambios.")
        return 0
    except teach.ErrorRobot as e:
        print(f"\nERROR DEL ROBOT: {e}")
        return 1
    print(f"\nRetirada guardada: {datos['retirada']}")
    print("Se usa sola: despues de cada movimiento el brazo se retira ahi.")
    print("Antes de APAGAR la fuente, usa el boton REPOSO SEGURO (el brazo apoyado no se cae).")
    return 0


if __name__ == "__main__":
    sys.exit(main())