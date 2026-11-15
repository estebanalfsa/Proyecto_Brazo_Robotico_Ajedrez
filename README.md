# Brazo de ajedrez robotico

Sistema que une una camara, vision por computadora y un brazo de 6 servos para
reconocer piezas de ajedrez, validar movimientos y moverlas fisicamente sobre el
tablero.

El programa mira el tablero con OpenCV, detecta que casillas estan ocupadas,
clasifica el tipo de pieza por su sticker, calcula los movimientos legales con
python-chess y envia los angulos de los servos al Arduino por puerto serial.
Despues del movimiento, la camara confirma que la pieza llego al destino.

```text
camara -> tablero rectificado -> casillas ocupadas -> tipo de pieza -> reglas
       -> orden al robot -> movimiento -> verificacion por camara
```

## Estado del proyecto

La fase de reconocimiento y control esta integrada y el robot esta operativo.
Queda pendiente afinar el agarre y el traslado de algunas piezas, especialmente
cuando la bateria o la fuente de los servos baja de voltaje.

## Que hace

- Rectifica el tablero a partir de 4 esquinas marcadas con el mouse.
- Detecta casillas ocupadas comparando contra una foto del tablero vacio.
- Distingue el equipo de la pieza por color: tablita verde con sticker rojo (`R`)
  o sticker negro (`N`).
- Reconoce el tipo de pieza con un KNN: peon, caballo, alfil, torre, dama o rey.
- Calcula destinos legales con python-chess.
- Muestra puntos verdes en las casillas permitidas.
- Mueve la pieza con el brazo y verifica el resultado con la camara.
- Permite probar piezas sueltas reconstruyendo el tablero logico desde la camara.
- Incluye calibracion de altura de stickers para reducir el error por paralaje.
- Arranca el brazo en una pose de retirada para no tumbar piezas.

## Reglas actuales

- Solo se mueve el lado del usuario (blancas), que empieza en las filas 1 y 2.
- No hay oponente automatico.
- No hay capturas.
- No hay enroque.
- No hay promocion.
- El tablero logico normal arranca en la posicion inicial de ajedrez.

La tecla `S` permite reconstruir el tablero logico desde la camara para probar
piezas aisladas. En ese modo, las piezas propias usan el tipo reconocido y el resto
de casillas ocupadas solo bloquean el paso.

## Hardware

- Camara web.
- Arduino con el firmware `files/brazo_serial/brazo_serial.ino`.
- Brazo de 6 servos: base, hombro, codo, muneca, gancho y pinza.
- Fuente externa para los servos.
- Tablero de ajedrez y 16 piezas o tablitas del mismo equipo.

No alimentes los servos desde el Arduino. Usa una fuente externa y asegurate de
que comparta tierra con el Arduino.

## Software

- Python 3.12 o superior. Probado con Python 3.14.4.
- OpenCV. Probado con `opencv-python 5.0.0.93`.
- NumPy. Probado con `numpy 2.5.3`.
- pyserial. Probado con `pyserial 3.5`.
- python-chess. Probado con `chess 1.11.2`.

El codigo no usa `cv2.ml`, porque OpenCV 5 ya no lo incluye. El clasificador KNN
esta implementado en NumPy.

## Instalacion rapida

```powershell
py -m pip install -r requirements.txt
cd files
py juego.py --listar
py robot.py info
py juego.py --camara 0
```

Sin `--puerto` el programa funciona en simulacion y no mueve el robot.

Con robot real:

```powershell
py juego.py --camara 0 --puerto COM5
```

En Linux o macOS cambia `py` por `python3`. El puerto del Arduino suele ser
`/dev/ttyUSB0` o `/dev/ttyACM0`.

Antes de usar el puerto, cierra el Monitor Serial de Arduino IDE y carga el
firmware actual si el Arduino tiene una version vieja.

## Estructura del repositorio

```text
brazo_robot/
  README.md
  GUIA.md
  DOCUMENTACION.md
  requirements.txt
  files/
    juego.py                 interfaz de juego y reglas
    vision_tablero.py        camara, homografia y deteccion de ocupacion
    clasificador.py          KNN de tipos de pieza
    robot.py                 poses, movimiento y puerto serial
    teach.py                 ensenanza de casillas y pinza
    retirada.py              ensenanza de la pose de retirada
    brazo_serial/
      brazo_serial.ino       firmware del Arduino
    poses_ensenadas.json     poses del robot
    calibracion_tablero.json esquinas y orientacion del tablero
    fondo_vacio.png          foto del tablero vacio
    calibracion_top.json     altura de stickers, opcional
    modelo_piezas.npz        modelo KNN entrenado
```

`files/modelo_piezas.npz` pesa unos 70 MB porque guarda todas las muestras del
entrenamiento. Por eso el primer `git clone` puede tardar. `mapa_casillas.csv` y
`__pycache__/` son archivos de diagnostico y estan ignorados por Git.

## Primer uso

### 1. Calibrar la camara

1. Abre la ventana de la camara.
2. Haz clic en las 4 esquinas del tablero.
3. Pulsa `C`.
4. Pulsa `O` hasta que A1 quede abajo a la izquierda, del lado del robot.
5. Quita las piezas y retira el brazo del encuadre.
6. Pulsa `E` para capturar el tablero vacio.

Se guarda en `calibracion_tablero.json` y `fondo_vacio.png`. Si mueves la camara
o el tablero, pulsa `R` y repite.

### 2. Calibrar la altura de los stickers, opcional

1. Pulsa `H`.
2. Haz clic en el centro del sticker de A1, luego H1, H8 y A8.
3. Se guarda en `calibracion_top.json`.

Esta calibracion reduce el error por paralaje al recortar la pieza para
clasificarla.

### 3. Entrenar el clasificador

1. Coloca las 16 piezas en la posicion inicial exacta.
2. Pulsa `D` y comprueba que hay 16 piezas del mismo equipo.
3. Pulsa `P`.
4. Repite `P` dos o tres veces, moviendo un poco cada tablita dentro de su casilla.
5. Pulsa `V` para ver el informe de validacion.

El modelo se guarda en `modelo_piezas.npz`. `P` acumula muestras. Para empezar de
cero, borra ese archivo y vuelve a entrenar.

### 4. Jugar o probar

1. Haz clic en el origen. Aparecen puntos verdes en los destinos legales.
2. Haz clic en el destino.
3. Pulsa `J` o el boton `JUGAR`.
4. El robot mueve y la camara confirma.

Para probar una sola pieza, deja solo esa pieza en la mesa, pulsa `D`, luego `S`
y selecciona el origen.

## Teclas principales

| Tecla | Accion |
|---|---|
| Clic | Primer clic origen, segundo clic destino |
| `J` | Ejecutar la jugada |
| `L` | Limpiar origen y destino |
| `P` | Entrenar el clasificador |
| `H` | Calibrar altura de stickers |
| `V` | Informe de validacion en muestra |
| `S` | Sincronizar tablero logico con la camara |
| `X` | Parada de emergencia |
| `Q` o `Esc` | Salir |
| `C` | Calibrar con 4 esquinas |
| `E` | Capturar tablero vacio |
| `O` | Girar orientacion 90 grados |
| `M` | Modo jugada por teclado |
| `T` | Exportar mapa de casillas |
| `D` | Diagnostico de deteccion |
| `U` | Aceptar la lectura actual como estado real |
| `R` | Reiniciar calibracion |

## Como se detecta una casilla ocupada

1. El tablero se rectifica a 640 x 640 pixeles con una homografia.
2. Cada casilla mide 80 x 80 pixeles.
3. La imagen actual se compara contra `fondo_vacio.png`.
4. Se calcula la diferencia absoluta en escala de grises.
5. Se calculan bordes Canny nuevos.
6. En el interior de cada casilla se calcula:
   - `frac`: fraccion de pixeles con diferencia mayor que 15.
   - `fbor`: fraccion de bordes nuevos.
7. La casilla se marca ocupada si `frac > 0.20` o `fbor > 0.03`.
8. Un cambio se acepta solo tras 6 lecturas estables.
9. Si cambian mas de 6 casillas de golpe, se asume que una mano o el brazo tapa el tablero.

La tecla `D` muestra `frac / fbor` por casilla para diagnosticar.

## Como se reconoce la pieza

El tipo se reconoce con un KNN sobre la imagen binarizada del sticker:

1. Se recorta la casilla.
2. Se pasa a grises y se binariza con umbral adaptativo.
3. Se reduce a 32 x 32 pixeles.
4. Se compara contra las muestras guardadas con distancia euclidiana.
5. Se usan los 5 vecinos mas cercanos y voto mayoritario.

El entrenamiento usa la posicion inicial conocida:

```text
fila 1: R N B Q K B N R
fila 2: ocho peones
```

Cada pieza genera 9 variantes: giros pequenos y desplazamientos de 2 pixeles.
Son 144 muestras por ronda.

## Documentacion

- `GUIA.md`: guia rapida de uso, calibracion, entrenamiento y apagado.
- `DOCUMENTACION.md`: referencia tecnica completa, instalacion en otra computadora,
  algoritmos, comandos, firmware y solucion de problemas.

## Advertencia

`files/poses_ensenadas.json` es el archivo mas valioso del proyecto. Contiene las
poses ensenadas del robot y los limites con los que fueron grabadas. No lo edites,
no lo borres y no lo reemplaces sin una copia de seguridad y sin confirmacion.

Si el brazo se mueve solo, pulsa `X` para detenerlo. Si vas a apagar la fuente,
primero manda el brazo a `REPOSO SEGURO` o a `RETIRAR BRAZO`.

## Limitaciones conocidas

- Solo se mueve el lado del usuario.
- No hay capturas, enroque ni promocion.
- El tablero logico normal arranca en la posicion inicial.
- `S` es un modo de prueba, no una partida completa.
- El clasificador depende de la luz, el contraste y el paralaje.
- La deteccion de equipo por color puede fallar con otra iluminacion.
- El agarre depende del estado de la bateria o fuente de los servos.
- No hay deteccion de colisiones con el brazo.
