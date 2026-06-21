#!/bin/bash
# scripts/gen_certs.sh
set -e

# Default to ML-DSA-65 (formerly Dilithium3) if no argument is passed
SIG_ALGO=${1:-mldsa65}

echo "[+] Generating PKI using Signature Algorithm: $SIG_ALGO"
mkdir -p ./certs
rm -f ./certs/*

# Explicitly load both the OQS and Default providers to support ML-DSA and RSA
docker run --rm -v "$(pwd)/certs:/certs" openquantumsafe/openvpn \
    openssl req -provider oqsprovider -provider default -x509 -new -newkey $SIG_ALGO -keyout /certs/ca.key -out /certs/ca.crt -nodes -subj "/CN=OQS-OT-CA/"

docker run --rm -v "$(pwd)/certs:/certs" openquantumsafe/openvpn \
    openssl req -provider oqsprovider -provider default -new -newkey $SIG_ALGO -keyout /certs/server.key -out /certs/server.csr -nodes -subj "/CN=Plant-Gateway/"

docker run --rm -v "$(pwd)/certs:/certs" openquantumsafe/openvpn \
    openssl x509 -provider oqsprovider -provider default -req -in /certs/server.csr -CA /certs/ca.crt -CAkey /certs/ca.key -CAcreateserial -out /certs/server.crt

docker run --rm -v "$(pwd)/certs:/certs" openquantumsafe/openvpn \
    openssl req -provider oqsprovider -provider default -new -newkey $SIG_ALGO -keyout /certs/client.key -out /certs/client.csr -nodes -subj "/CN=Corp-Gateway/"

docker run --rm -v "$(pwd)/certs:/certs" openquantumsafe/openvpn \
    openssl x509 -provider oqsprovider -provider default -req -in /certs/client.csr -CA /certs/ca.crt -CAkey /certs/ca.key -CAcreateserial -out /certs/client.crt

if [ ! -f "./certs/ca.crt" ]; then
    echo "[-] ERROR: Certificates failed to generate for $SIG_ALGO. Aborting."
    exit 1
fi
