#!/bin/bash
# ------------------------------------------------------------------
# Cronograma de ráfagas para E2 (ejecutar en A y en B al mismo tiempo)
#   en A:  ./rafagas.sh E2_R1 A 5201
#   en B:  ./rafagas.sh E2_R1 B 5202
# Ráfagas y pausas de 1 a 20 s (sorteadas en cada nodo), silencio inicial
# de 2 a 6 s y silencio final de >= 8 s dentro de los 600 s.
# Guarda cronograma_<RUN>_<NODO>.csv (run,source,start_s,end_s) en
# segundos desde que se pulsa Enter (= señal de t0 dada desde C).
# ------------------------------------------------------------------
RUN=$1; NODO=$2; PORT=$3; T=${4:-600}; SERVER=192.168.50.13
if [ -z "$PORT" ]; then echo "Uso: $0 <E2_R1|E2_R2> <A|B> <5201|5202>"; exit 1; fi
OUT=cronograma_${RUN}_${NODO}.csv
LOG=iperf_${RUN}_${NODO}.log
echo "run,source,start_s,end_s" > "$OUT"
read -p "Pulse Enter en la señal de inicio (t0)... "
START=$(date +%s.%N)
echo "inicio local: $START" > "$LOG"
t=$(( RANDOM % 5 + 2 ))
while :; do
  dur=$(( RANDOM % 20 + 1 ))
  [ $(( t + dur )) -gt $(( T - 8 )) ] && break
  w=$(awk -v s="$START" -v t="$t" -v n="$(date +%s.%N)" 'BEGIN{print s+t-n}')
  awk -v w="$w" 'BEGIN{exit !(w>0)}' && sleep "$w"
  echo "[$t s] ráfaga de $dur s"
  iperf3 -c "$SERVER" -p "$PORT" -u -b 4M -l 1200 -t "$dur" >> "$LOG" 2>&1
  echo "$RUN,$NODO,$t,$(( t + dur ))" >> "$OUT"
  t=$(( t + dur + RANDOM % 20 + 1 ))
done
echo "Cronograma guardado en $OUT (log de iperf3 en $LOG)"
