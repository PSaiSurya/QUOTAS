# hmi_multi_client.py 
import socket
import time
import sys
import asyncio
from asyncua import Client

def wait_for_ready(target_ip, port, timeout_sec=120):
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0) 
            s.connect((target_ip, port))
            s.close()
            time.sleep(2)
            return True
        except Exception:
            time.sleep(1)
    return False


def benchmark_modbus(target_ip, samples):
    if not wait_for_ready(target_ip, 502): return []
    latencies = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Disable Nagle's Algorithm for pure cryptographic latency
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        s.settimeout(15.0)
        s.connect((target_ip, 502))
        
        for i in range(samples):
            # Transaction ID increments safely
            tx_id = i.to_bytes(2, byteorder='big')
            packet = tx_id + b'\x00\x00\x00\x06\x01\x03\x00\x00\x00\x05'
            
            start = time.perf_counter()
            s.sendall(packet)
        
            #Strict MBAP Parsing
            # 1. Read exactly the first 6 bytes of the MBAP Header
            mbap_header = recv_exact(s, 6)
            
            # 2. Extract the 'Length' field (Bytes 4 and 5)
            # This tells us exactly how many bytes remain in this specific transaction
            remaining_length = int.from_bytes(mbap_header[4:6], byteorder='big')
            
            # 3. Read the exact remaining bytes, forcing the socket to wait for the network
            recv_exact(s, remaining_length)
            
            latencies.append((time.perf_counter() - start) * 1000)
            time.sleep(0.2)
        s.close()
    except Exception as e:
        print(f"DEBUG_MODBUS_ERROR: {e}", file=sys.stdout)
        pass
    return latencies


def recv_exact(sock, length):
    """Forces the socket to pull exactly N bytes, bypassing OS buffer tricks"""
    data = b''
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk: raise Exception("PACKET_LOST_OR_TCP_DROP")
        data += chunk
    return data

def benchmark_s7(target_ip, samples):
    if not wait_for_ready(target_ip, 102): return []
    latencies = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Disable Nagle's algorithm to prevent OS packet clumping
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(15.0) 
        s.connect((target_ip, 102))
        
        # 1. COTP Handshake
        s.sendall(b'\x03\x00\x00\x16\x11\xe0\x00\x00\x00\x01\x00\xc1\x02\x01\x00\xc2\x02\x01\x02\xc0\x01\x0a')
        # Expect exactly 22 bytes back. Flush the stream.
        recv_exact(s, 22)
        
        # 2. S7 Setup
        s.sendall(b'\x03\x00\x00\x19\x02\xf0\x80\x32\x01\x00\x00\x00\x00\x00\x08\x00\x00\xf0\x00\x00\x01\x00\x01\x03\xc0')
        # Expect exactly 27 bytes back. Flush the stream.
        recv_exact(s, 27)
        
        # 3. S7 Read Data (Targeting DB4 / %MW)
        s7_read_packet = b'\x03\x00\x00\x1f\x02\xf0\x80\x32\x01\x00\x00\x00\x00\x00\x0e\x00\x00\x04\x01\x12\x0a\x10\x02\x00\x01\x00\x04\x84\x00\x00\x00'
        
        for i in range(samples):
            try:
                start = time.perf_counter()
                s.sendall(s7_read_packet)
                
                # Strict TPKT Parsing
                # Read exactly the 4-byte header
                tpkt = recv_exact(s, 4)
                # Parse bytes 3 and 4 to find out exactly how large the PLC's response is
                pdu_length = int.from_bytes(tpkt[2:4], byteorder='big')
                # Read the rest of the exact payload, forcing it to wait for the network
                recv_exact(s, pdu_length - 4)
                
                latencies.append((time.perf_counter() - start) * 1000)
            except Exception as e:
                print(f"DEBUG_S7_READ_ERROR_AT_{i}: {e}", file=sys.stdout)
                break 
            time.sleep(0.2) 
        s.close()
    except Exception as e:
        print(f"DEBUG_S7_CONN_ERROR: {e}", file=sys.stdout)
        return [] 
    return latencies


async def _run_opcua_benchmark(target_ip, samples):
    if not wait_for_ready(target_ip, 4840): return []
    latencies = []
    
    client = Client(f"opc.tcp://{target_ip}:4840") 
    try:
        await client.connect()
        
        sock = client.uaclient.protocol.transport.get_extra_info('socket')
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            
        node = client.get_node("ns=0;i=2259") 
        for _ in range(samples):
            start = time.perf_counter()
            await node.read_value()
            latencies.append((time.perf_counter() - start) * 1000)
            await asyncio.sleep(0.2)
    except Exception:
        pass
    finally:
        try:
            await client.disconnect()
        except:
            pass
    return latencies

def benchmark_opcua(target_ip, samples):
    return asyncio.run(_run_opcua_benchmark(target_ip, samples))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
        
    target_host = sys.argv[1]
    chosen_protocol = sys.argv[2].lower()
    total_samples = 100
    
    if chosen_protocol == "modbus":
        results = benchmark_modbus(target_host, total_samples)
    elif chosen_protocol == "s7":
        results = benchmark_s7(target_host, total_samples)
    elif chosen_protocol == "opcua":
        results = benchmark_opcua(target_host, total_samples)
    else:
        results = []

    if results:
        print(f"METRICS_SUMMARY:SUCCESS,{sum(results)/len(results):.2f},{len(results)}")
    else:
        print("METRICS_SUMMARY:FAILED,0.00,0")
