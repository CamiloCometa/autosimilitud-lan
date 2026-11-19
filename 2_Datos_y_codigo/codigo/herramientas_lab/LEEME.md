# Herramientas para el día del laboratorio

Copien esta carpeta a los nodos (USB) y denle permisos: `chmod +x *.sh`.

| Script | Dónde | Para qué |
|---|---|---|
| `registrar_nodo.sh` | A, B y C | Guarda SO, interfaces, versiones y ping a C en `versiones_<host>.txt` |
| `rafagas.sh` | A y B (E2) | Ejecuta un cronograma aleatorio de ráfagas y lo guarda en `cronograma_<RUN>_<NODO>.csv` |

Grabar todo lo que se escribe en la terminal: `script -a registro_$(hostname).txt` (salir con `exit`).
Comandos completos y orden de trabajo: `docs/comandos_laboratorio.md`.

Al terminar, traigan a su computador y copien en `data/lab/` del programa: los `versiones_*.txt`,
`registro_*.txt`, `cronograma_*.csv`, `iperf_*.log`, `ventanas.txt` y la hoja de registro; y los
`.pcap` en `data/pcap/` (o conviértanlos con el botón «Convertir .pcap a CSV…», que los copia solo).
