# GUIA.md

Brazo de ajedrez con Arduino, visión OpenCV y reconocimiento de piezas.
Esta guía cubre la fase de reconocimiento (solo tu lado, filas 1 y 2).

## Requisitos

```
py -m pip install opencv-python numpy pyserial chess
```

Trabaja siempre dentro de `files/`. Los scripts guardan sus datos junto a ellos,
así que da igual desde qué carpeta los lances.

## Arranque rápido

```
cd files
py juego.py --listar                  # numero de camara que funciona
py juego.py --camara 0                # simulacion, no mueve el robot
py juego.py --camara 0 --puerto COM5  # con robot (cierra el Monitor Serial antes)
```

Antes de usar `--puerto`, el firmware debe tener cargado el sketch de esta rama:
`A` acepta una pose opcional y el brazo arranca en la pose de retirada.

## Calibrar el tablero

1. En la ventana de la camara, clic en las 4 esquinas del tablero. El orden no importa.
2. En la ventana del juego, pulsa `C`.
3. Pulsa `O` hasta que A1 quede abajo a la izquierda (lado del robot).
4. Quita todas las piezas, retira el brazo del encuadre y pulsa `E`.
5. Vuelve a poner las piezas.

Se guarda en `calibracion_tablero.json` y `fondo_vacio.png`. Si mueves la camara,
pulsa `R` y repite.

## Calibrar la altura de los stickers (opcional, recomendado)

La camara esta inclinada y las tablitas salen desplazadas por el paralaje.
Con esta segunda homografia el recorte para clasificar se hace a la altura del sticker.

1. Pulsa `H`.
2. Clic en el centro del sticker de A1, luego H1, H8 y A8, en ese orden.
3. Se guarda en `calibracion_top.json`.

Si no la calibras, el clasificador usa la vista normal.

## Enseñar el brazo (solo si hace falta repetirlo)

Requiere el robot real y lo ejecutas tu:

```
py teach.py --puerto COM5                 # sigue donde lo dejaste
py teach.py --puerto COM5 --fila 1        # solo fila 1
py teach.py --puerto COM5 --solo A1,C1    # casillas concretas
py teach.py --puerto COM5 --pinza         # solo angulos de pinza
py retirada.py --puerto COM5              # pose de retirada
```

Teclas de `teach.py`: `A/D` base, `W/S` hombro, `E/Q` codo, `R/F` gancho,
`Z/C` pinza, `1/2/3` tamano del paso, `G` guardar y seguir, `B` volver,
`0` o `Esc` salir.

AVISO: `poses_ensenadas.json` es el archivo mas valioso del proyecto. No lo edites,
no lo borres y no lo reemplaces sin confirmacion explicita. `teach.py --rehacer`
hace copia `.bak`, pero no lo uses a la ligera.

## Entrenar el clasificador de piezas

1. Calibra el tablero (`C`, `O`, `E`).
2. Coloca las 16 piezas de tu equipo en la posicion inicial exacta:
   fila 1 = `R N B Q K B N R` (dama en D1, rey en E1), fila 2 = 8 peones.
3. Pulsa `D` y comprueba que hay 16 piezas detectadas con la letra de equipo correcta.
   Si no son 16, corrige luz o contraste, o pulsa `U`, antes de entrenar.
4. Pulsa `P`. El programa se niega si no ve exactamente 16.
5. Repite `P` dos o tres veces. Entre rondas mueve cada tablita 1 o 2 mm o gírala
   un poco, sin cambiar de casilla.
6. El modelo se guarda en `modelo_piezas.npz`.

Verificacion: cada pieza muestra su tipo. Verde si coincide con la posicion inicial,
rojo si no. Prueba clave: intercambia a mano A1 y B1. Si A1 muestra `N` y B1 muestra `R`,
el clasificador aprendio el sticker. Si siguen diciendo `R` y `N`, aprendio la casilla
y hay que reentrenar.

Vuelve a entrenar si mueves la camara, cambias mucho la luz o cambias de tablero.

## Jugar

1. Clic en el origen. Aparecen puntos verdes en las casillas legales.
2. Clic en el destino.
3. Pulsa `J` o el boton JUGAR.
4. El robot mueve y la camara confirma. Si confirma, la jugada se anota en el
   tablero logico de python-chess.

Reglas activas: solo tu lado, sin capturas, sin enroque y sin promocion.

## Probar piezas sueltas

El tablero logico arranca en la posicion inicial completa. Si quitas piezas de la
mesa, para el programa siguen existiendo y una torre puede quedar bloqueada por un
peon que ya no esta.

Para probar una pieza sola:

1. Deja en la mesa solo las piezas que quieras probar.
2. Pulsa `D` y comprueba que la camara las ve.
3. Pulsa `S`. El programa reconstruye el tablero logico con lo que ve:
   las piezas de tu equipo se colocan con su tipo reconocido y cualquier otra
   casilla ocupada bloquea el paso.
4. Selecciona el origen. Los puntos verdes son los destinos legales segun esas piezas.
5. Si mueves piezas a mano, vuelve a pulsar `S`.

`S` necesita el clasificador entrenado y una lectura estable. No crea una partida
completa: sirve para comprobar alcance y bloqueos pieza por pieza.

## Teclas

Ventana del juego:

| Tecla | Accion |
|---|---|
| Clic | 1er clic origen, 2do clic destino |
| `J` | Ejecutar la jugada |
| `L` | Limpiar origen y destino |
| `P` | Entrenar el clasificador con la posicion inicial |
| `H` | Calibrar la altura de los stickers |
| `V` | Informe de validacion en muestra |
| `S` | Sincronizar el tablero logico con la camara |
| `X` | Parada de emergencia |
| `Q` o `Esc` | Salir |

Heredadas de la vision:

| Tecla | Accion |
|---|---|
| `C` | Calibrar con las 4 esquinas |
| `E` | Capturar el tablero vacio |
| `O` | Girar la orientacion 90 grados |
| `M` | Modo jugada por teclado (ej. `E3 G5`) |
| `T` | Exportar `mapa_casillas.csv` |
| `D` | Diagnostico de deteccion |
| `U` | Aceptar la lectura actual como estado real |
| `R` | Reiniciar la calibracion |

Que hace `U`: el tablero ignora cambios masivos (mano o brazo) y espera 6 lecturas
estables. Si colocas o mueves varias piezas a mano de golpe, pulsa `U` con el brazo
retirado y sin manos en la imagen. No recalibra y no toca el tablero logico.

Letras de tipo: `P` peon, `N` caballo, `B` alfil, `R` torre, `Q` dama, `K` rey.
Letra de equipo: `R` tablita verde con sticker rojo, `N` sticker negro.

## Apagar

1. Pulsa `REPOSO SEGURO` (o `RETIRAR BRAZO` si vas a seguir).
2. Espera a que termine el movimiento.
3. Apaga la fuente de los servos.
4. Pulsa `Q` para cerrar.

## Problemas frecuentes

| Sintoma | Que hacer |
|---|---|
| "TAPADO" | Retira mano o brazo y espera, o pulsa `U` |
| A1 no queda abajo a la izquierda | Pulsa `O` hasta corregir |
| Todo desplazado tras mover la camara | `R`, recalibrar y `E` |
| "No hay pieza en X" | Revisa `D`; suele ser contraste o calibracion |
| El clasificador no acierta | Reentrena con buena luz y repite el intercambio A1/B1 |
| Una torre no se mueve aunque delante no haya nada | Pulsa `S` para reconstruir el tablero logico con la camara |
| La camara no confirma el movimiento | Revisa `U` y `D`; el tablero logico no avanza |
| Falta python-chess | `py -m pip install chess` |

## Datos versionados

Se versionan: `calibracion_tablero.json`, `calibracion_top.json`,
`fondo_vacio.png`, `poses_ensenadas.json` y `modelo_piezas.npz`.
Se ignoran: `__pycache__/`, `*.pyc`, `mapa_casillas.csv` y temporales.

## Limitaciones de esta fase

- Solo se mueve tu lado. No hay oponente, capturas, enroque ni promocion.
- El tablero logico arranca en la posicion inicial. Para otra posicion pulsa `S`
  y reconstruye desde la camara. `S` es un modo de prueba: las piezas de tu equipo
  usan el tipo reconocido y el resto de casillas ocupadas solo bloquean.
- El clasificador es un KNN sobre la imagen binarizada del sticker, no una red
  neuronal. Depende de la luz, del contraste y del paralaje.
- La deteccion de equipo por color puede fallar con otra luz o con tableros de
  casillas verdes o rojas. El umbral esta en `UMBRAL_EQUIPO` (0.08).
- Queda pendiente la Etapa 6 del brazo: reensenar con apertura minima de pinza,
  traslado mas alto, interpolacion lineal y posible paso a 32 casillas.
