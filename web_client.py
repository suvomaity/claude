import socket
import threading
import os
import time
import re
import json  # Added for ports.json
from nvt import NVTSession, encode_nvt, decode_nvt

CHUNK_SIZE = 4096

current_sock = None
nvt_session = None
lock = threading.Lock()


# ---------------------------------------------------------
# CONNECT
# ---------------------------------------------------------
def connect(host, port):
    global current_sock, nvt_session

    with lock:
        try:
            current_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            current_sock.settimeout(5)
            current_sock.connect((host, int(port)))

            nvt_session = NVTSession()

            print(f"[NVT] Connected to {host}:{port}")

            # Initial negotiation – suppress Go Ahead
            suppress_ga = nvt_session.negotiate_option(b'\x03')
            current_sock.send(suppress_ga)

            return {"status": "Connected", "host": host, "port": port}

        except Exception as e:
            current_sock = None
            nvt_session = None
            return {"status": "Error", "error": str(e)}


# ---------------------------------------------------------
# DISCONNECT
# ---------------------------------------------------------
def disconnect():
    global current_sock, nvt_session
    with lock:
        if current_sock:
            try:
                quit_msg = nvt_session.send_text("quit", CHUNK_SIZE)
                current_sock.send(quit_msg)
                time.sleep(0.05)
                current_sock.close()
            except:
                pass

            current_sock = None
            nvt_session = None
            print("[NVT] Disconnected")
            return {"status": "Disconnected"}

    return {"status": "Error", "error": "Not connected"}


# ---------------------------------------------------------
# RECV ONE NVT FRAME (safe way)
# ---------------------------------------------------------
def recv_frame():
    """Receive exactly one 4096-byte NVT frame."""
    try:
        frame = current_sock.recv(CHUNK_SIZE)
        if not frame:
            return ""
        text, _ = nvt_session.receive_data(frame)
        return text.strip()
    except Exception as e:
        print("[NVT] recv_frame error:", e)
        return ""


# ---------------------------------------------------------
# SEND MESSAGE
# ---------------------------------------------------------
def send_message(msg):
    global current_sock, nvt_session

    if not current_sock:
        return {"status": "Error", "error": "Not connected"}

    with lock:
        try:
            # Send command
            cmd = nvt_session.send_text("send message", CHUNK_SIZE)
            current_sock.send(cmd)

            # Send message body
            body = nvt_session.send_text(msg, CHUNK_SIZE)
            current_sock.send(body)

            # Receive ack
            response = recv_frame()

            return {
                "status": "Sent",
                "message": msg,
                "response": response,
            }

        except Exception as e:
            return {"status": "Error", "error": str(e)}


# ---------------------------------------------------------
# EXEC COMMAND
# ---------------------------------------------------------
def exec_command(cmd):
    """
    Execute a remote command using NVT protocol.
    """
    global current_sock, nvt_session
    if not current_sock:
        return {"status": "Error", "error": "Not connected"}
    
    with lock:
        try:
            # Send exec command using NVT encoding
            full_cmd = f"exec {cmd}\n"  # Added \n for clean send
            cmd_encoded = nvt_session.send_text(full_cmd, CHUNK_SIZE)
            current_sock.send(cmd_encoded)
            print(f"[NVT] Sent exec: '{cmd}'")
            
            # Receive output (single padded frame from server)
            output = recv_frame()
            print(f"[NVT] Raw output: {repr(output[:200])}...")  # Debug log
            
            # Parse output to extract stdout and stderr
            # Server response format: "[Server response]\nOutput:\n...\nError:\n..."
            stdout = stderr = ""
            if "Output:" in output and "Error:" in output:
                parts = output.split("Output:", 1)
                if len(parts) > 1:
                    output_part = parts[1].split("Error:", 1)
                    stdout = output_part[0].strip() if len(output_part) > 0 else ""
                    stderr = output_part[1].strip() if len(output_part) > 1 else ""
            else:
                stdout = output.strip()
            
            return {
                "status": "Executed",
                "command": cmd,
                "stdout": stdout,
                "stderr": stderr,
                "full_output": output,
                "exit_code": 0 if not stderr else 1
            }
        except Exception as e:
            print(f"[NVT] Exec error: {e}")
            return {"status": "Error", "error": str(e)}


# ---------------------------------------------------------
# UPLOAD FILE  (FIXED ACK)
# ---------------------------------------------------------
def upload_file(file_path):
    global current_sock, nvt_session

    if not current_sock:
        return {"status": "Error", "error": "Not connected"}

    filename = os.path.basename(file_path)
    if not os.path.exists(file_path):
        return {"status": "Error", "error": f"File does not exist: {file_path}"}

    with lock:
        try:
            # 1. send upload command
            cmd = f"upload {filename}"
            encoded = nvt_session.send_text(cmd, CHUNK_SIZE)
            current_sock.send(encoded)

            # 2. send size
            size = os.path.getsize(file_path)
            size_str = nvt_session.send_text(str(size), CHUNK_SIZE)
            current_sock.send(size_str)

            # 3. send file data
            sent_bytes = 0
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    current_sock.send(chunk)
                    sent_bytes += len(chunk)

            # 4. receive upload ACK (1 frame only)
            ack = recv_frame()
            print("[NVT] Upload ACK:", ack)

            return {
                "status": "Uploaded",
                "filename": filename,
                "size": size,
                "bytes_sent": sent_bytes,
                "server_ack": ack,
            }

        except Exception as e:
            return {"status": "Error", "error": str(e)}


# ---------------------------------------------------------
# DOWNLOAD FILE  (FULLY FIXED)
# ---------------------------------------------------------
def download_file(filename):
    global current_sock, nvt_session

    if not current_sock:
        return {"status": "Error", "error": "Not connected"}

    with lock:
        try:
            # 1. send download command
            cmd = f"download {filename}"
            encoded = nvt_session.send_text(cmd, CHUNK_SIZE)
            current_sock.send(encoded)

            # 2. read size frame (not raw data!)
            size_text = recv_frame()
            print("[NVT] SIZE TEXT:", size_text)

            # extract a number
            m = re.search(r"(\d+)", size_text)
            if not m:
                return {"status": "Error", "error": f"Invalid size: {size_text}"}

            size = int(m.group(1))
            print(f"[NVT] Expecting {size} bytes")

            # if file doesn't exist
            if size == 0:
                return {"status": "Error", "error": "File not found on server"}

            # 3. receive file binary
            downloaded = b""
            remaining = size
            current_sock.settimeout(10)

            while remaining > 0:
                chunk = current_sock.recv(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                downloaded += chunk
                remaining -= len(chunk)

            # 4. save file
            os.makedirs("downloads", exist_ok=True)
            save_path = os.path.join("downloads", filename)
            with open(save_path, "wb") as f:
                f.write(downloaded)

            return {
                "status": "Downloaded",
                "filename": filename,
                "path": save_path,
                "received": len(downloaded),
                "expected": size,
            }

        except Exception as e:
            return {"status": "Error", "error": str(e)}


# ---------------------------------------------------------
# PORT SCANNER
# ---------------------------------------------------------
def scan_ports(host, start_port=1, end_port=100, sio=None):
    open_ports = []
    try:
        with open('ports.json', 'r') as f:
            port_info = json.load(f)
    except FileNotFoundError:
        port_info = {}  # Fallback if JSON missing

    total_ports = end_port - start_port + 1
    scanned = 0

    for port in range(start_port, end_port + 1):
        status = "closed"
        service = port_info.get(str(port), {}).get('name', 'unknown')
        try:
            s = socket.socket()
            s.settimeout(0.3)
            if s.connect_ex((host, port)) == 0:
                open_ports.append({"port": port, "service": service, "comment": port_info.get(str(port), {}).get('comment', '')})
                status = "open"
            s.close()
        except:
            pass
        
        scanned += 1
        # Emit progress every 10 ports or at end
        if sio and (scanned % 10 == 0 or scanned == total_ports):
            sio.emit("scan_update", {
                "host": host,
                "port": port,
                "status": status,
                "service": service,
                "progress": f"{scanned}/{total_ports}"
            }, namespace="/")

    result = {
        "status": "Scanned",
        "host": host,
        "open_ports": open_ports,
        "total_scanned": total_ports,
        "open_count": len(open_ports)
    }
    if sio:
        sio.emit("scan_complete", result, namespace="/")
    return result


# ---------------------------------------------------------
# STATUS
# ---------------------------------------------------------
def get_connection_status():
    global current_sock, nvt_session
    if current_sock:
        return {"connected": True}
    return {"connected": False}