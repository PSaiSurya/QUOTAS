import os
import time
import subprocess
import re
import sys

class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        self.log = open("execution_log.txt", "a")
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()
    def flush(self): pass

sys.stdout = Logger()

CRYPTOGRAPHY_SUITES = {
    "CLASSICAL_BASELINE": {"sig": "rsa:3072", "kem": "X25519"},
    "NIST_LVL1_ML": {"sig": "mldsa44", "kem": "mlkem512"},
    "NIST_LVL3_ML": {"sig": "mldsa65", "kem": "mlkem768"},
    "NIST_LVL5_ML": {"sig": "mldsa87", "kem": "mlkem1024"},
    "NIST_LVL1_FALCON": {"sig": "falcon512", "kem": "mlkem512"},
    "NIST_LVL5_FALCON": {"sig": "falcon1024", "kem": "mlkem1024"}
}
 
PROTOCOLS = ["modbus", "s7", "opcua"]

# The target CPU constraints we will apply DYNAMICALLY after boot
PLC_HARDWARE_PROFILES = {
    "micro_rtu": "0.01",
    "legacy_rtu": "0.1",
    "mid_tier_plc": "0.5",
    "high_end_plc": "1.5"
}

ITERATIONS = 10
OUTPUT_CSV = "nist_pqc_ot_benchmarks.csv"

def patch_configs(kem_algo):
    for mode in ["server", "client"]:
        with open(f"config/openvpn-{mode}.tmpl", "r") as f:
            content = f.read()
        content = content.replace("__ALGO__", kem_algo)
        with open(f"config/openvpn-{mode}.conf", "w") as f:
            f.write(content)

def run_pipeline():
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, "w") as f:
            f.write("Cipher_Suite,Signature_Algo,KEM_Algo,PLC_Hardware_Profile,Protocol,Iteration,Status,Avg_Latency_ms,Successful_Polls\n")

    for suite_name, algos in CRYPTOGRAPHY_SUITES.items():
        sig_algo, kem_algo = algos["sig"], algos["kem"]
        
        print(f"\n" + "="*75)
        print(f" 🔐 SUITE: {suite_name} | SIG: {sig_algo.upper()} | KEM: {kem_algo.upper()}")
        print(f"="*75)
        
        subprocess.run(["./scripts/gen_certs.sh", sig_algo], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        patch_configs(kem_algo)

        for profile_name, cpu_limit in PLC_HARDWARE_PROFILES.items():
            print(f"\n  [+] 🏗️  Booting Infrastructure unconstrained for initialization...")
            
            subprocess.run(["docker", "compose", "down", "-v", "--remove-orphans"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Step 1: Boot at full power so the OS, Webserver, and VPN negotiate instantly
            os.environ["PLC_CPU_LIMIT"] = "1.5" 
            
            try:
                subprocess.run(["docker", "compose", "up", "-d", "--force-recreate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except subprocess.CalledProcessError:
                print("      [-] CRITICAL ERROR: Docker failed to boot. Halting benchmark.")
                sys.exit(1)
            
            # Fast settle time because the CPU is unrestrained
            time.sleep(15) 
            
            subprocess.run(["docker", "exec", "--privileged", "corporate-hmi", "ip", "route", "replace", "10.0.20.0/24", "via", "192.168.10.10"], stdout=subprocess.DEVNULL)
            subprocess.run(["docker", "exec", "--privileged", "plant-plc", "ip", "route", "replace", "192.168.10.0/24", "via", "10.0.20.10"], stdout=subprocess.DEVNULL)
            subprocess.run(["docker", "exec", "--privileged", "corp-vpn-gateway", "iptables", "-t", "nat", "-A", "POSTROUTING", "-j", "MASQUERADE"], stdout=subprocess.DEVNULL)
            subprocess.run(["docker", "exec", "--privileged", "plant-vpn-gateway", "iptables", "-t", "nat", "-A", "POSTROUTING", "-j", "MASQUERADE"], stdout=subprocess.DEVNULL)
            
            time.sleep(5) # Give the VPN 5 seconds to finish its unconstrained TLS handshake
            
            # ========================================================================
            # THE DYNAMIC THROTTLE
            # ========================================================================
            print(f"      [~] Handshake complete. Applying DYNAMIC THROTTLE: {profile_name.upper()} ({cpu_limit} CPU)...")
            subprocess.run(["docker", "update", "--cpus", str(cpu_limit), "plant-plc", "plant-vpn-gateway"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Wait 3 seconds for the Linux Kernel CFS scheduler to apply the new hard limits
            time.sleep(3)
            
            for proto in PROTOCOLS:
                print(f"\n      [*] 📡 PROTOCOL: {proto.upper()} (via {suite_name})")
                
                for i in range(1, ITERATIONS + 1):
                    proc = subprocess.run([
                        "docker", "compose", "exec", "-T", "corporate-hmi", "python3", "/app/hmi_multi_client.py", "10.0.20.50", proto
                    ], capture_output=True, text=True)
                    if proc.returncode != 0:
                        # [CRITICAL FIX]: This forces the script to dump the error if the client crashes
                        print(f"      [!] CLIENT_CRASH_LOG: {proc.stderr.strip()}", file=sys.stderr)
                    
                    match = re.search(r"METRICS_SUMMARY:(SUCCESS|FAILED),([\d.]+),(\d+)", proc.stdout)
                    if match:
                        status, latency, count = match.groups()
                        print(f"          -> Run {i:02d}/{ITERATIONS}: Status={status:<7} | Latency={float(latency):>6.2f}ms | Packets={count}")
                        with open(OUTPUT_CSV, "a") as f:
                            f.write(f"{suite_name},{sig_algo},{kem_algo},{profile_name},{proto},{i},{status},{latency},{count}\n")
                    else:
                        print(f"          -> Run {i:02d}/{ITERATIONS}: FAILED/TIMEOUT. Device dropped offline.")
                        with open(OUTPUT_CSV, "a") as f:
                            f.write(f"{suite_name},{sig_algo},{kem_algo},{profile_name},{proto},{i},ERROR,0.00,0\n")

    subprocess.run(["docker", "compose", "down", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"\n[+] Massive Matrix Processing run finalized. Metrics recorded directly into '{OUTPUT_CSV}'.")

if __name__ == "__main__":
    run_pipeline()