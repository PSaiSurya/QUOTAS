#!/bin/bash
# setup.sh - Run once to compile the environment
set -e

echo "[+] 1. Pulling official OpenPLC v4 and injecting routing tools..."
cat << 'EOF' > Dockerfile.plc
FROM ghcr.io/autonomy-logic/openplc-runtime:latest
USER root
RUN apt-get update && apt-get install -y iproute2 iptables iputils-ping python3 python3-pip
EOF
docker build -t custom-plc -f Dockerfile.plc .

echo "[+] 2. Injecting Network Routing Tools into Quantum VPN Gateways..."
cat << 'EOF' > Dockerfile.vpn
FROM openquantumsafe/openvpn:latest
USER root
RUN apt-get update && apt-get install -y iproute2 iptables iputils-ping
EOF
docker build -t custom-vpn -f Dockerfile.vpn .

echo "[+] 3. Building HMI Telemetry Engine..."
cat << 'EOF' > Dockerfile.hmi
FROM python:3.11-slim
RUN apt-get update && apt-get install -y iproute2 iptables iputils-ping netcat-openbsd

# [FIX]: Injecting asyncua for stateful OPC-UA benchmarking
RUN pip install --no-cache-dir asyncua
EOF
docker build -t custom-hmi -f Dockerfile.hmi .

echo "[+] Setup complete! OpenPLC v4 is perfectly integrated."
