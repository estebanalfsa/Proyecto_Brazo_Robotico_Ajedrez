# Documentacion tecnica del brazo de ajedrez

Esta documentacion explica que hace el sistema, como se instala en otra computadora,
como se calibra, como detecta las piezas, como se entrena el clasificador, como se
calculan las casillas ocupadas y como se ejecuta el robot.

La guia rapida de uso diario esta en `GUIA.md`. Este archivo es la referencia completa.

## 1. Que hace el sistema

El programa une cuatro partes:

1. Una camara mira el tablero.
2. OpenCV rectifica el tablero y detecta que casillas estan ocupadas.
3. Un clasificador KNN reconoce el tipo de pieza por el sticker.
4. python-chess calcula los movimientos legales.
5. El robot recibe los angulos de los servos por puerto serial y mueve la pieza.
6. La camara confirma que el origen quedo libre y el destino ocupado.

El flujo normal es:

```
camara -> tablero rectificado -> casillas ocupadas -> tipo de pieza -> reglas
       -> orden al robot -> movimiento -> verificacion por camara
```

## 2. Estructura del proyecto

```
brazo_robot/
  GUIA.md
  DOCUMENTACION.md
  requirements.txt
  .gitignore
  files/
    juego.py                 interfaz principal
    vision_tablero.py        camara, homografia, ocupacion, reglas visuales
    clasificador.py          KNN de tipos de pieza
    robot.py                 poses, cinematica y puerto serial
    teach.py                 ensenanza de casillas y pinza
    retirada.py              ensenanza de la pose de retirada
    brazo_serial/
      brazo_serial.ino       firmware del Arduino
    poses_ensenadas.json     poses del robot, archivo mas valioso
    calibracion_tablero.json esquinas y orientacion del tablero
    fondo_vacio.png          foto del tablero vacio
    calibracion_top.json     altura de los stickers, opcional
    modelo_piezas.npz        modelo KNN entrenado
```

Los datos se guardan junto a los scripts, en `files/`, aunque lances el programa
desde otra carpeta. La mayoria de comandos de esta guia suponen que estas dentro de
`files/`.

## 3. Requisitos

### Software

- Python 3.12 o superior. En este equipo se probo con Python 3.14.4.
- OpenCV. En este equipo se probo con `opencv-python 5.0.0.93`.
- NumPy. En este equipo se probo con `numpy 2.5.3`.
- pyserial. En este equipo se probo con `pyserial 3.5`.
- python-chess. En este equipo se probo con `chess 1.11.2`.
- Arduino IDE, solo si hay que cargar el firmware.

El codigo no usa `cv2.ml`, porque OpenCV 5 ya no lo incluye. El KNN esta hecho en
NumPy.

### Hardware

- Camara web. La camara 0 suele ser la del portatil y la 1 una camara externa.
- Arduino con el firmware `brazo_serial.ino`.
- Brazo con 6 servos: base, hombro, codo, muneca, gancho y pinza.
- Fuente externa para los servos. No alimentes los servos desde el Arduino.
- Tablero y tablitas o piezas con sticker. El entrenamiento actual esta pensado
  para 16 piezas del mismo equipo.

## 4. Instalacion en otra computadora

### Paso 1: copiar el proyecto

Copia la carpeta completa `brazo_robot`, no solo los `.py`. Necesitas tambien la
carpeta `files/` y, si vas a usar el mismo robot, estos archivos:

- `files/poses_ensenadas.json`
- `files/calibracion_tablero.json`
- `files/fondo_vacio.png`
- `files/calibracion_top.json`, si existe
- `files/modelo_piezas.npz`, si ya entrenaste

Si la otra computadora controla el mismo robot fisico, copia `poses_ensenadas.json`.
Si es otro robot, tendras que ensenar las casillas de nuevo con `teach.py`.

Si la otra computadora usa otra camara, otra luz o el tablero esta en otra posicion,
tendras que recalibrar y probablemente reentrenar.

### Paso 2: instalar Python y dependencias

En Windows, desde la carpeta del proyecto:

```powershell
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

Si no usas `requirements.txt`:

```powershell
py -m pip install opencv-python numpy pyserial chess
```

En Linux o macOS, cambia `py` por `python3`:

```bash
python3 -m pip install -r requirements.txt
```

Si ya estas dentro de `files/`, usa `../requirements.txt`. En Windows seria
`..\requirements.txt`.

### Paso 3: cargar el firmware del Arduino

Solo si el Arduino no tiene ya el firmware de esta version:

1. Abre `files/brazo_serial/brazo_serial.ino` en Arduino IDE.
2. Selecciona la placa y el puerto correctos.
3. Instala la libreria `Servo` si no la tienes. Viene incluida en Arduino IDE.
4. Carga el sketch.
5. Cierra el Monitor Serial antes de usar `juego.py`.

El firmware actual acepta `A b h c m g p` para activar los servos en una pose
concreta. Esto se usa para arrancar en la pose de retirada sin tumbar piezas. Si el
Arduino tiene un firmware viejo, el comando `A ...` puede ignorarse y el brazo puede
saltar al reposo.

### Paso 4: conectar camara y Arduino

En Windows, el puerto suele ser `COM3`, `COM4`, `COM5`, etc. En Linux suele ser
`/dev/ttyUSB0` o `/dev/ttyACM0`. En macOS suele ser `/dev/cu.usbmodem...`.

Para encontrar la camara:

```powershell
cd files
py juego.py --listar
```

Para encontrar el puerto en Windows, abre el Administrador de dispositivos y mira
`Puertos (COM y LPT)`. En Linux:

```bash
ls /dev/ttyUSB* /dev/ttyACM*
```

### Paso 5: probar sin robot

```powershell
cd files
py juego.py --camara 0
```

Sin `--puerto` todo es simulacion. El robot no se mueve. El programa imprime los
comandos que enviaria al Arduino con el prefijo `[SIM]`.

### Paso 6: probar con robot

```powershell
cd files
py juego.py --camara 0 --puerto COM5
```

Antes de aceptar, el programa te pide que el brazo este fisicamente en la pose de
retirada y que enciendas la fuente de los servos en ese momento. Esto evita que los
servos se activen con el brazo encima del tablero.

## 5. Comandos principales

### Juego

```powershell
py juego.py --listar
py juego.py --camara 0
py juego.py --camara 0 --puerto COM5
```

- `--listar`: prueba las camaras 0 a 5 y sale. Es seguro.
- `--camara N`: elige la camara.
- `--puerto COMx`: usa el robot real. Sin esto, simulacion.

La vision tambien se puede abrir sola, sin las reglas de ajedrez:

```powershell
py vision_tablero.py --listar
py vision_tablero.py --camara 0
py vision_tablero.py --camara 0 --puerto COM5
```

Para jugar se recomienda `juego.py`. `vision_tablero.py` sirve para diagnostico de
la camara y para usar la interfaz original sin reglas de ajedrez.

### Robot

Todos estos comandos funcionan sin `--puerto` en simulacion:

```powershell
py robot.py info
py robot.py tabla
py robot.py angulos A1
py robot.py mover A1 A2
py robot.py ir A1 --bajar --puerto COM5
py robot.py reposo --puerto COM5
py robot.py consola --puerto COM5
```

- `info`: muestra el modo, los angulos de la pinza, la retirada y las casillas.
- `tabla`: muestra que casillas estan ensenadas o calculadas.
- `angulos A1`: muestra la pose segura y la pose de agarre de A1.
- `mover A1 A2`: simula o ejecuta la secuencia completa.
- `ir A1 --bajar`: lleva el brazo a una casilla, util para afinar.
- `reposo`: manda el brazo al reposo.
- `consola`: escribes `A1 H1` y el robot mueve la pieza.

Ejemplo de `robot.py info`:

```text
Pinza: abierta=64, toca la pieza en 40, se cierra a 15 (apriete +25); limites del firmware 10-110
```

### Ensenanza del robot

```powershell
py teach.py --puerto COM5
py teach.py --puerto COM5 --fila 1
py teach.py --puerto COM5 --solo A1,C1
py teach.py --puerto COM5 --pinza
py teach.py --puerto COM5 --rehacer
py retirada.py --puerto COM5
```

- `teach.py`: ensena las casillas que faltan.
- `--fila 1`: solo la fila 1.
- `--solo A1,C1`: solo esas casillas.
- `--pinza`: reensena solo los angulos de abrir y tocar la pieza.
- `--rehacer`: empieza de cero. Guarda una copia `.bak`, pero no lo uses a la ligera.
- `retirada.py`: ensena la pose donde el brazo queda fuera del encuadre.

`poses_ensenadas.json` es el archivo mas valioso del proyecto. No lo edites a mano,
no lo borres y no lo reemplaces sin una copia de seguridad.

## 6. Puesta en marcha

### Simulacion

```powershell
cd files
py juego.py --camara 0
```

Al arrancar:

- Carga `calibracion_tablero.json` y `fondo_vacio.png` si existen.
- Carga `calibracion_top.json` si existe.
- Carga `modelo_piezas.npz` si existe.
- Carga `poses_ensenadas.json` desde `robot.py`.

### Robot real

1. Coloca el brazo fisicamente en la pose de retirada.
2. Conecta el Arduino por USB.
3. Cierra el Monitor Serial.
4. Ejecuta:

```powershell
cd files
py juego.py --camara 0 --puerto COM5
```

5. El programa lee los limites del firmware con el comando `L`.
6. Compara esos limites con los que se usaron al ensenar las casillas. Si cambiaron,
   se niega a mover y pide reensenar.
7. Pide encender la fuente de los servos.
8. Activa los servos en la pose de retirada.

### Apagado

1. Pulsa `REPOSO SEGURO` o `RETIRAR BRAZO`.
2. Espera a que termine el movimiento.
3. Apaga la fuente de los servos.
4. Pulsa `Q` para cerrar.

No apagues la fuente mientras el brazo esta sosteniendo una pieza.

## 7. Calibracion de la camara

### Esquinas y orientacion

1. Abre la ventana de la camara.
2. Haz clic en las 4 esquinas del tablero. El orden no importa.
3. Pulsa `C` para calcular la homografia.
4. Pulsa `O` hasta que A1 quede abajo a la izquierda, del lado del robot.
5. Quita todas las piezas y retira el brazo del encuadre.
6. Pulsa `E` para capturar el tablero vacio.

`C` guarda las esquinas y la orientacion en `calibracion_tablero.json`.
`E` guarda la foto del tablero vacio en `fondo_vacio.png`.

Si mueves la camara o el tablero, pulsa `R`, vuelve a marcar las 4 esquinas y repite
`C` y `E`.

### Altura de los stickers, opcional

La camara esta inclinada y las tablitas pueden salir desplazadas por el paralaje.
La calibracion de altura corrige eso antes de recortar la pieza para clasificarla.

1. Pulsa `H`.
2. Haz clic en el centro del sticker de A1.
3. Luego en H1.
4. Luego en H8.
5. Luego en A8.

Se guarda en `calibracion_top.json`. Si no existe, el clasificador usa la vista
rectificada normal.

## 8. Como se calcula si una casilla esta ocupada

Esta es la parte central de `vision_tablero.py`.

### 8.1 Rectificacion

Con las 4 esquinas se calcula una homografia con `cv2.getPerspectiveTransform`.
El tablero se transforma a una imagen cuadrada de `640 x 640` pixeles.
Cada casilla mide `80 x 80` pixeles (`STEP = 640 / 8`).

La vista rectificada siempre tiene:

- columna 0 = A
- columna 7 = H
- fila 0 = rango 8
- fila 7 = rango 1

Por eso A1 queda abajo a la izquierda.

### 8.2 Comparacion contra el tablero vacio

Para cada frame:

1. Se pasa la imagen actual y la foto vacia a escala de grises.
2. Se aplica un desenfoque gaussiano de `5 x 5`.
3. Se compensa un cambio global de luz usando solo el borde de las casillas.
4. Se calcula la diferencia absoluta: `diff = abs(actual - fondo)`.
5. Se calculan bordes Canny en la imagen actual.
6. Se calculan bordes Canny en el fondo y se dilatan.
7. Los bordes nuevos son los que estan en la actual pero no en el fondo.

La compensacion de luz usa el borde exterior de cada casilla, porque ahi casi nunca
hay una pieza. No se usa la mediana de todo el tablero porque un tablero de ajedrez
tiene dos tonos y la mediana no representa bien la luz.

### 8.3 Decision por casilla

Cada casilla se analiza sin el 15 por ciento de su borde:

```python
MARGEN_CASILLA = 0.15
UMBRAL_PIXEL = 15
FRACCION_OCUPADA = 0.20
CANNY_BAJO, CANNY_ALTO = 20, 60
FRACCION_BORDES = 0.03
```

Para cada casilla:

```text
frac = fraccion de pixeles con diff > 15
fbor = fraccion de pixeles con borde nuevo
```

La casilla se marca ocupada si:

```text
frac > 0.20  OR  fbor > 0.03
```

`frac` detecta cambios de color o de brillo. `fbor` detecta piezas del mismo tono que
la casilla, que casi no cambian el brillo pero si agregan bordes.

La tecla `D` muestra en pantalla los dos porcentajes de cada casilla. Sirve para
diagnosticar por que una casilla se ve ocupada o vacia.

### 8.4 Estabilidad

Una sola lectura no basta. Se exige:

```python
FRAMES_ESTABLES = 6
```

Un cambio de ocupacion se acepta solo si se repite 6 frames seguidos. Asi se evita
que un reflejo o un frame malo marquen una pieza fantasma.

### 8.5 Mano o brazo tapando el tablero

```python
MAX_CAMBIOS = 6
FRAMES_RESYNC = 45
```

Si cambian mas de 6 casillas de golpe, el programa asume que una mano o el brazo
esta tapando el tablero. No actualiza el estado y muestra `TAPADO`.

Si esa lectura rara se queda quieta durante 45 frames, el programa la acepta como
estado real. Eso permite colocar varias piezas a mano de golpe sin tener que reiniciar.

### 8.6 Confirmacion despues de mover

Cuando el robot termina, el programa espera `VERIF_ESPERA_S = 2.5` segundos y
comprueba:

```text
destino ocupado  AND  origen libre
```

Solo entonces registra la jugada en el tablero logico. El estado no se adelanta a
mano. La camara es la fuente de verdad.

## 9. Equipo y tipo de pieza

Son dos problemas separados.

### 9.1 Equipo por color

El equipo se detecta con los pixeles de la pieza, no con el fondo de la casilla.

Dentro de la mascara de cambio de cada casilla se pasa la imagen a HSV y se cuentan:

- verde: matiz entre 40 y 90, saturacion mayor que 70, brillo mayor que 50
- rojo: matiz menor que 10 o mayor que 170, saturacion mayor que 120, brillo mayor que 60

Si la fraccion de pixeles verdes o rojos supera `UMBRAL_EQUIPO = 0.08`, el equipo es
`R`. Si no, es `N`.

`R` significa tablita verde con sticker rojo.
`N` significa sticker negro.

El color tiene histeresis de `FRAMES_COLOR = 10` lecturas seguidas. Asi no parpadea
entre verde y naranja.

`equipo_propio()` toma la mayoria de las piezas vistas en todo el tablero. El
entrenamiento, en cambio, sigue exigiendo 16 piezas en las filas 1 y 2.

### 9.2 Tipo de pieza

El tipo se reconoce con `clasificador.py`.

No es una red neuronal. Es un KNN sobre la imagen binarizada del sticker:

1. Se recorta la casilla, con un margen del 12 por ciento.
2. Se pasa a grises.
3. Se aplica un desenfoque gaussiano de `3 x 3`.
4. Se binariza con umbral adaptativo gaussiano, bloque 15, constante 8.
5. Se reduce a `32 x 32` pixeles.
6. Se convierte en un vector de 1024 valores entre 0 y 1.

Para predecir:

1. Se calcula la distancia cuadratica entre el vector nuevo y todas las muestras.
2. Se toman los 5 vecinos mas cercanos.
3. Se hace voto mayoritario.
4. La confianza es la cantidad de votos del tipo ganador dividida entre 5.

Los tipos son:

```text
P peon, N caballo, B alfil, R torre, Q dama, K rey
```

### 9.3 Entrenamiento

El entrenamiento es automatico porque la posicion inicial se conoce:

```text
fila 1: R N B Q K B N R   (dama en D1, rey en E1)
fila 2: ocho peones
```

Pasos:

1. Calibra el tablero con `C`, `O` y `E`.
2. Coloca las 16 piezas de tu equipo en la posicion inicial exacta.
3. Pulsa `D` y comprueba que hay 16 piezas y que todas son del mismo equipo.
4. Pulsa `P`.

`P` se niega si no ve exactamente 16 piezas de tu equipo en las filas 1 y 2.

Cada pieza genera 9 muestras:

- la original
- giros de -8, -4, 4 y 8 grados
- desplazamientos de 2 pixeles a izquierda, derecha, arriba y abajo

Son 144 muestras por ronda. Se acumulan en `modelo_piezas.npz`.

No muevas una pieza a otra casilla entre rondas. Si lo haces, la etiqueta de esa
casilla sera incorrecta y envenenaras el modelo. Entre rondas solo se permite mover
la tablita unos milimetros o girarla un poco dentro de su propia casilla.

`P` acumula muestras. No hay forma de deshacer una ronda mala desde el programa.
Para empezar de cero, cierra el programa, borra `files/modelo_piezas.npz` y vuelve a
entrenar.

### 9.4 Validacion con V

`V` compara el tipo predicho con el esperado en la posicion inicial. Imprime en
consola, casilla por casilla, el esperado, el visto, la confianza y si acierta.

Es una validacion EN MUESTRA: usa las mismas imagenes del entrenamiento. Sale
optimista. Sirve para detectar confusiones gruesas, no para medir precision real.

Prueba clave: intercambia a mano A1 y B1. Si A1 muestra `N` y B1 muestra `R`, el
clasificador aprendio el sticker. Si siguen diciendo `R` y `N`, aprendio la casilla
y hay que revisar el recorte o la calibracion de altura.

## 10. Reglas de ajedrez

`juego.py` usa python-chess.

Al arrancar, el tablero logico esta en la posicion inicial completa. Se juega solo
el lado blanco, que corresponde a las filas 1 y 2.

Reglas activas:

- solo tu lado
- sin capturas
- sin enroque
- sin promocion

`casillas_legales()` toma la pieza de la casilla de origen, comprueba que sea de tu
color y devuelve los destinos legales que no sean captura, enroque ni promocion.

`validar()` comprueba:

1. que el origen tenga pieza segun la camara
2. que el destino este libre segun la camara
3. que el brazo llegue a las dos casillas
4. que la jugada sea legal en python-chess

Si todo pasa, el robot mueve. La jugada se registra en el tablero logico solo cuando
la camara confirma que el destino quedo ocupado y el origen libre.

### 10.1 Modo de prueba con S

El tablero logico inicial no sirve si estas probando una sola pieza. Por ejemplo, una
torre en A1 sigue bloqueada por el peon de A2 y el caballo de B1 aunque en la mesa no
esten.

La tecla `S` reconstruye el tablero logico con lo que ve la camara:

- las piezas de tu equipo con tipo reconocido se colocan como piezas blancas
- cualquier otra casilla ocupada se coloca como peon negro, solo para bloquear
- el turno es siempre blanco

Despues de `S`, si mueves piezas a mano, vuelve a pulsar `S`.

`S` necesita el clasificador entrenado y una lectura estable. No crea una partida
completa: las piezas del otro equipo solo bloquean, no se capturan. Es un modo de
prueba para comprobar alcance y bloqueos pieza por pieza.

## 11. Robot, poses y pinza

### 11.1 Poses ensenadas

`teach.py` guarda 32 casillas: las columnas A, C, F y H, en las 8 filas.
Cada casilla tiene dos poses:

- `segura`: altura para pasar por encima de las piezas
- `agarre`: altura para rodear la pieza

Las otras 32 casillas se calculan interpolando entre las columnas ensenadas. En la
practica quedan disponibles las 64 casillas.

La interpolacion es lineal a tramos entre las columnas A, C, F y H de la misma fila.
No es una interpolacion global de todo el tablero.

### 11.2 Secuencia de movimiento

Antes de mover nada, `planificar()` calcula todas las poses. Si alguna casilla esta
fuera de alcance, falla antes de mover el brazo.

La secuencia es:

1. ir sobre el origen en altura segura
2. bajar en 3 pasos con la pinza abierta
3. cerrar la pinza
4. subir con la pieza
5. levantar 12 grados el hombro para trasladar
6. ir sobre el destino
7. bajar en 3 pasos
8. abrir la pinza
9. subir
10. volver a la pose de retirada

### 11.3 Pinza

Valores actuales de `poses_ensenadas.json`:

```text
pinza abierta: 64
pinza tocando la pieza: 40
limite inferior del firmware: 10
limite superior del firmware: 110
```

`robot.py` tiene:

```python
APRIETE_PINZA = 25
```

El cierre es:

```text
40 - 25 = 15
```

La pinza se cierra en 15 grados para sujetar con mas fuerza. Si el servo zumba fuerte
o se calienta, hay que bajar el apriete. Si la pieza resbala, se puede subir un poco,
pero cuidando el limite inferior de 10.

Si la pinza no agarra, revisa en este orden:

1. que la bateria o fuente de los servos este cargada
2. que la tablita este centrada entre las dos mandibulas
3. que la altura de agarre no sea demasiado alta ni demasiado baja
4. que el servo de la pinza no este debilitado
5. recien despues, ajustar `APRIETE_PINZA`

### 11.4 Firmware

El Arduino habla por serial a 9600 baudios. Comandos:

| Comando | Significado |
|---|---|
| `A` | activar servos en la pose de reposo |
| `A b h c m g p` | activar servos en esa pose |
| `G b h c m g p` | ir a la pose indicada |
| `H` | volver al reposo |
| `X` | parada, congela los servos |
| `P` | imprimir la posicion actual |
| `L` | imprimir limites y reposo |

`robot.py` lee los limites con `L` antes de activar. Si los limites del firmware no
coinciden con los que se usaron al ensenar las casillas, se niega a mover y pide
reensenar. Esto evita que un cambio de firmware rompa las poses.

## 12. Teclas

### Ventana del juego

| Tecla | Accion |
|---|---|
| Clic | primer clic origen, segundo clic destino |
| `J` | ejecutar la jugada |
| `L` | limpiar origen y destino |
| `P` | entrenar el clasificador con la posicion inicial |
| `H` | calibrar la altura de los stickers |
| `V` | informe de validacion en muestra |
| `S` | sincronizar el tablero logico con la camara |
| `X` | parada de emergencia |
| `Q` o `Esc` | salir |

### Teclas heredadas de la vision

| Tecla | Accion |
|---|---|
| `C` | calibrar con las 4 esquinas |
| `E` | capturar el tablero vacio |
| `O` | girar la orientacion 90 grados |
| `M` | modo jugada por teclado, por ejemplo `E3 G5` |
| `T` | exportar `mapa_casillas.csv` |
| `D` | diagnostico de deteccion |
| `U` | aceptar la lectura actual como estado real |
| `R` | reiniciar la calibracion |

## 13. Diagnostico

### D

Activa el diagnostico. En cada casilla muestra dos porcentajes:

```text
frac / fbor
```

`frac` es la fraccion de pixeles cambiados. `fbor` es la fraccion de bordes nuevos.
Si una casilla se ve ocupada sin pieza, compara esos valores con los umbrales.

### U

Acepta la lectura actual como estado real. Se usa cuando colocas o quitas varias
piezas a mano de golpe. Pulsalo con el brazo retirado y sin manos en la imagen.

### T

Exporta `mapa_casillas.csv` con la posicion en pixeles, la posicion en milimetros,
la ocupacion y el color de cada casilla. Es un archivo de diagnostico y esta ignorado
por Git.

### M

Modo jugada por teclado. Escribes origen y destino, por ejemplo `E3 G5`. Es util si
el mouse no es comodo.

## 14. Problemas frecuentes

| Sintoma | Que revisar |
|---|---|
| `TAPADO` | retira mano o brazo, espera, o pulsa `U` |
| A1 no queda abajo a la izquierda | pulsa `O` hasta corregir |
| Todo desplazado tras mover la camara | `R`, recalibrar, `C`, `O`, `E` |
| `No hay pieza en X` | revisa `D`, la luz y la calibracion |
| El clasificador no acierta | reentrena con buena luz y repite el intercambio A1/B1 |
| Una torre no se mueve aunque delante no haya nada | pulsa `S` para reconstruir el tablero logico |
| `S` dice `Clasificador sin entrenar` | pulsa `P` y entrena |
| `S` dice `No detecto piezas` | revisa `D` y la camara |
| La camara no confirma el movimiento | revisa `U` y `D`; el tablero logico no avanza |
| El robot no responde | revisa el puerto, cierra el Monitor Serial y la fuente de servos |
| El brazo salta al reposo al arrancar | el firmware es viejo; carga `brazo_serial.ino` actual |
| La pinza no agarra | revisa bateria, centrado, altura de agarre y `APRIETE_PINZA` |
| Falla python-chess | `py -m pip install chess` |
| Falla pyserial | `py -m pip install pyserial` |

## 15. Archivos de datos y respaldo

### `poses_ensenadas.json`

Contiene los limites del firmware, los angulos de la pinza, la pose de retirada y las
32 casillas ensenadas. Es el archivo mas valioso. Haz copia antes de cambiar de
computadora o de reensenar.

### `calibracion_tablero.json`

Contiene las 4 esquinas y la orientacion. Esta atado a la posicion de la camara.

### `fondo_vacio.png`

Foto del tablero vacio. Esta atada a la camara, la luz y el tablero.

### `calibracion_top.json`

Homografia de la altura de los stickers. Es opcional. Si no existe, se usa la vista
rectificada normal.

### `modelo_piezas.npz`

Modelo KNN. Contiene `X` con las muestras y `y` con las etiquetas. Esta atado a la
camara, la luz y el tablero. Si cambias mucho el entorno, reentrena.

### `mapa_casillas.csv`

Diagnostico. Se puede borrar. Esta ignorado por Git.

## 16. Limitaciones conocidas

- Solo se mueve tu lado. No hay oponente ni turnos alternos.
- No hay capturas, enroque ni promocion.
- El tablero logico normal arranca en la posicion inicial. Para otra posicion usa `S`.
- `S` es un modo de prueba: las piezas del otro equipo solo bloquean.
- El clasificador es un KNN, no una red neuronal. Depende de la luz, el contraste y el
  paralaje.
- La deteccion de equipo por color puede fallar con otra luz o con casillas verdes o
  rojas. El umbral esta en `UMBRAL_EQUIPO`.
- La pinza y los servos dependen de la bateria o fuente. Si la alimentacion baja, el
  robot puede no agarrar o no llegar a la pose.
- No hay deteccion de colisiones con el brazo. El programa asume que el brazo esta
  fuera del encuadre cuando no se mueve.

## 17. Puesta en marcha desde cero, resumida

```powershell
cd brazo_robot
py -m pip install -r requirements.txt
cd files
py juego.py --listar
py robot.py info
py juego.py --camara 0
```

Si la camara y el tablero ya estan calibrados y el modelo existe, solo necesitas
`py juego.py --camara 0`. Si no:

1. Clic en las 4 esquinas.
2. `C`.
3. `O` hasta que A1 quede abajo a la izquierda.
4. Quitar piezas y brazo.
5. `E`.
6. Colocar las 16 piezas en la posicion inicial.
7. `P` tres veces, moviendo un poco las tablitas entre rondas.
8. `V` para validar.
9. Probar una pieza sola con `S`.
10. Recien despues, usar `--puerto`.

## 18. Copia minima para otra computadora

Si solo vas a ejecutar, no a reensenar:

```text
brazo_robot/
  requirements.txt
  files/
    juego.py
    vision_tablero.py
    clasificador.py
    robot.py
    teach.py
    retirada.py
    poses_ensenadas.json
    calibracion_tablero.json
    fondo_vacio.png
    calibracion_top.json    (si existe)
    modelo_piezas.npz
    brazo_serial/
      brazo_serial.ino
```

Si la otra computadora controla otro robot, no copies `poses_ensenadas.json` como
definitivo. Usa `teach.py --rehacer` y ensena las casillas de ese robot.
