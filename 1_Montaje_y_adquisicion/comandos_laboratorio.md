# Comandos del laboratorio (orden de trabajo)

Sustituyan `enp3s0` por la interfaz real de cada nodo (`ip -br link`).

## 0. Preparación (en cada nodo)
```bash
sudo apt install iperf3 tcpdump tshark
sudo nmcli con add type ethernet ifname enp3s0 con-name lab ipv4.method manual ipv4.addresses 192.168.50.1X/24   # X = 1 (A), 2 (B), 3 (C)
sudo nmcli con up lab
./registrar_nodo.sh                      # versiones, interfaces y ping → versiones_<host>.txt
script -a registro_$(hostname).txt       # graba la terminal (salir con: exit)
```

## 1. Servidores (en C, dos terminales, quedan abiertos todo el laboratorio)
```bash
iperf3 -s -p 5201
iperf3 -s -p 5202
```

## 2. E1 — tasa constante (repetir con E1_R2)
```bash
# C
date +%s.%N | tee -a ventanas.txt
sudo tcpdump -i enp3s0 -nn -s 128 -w E1_R1.pcap 'udp and dst host 192.168.50.13 and (dst port 5201 or dst port 5202)'
# A
iperf3 -c 192.168.50.13 -p 5201 -u -b 4M -l 1200 -t 600
# C, al terminar: Ctrl+C en tcpdump (anotar "packets dropped by kernel") y
date +%s.%N | tee -a ventanas.txt
```

## 3. E2 — ráfagas de A y B (repetir con E2_R2)
```bash
# C
sudo tcpdump -i enp3s0 -nn -s 128 -w E2_R1.pcap 'udp and dst host 192.168.50.13 and (dst port 5201 or dst port 5202)'
# A y B: dejar listo (espera el Enter)
./rafagas.sh E2_R1 A 5201        # en A
./rafagas.sh E2_R1 B 5202        # en B
# C: fijar t0 y dar la señal; A y B pulsan Enter a la vez
date +%s.%N | tee -a ventanas.txt
# C, pasados >= 600 s desde t0: Ctrl+C en tcpdump (anotar descartes)
```
Unir cronogramas: `cat cronograma_E2_R1_A.csv > schedule.csv; tail -n +2 cronograma_E2_R1_B.csv >> schedule.csv`

## 4. Exportar a CSV (en C o en su computador)
```bash
tshark -r E1_R1.pcap -Y 'ip.dst == 192.168.50.13 && (udp.dstport == 5201 || udp.dstport == 5202)' \
  -T fields -E header=y -E separator=, \
  -e frame.time_epoch -e frame.len -e ip.src -e udp.dstport > E1_R1.csv
```
En Windows, usen el botón «Convertir .pcap a CSV…» del programa (evita el problema de codificación de PowerShell).
