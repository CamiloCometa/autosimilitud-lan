#!/bin/bash
# Registra sistema, versiones e interfaces del nodo en versiones_<host>.txt
OUT=versiones_$(hostname).txt
{
  echo "== Nodo: $(hostname)   fecha: $(date '+%F %T %z')   epoch: $(date +%s.%N)"
  lsb_release -d 2>/dev/null || grep PRETTY_NAME /etc/os-release
  echo "kernel: $(uname -r)"
  echo "== Interfaces"; ip -br addr
  echo "== Versiones"
  iperf3 --version 2>&1 | head -1
  tcpdump --version 2>&1 | head -1
  tshark --version 2>/dev/null | head -1
  echo "== Conectividad hacia C"; ping -c 5 192.168.50.13 2>&1 | tail -2
} | tee "$OUT"
echo "Guardado en $OUT"
