/*
  BRAZO DE AJEDREZ - FIRMWARE CONTROLADO POR PC (robot.py)

  Comandos (texto, terminan en salto de linea, 9600 baudios):
    A                    Activar servos en la pose de reposo (el brazo debe estar YA en reposo)
    G b h c m g p        Ir a la pose: base hombro codo muneca gancho pinza (grados)
    H                    Volver al reposo
    X                    Parada: congela los servos donde esten
    P                    Imprime la posicion actual
    L                    Imprime sus limites y reposo (los lee el PC: la tabla vive SOLO aqui)
  Respuestas: "OK" al terminar, "ERR ..." si algo falla.

  Los servos llegan JUNTOS al destino y nunca superan su velocidad maxima (tickMs).
  Los limites mn/mx se aplican aqui tambien: aunque el PC se equivoque, no los excede.
*/
#include <Servo.h>

const byte NUM = 6;
const byte pines[NUM] = {5, 6, 7, 8, 9, 10};

const int mn[NUM]  = {3,   60,  3,   3,   3,   10};
const int mx[NUM]  = {170, 140, 177, 178, 175, 110};
const int ini[NUM] = {50,  90,  120, 178, 175, 25};

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

void activar(const int* p) {
  if (activo) { Serial.println(F("OK")); return; }
  for (byte i = 0; i < NUM; i++) {
    int a = constrain(p[i], mn[i], mx[i]);
    pos[i] = a;
    tgt[i] = a;
    servos[i].write(a);          // write ANTES de attach: sin salto
    servos[i].attach(pines[i]);
    delay(600);                  // uno por uno: evita picos de corriente
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
    intervalo[i] = delta[i] ? T / delta[i] : 0;   // todos terminan a la vez
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
    int v[NUM];
    int n = sscanf(s + 1, "%d %d %d %d %d %d", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]);
    activar(n == NUM ? v : ini);   // "A" solo = reposo; "A b h c m g p" = esa pose
  } else if (c == 'G'){
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
