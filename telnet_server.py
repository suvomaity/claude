import os
import socket
import sys
import signal
import subprocess
import threading
import shlex  # For secure command splitting
from nvt import NVTSession, encode_nvt, decode_nvt

ENCODING = "utf-8"
CHUNK_SIZE = 4096
MAX_RETRY = 10

def main():
    """Main method"""
    if len(sys.argv) < 2:
        print("Usage: python main.py server <port>")
        print("Example: python main.py server 8080")
        sys.exit(-1)

    if sys.argv[1] == "server":
        print("[NVT Server] Starting in server mode...")
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
        server_mode(port)
    else:
        print("Unknown mode. Use 'server'")
        sys.exit(-1)

def sigint_handler(sig, frame):
    """Capture SIGINT signal and exit gracefully"""
    print("\n[NVT Server] Shutting down...")
    sys.exit(0)

def server_mode(port: int):
    """
    Enter server mode with NVT protocol support.
    Listen on the given port and handle multiple clients.
    """
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("0.0.0.0", port))
        server_socket.listen(5)
        
        print(f"[NVT Server] Listening on 0.0.0.0:{port}")
        print(f"[NVT Server] Waiting for connections...")
        print(f"[NVT Server] Press Ctrl+C to stop")
        
        while True:
            try:
                connection, info = server_socket.accept()
                client_thread = threading.Thread(
                    target=client_handler,
                    args=(connection, info),
                    daemon=True
                )
                client_thread.start()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[NVT Server] Accept error: {e}")
        
        server_socket.close()
        print("[NVT Server] Stopped")
        
    except Exception as exc:
        print(f"[NVT Server] Fatal error: {exc}")
        sys.exit(-1)

def client_handler(given_socket: socket.socket, info: tuple):
    """
    Handle each client connection with NVT protocol support.
    """
    client_id = f"{info[0]}:{info[1]}"
    print(f"[NVT Server] Client {client_id} connected")
    
    # Initialize NVT session for this client
    nvt_session = NVTSession()
    
    try:
        # Send initial NVT option negotiations
        # We WILL suppress go-ahead
        suppress_ga = nvt_session.negotiate_option(b'\x03', enable=True)
        given_socket.send(suppress_ga)
        
        # Main command loop
        result = True
        while result:
            result = recv_and_process(given_socket, nvt_session, client_id)
    
    except Exception as exc:
        print(f"[NVT Server] Client {client_id} error: {exc}")
    
    finally:
        try:
            given_socket.close()
        except:
            pass
        print(f"[NVT Server] Client {client_id} disconnected")

def recv_nvt_data(given_socket: socket.socket, nvt_session: NVTSession, timeout=5.0) -> str:
    """
    Receive and decode ONE NVT frame from socket.
    We expect the client to send commands/size padded to CHUNK_SIZE bytes,
    so a single recv(CHUNK_SIZE) is one logical message.
    """
    given_socket.settimeout(timeout)
    
    try:
        data = given_socket.recv(CHUNK_SIZE)
        if not data:
            return ""
    except socket.timeout:
        return ""
    except Exception as e:
        print(f"[NVT Server] Recv error: {e}")
        return ""
    
    # Decode using NVT
    text, responses = nvt_session.receive_data(data)
    
    # Send any auto-responses (option negotiation etc.)
    for response in responses:
        try:
            given_socket.send(response)
        except:
            pass
    
    return text.strip()

def send_nvt_data(given_socket: socket.socket, nvt_session: NVTSession, text: str, padded=False):
    """
    Send NVT-encoded data to client.
    
    Args:
        given_socket: Client socket
        nvt_session: NVT session for encoding
        text: Text to send
        padded: Whether to pad to CHUNK_SIZE
    """
    if padded:
        encoded = nvt_session.send_text(text, CHUNK_SIZE)
    else:
        encoded = nvt_session.send_text(text)
    
    given_socket.send(encoded)

def recv_and_process(given_socket: socket.socket, nvt_session: NVTSession, client_id: str) -> bool:
    """
    Receive and process commands from client using NVT protocol.
    
    Returns:
        True to continue, False to disconnect
    """
    try:
        # Receive command
        command = recv_nvt_data(given_socket, nvt_session)
        
        if not command:
            return True
        
        print(f"[NVT Server] {client_id} command: '{command[:50]}...'")
        
        # Parse command
        cmd_parts = command.split()
        if not cmd_parts:
            return True
        
        main_cmd = cmd_parts[0].lower()
        
        # Handle UPLOAD command
        if main_cmd == "upload":
            if len(cmd_parts) < 2:
                send_nvt_data(given_socket, nvt_session, "[Server] Error: No filename provided\n")
                return True
            
            filename = " ".join(cmd_parts[1:])
            print(f"[NVT Server] {client_id} uploading: {filename}")
            
            # Receive file size
            size_str = recv_nvt_data(given_socket, nvt_session, timeout=3.0)
            try:
                file_size = int(size_str)
            except ValueError:
                send_nvt_data(given_socket, nvt_session, "[Server] Error: Invalid file size\n")
                return True
            
            # Receive file data
            received_data = b''
            remaining = file_size
            
            while remaining > 0:
                chunk = given_socket.recv(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                received_data += chunk
                remaining -= len(chunk)
            
            # Save file
            save_path = os.path.join("uploads", filename)
            os.makedirs("uploads", exist_ok=True)
            
            with open(save_path, 'wb') as f:
                f.write(received_data)
            
            response = f"[Server] Received {len(received_data)} bytes and saved as '{filename}'\n"
            send_nvt_data(given_socket, nvt_session, response)
            print(f"[NVT Server] {client_id} upload complete: {len(received_data)} bytes")
            return True
        
        # Handle EXEC COMMAND
        elif main_cmd == "exec":
            if len(cmd_parts) < 2:
                send_nvt_data(given_socket, nvt_session, "[Server] Error: No command provided\n", padded=True)
                return True

            exec_cmd = " ".join(cmd_parts[1:])
            print(f"[NVT Server] {client_id} executing: {exec_cmd}")

            try:
                # OS-aware whitelist (Unix + Windows)
                if os.name == 'nt':  # Windows
                    allowed_cmds = ['dir', 'cd', 'type', 'echo', 'whoami', 'date', 'time', 'set']
                else:  # Unix/Linux/Mac
                    allowed_cmds = ['ls', 'pwd', 'cat', 'whoami', 'date', 'echo', 'ps', 'id', 'uname']
                
                # Common across OS
                allowed_cmds += ['echo', 'whoami']  # Overlap safe
                
                exec_parts = shlex.split(exec_cmd)
                if not exec_parts or exec_parts[0] not in allowed_cmds:
                    raise ValueError(f"Command '{exec_parts[0] if exec_parts else 'unknown'}' not allowed. Try: {', '.join(allowed_cmds[:5])}...")

                result = subprocess.run(
                    exec_parts,  # No shell=True for security
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    text=True
                )

                stdout = result.stdout if result.stdout else "(empty)"
                stderr = result.stderr if result.stderr else "(none)"

                response = f"[Server response]\nOutput:\n{stdout}\nError:\n{stderr}\n"

                send_nvt_data(given_socket, nvt_session, response, padded=True)

                print(f"[NVT Server] {client_id} exec complete: exit code {result.returncode}")

            except subprocess.TimeoutExpired:
                send_nvt_data(given_socket, nvt_session, "[Server] Error: Command timeout\n", padded=True)
            except Exception as e:
                send_nvt_data(given_socket, nvt_session, f"[Server] Error: {str(e)}\n", padded=True)

            return True

        # Handle DOWNLOAD command
        elif main_cmd == "download":
            if len(cmd_parts) < 2:
                send_nvt_data(given_socket, nvt_session, "[Server] Error: No filename provided\n")
                return True
            
            filename = " ".join(cmd_parts[1:])
            file_path = os.path.join("uploads", filename)

            print(f"[NVT Server] {client_id} downloading: {filename}")
            print(f"[NVT Server] File path: {os.path.abspath(file_path)}")
            
            if not os.path.exists(file_path):
                # Send size = 0 as plain ASCII line: "0\n"
                given_socket.sendall(b"0\n")
                print(f"[NVT Server] {client_id} requested missing file '{filename}'")
                return True
            
            # Send file size as plain ASCII line: "<size>\n"
            file_size = os.path.getsize(file_path)
            size_line = f"{file_size}\n".encode("ascii")
            given_socket.sendall(size_line)
            print(f"[NVT Server] {client_id} file size: {file_size} bytes")
            
            # Send file data as raw binary
            total_sent = 0
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    given_socket.sendall(chunk)
                    total_sent += len(chunk)
            
            print(f"[NVT Server] {client_id} download complete: {total_sent}/{file_size} bytes")
            return True

        
        # Handle QUIT command
        elif main_cmd == "quit":
            send_nvt_data(given_socket, nvt_session, "[Server] Goodbye!\n")
            print(f"[NVT Server] {client_id} requested disconnect")
            return False
        
        # Handle SEND MESSAGE command
        elif main_cmd == "send" and len(cmd_parts) > 1 and cmd_parts[1] == "message":
            print(f"[NVT Server] {client_id} sending message")
            
            # Receive the actual message
            message = recv_nvt_data(given_socket, nvt_session)
            print(f"[NVT Server] {client_id} message: '{message[:100]}...'")
            
            # Echo back
            response = f"[Server response] Got {len(message)} bytes of your message.\n"
            send_nvt_data(given_socket, nvt_session, response)
            return True
        
        # Unknown command
        else:
            response = f"[Server] Unknown command: {main_cmd}\n"
            response += "[Server] Available commands: send message, upload, download, exec, quit\n"
            send_nvt_data(given_socket, nvt_session, response)
            return True
    
    except Exception as exc:
        print(f"[NVT Server] Process error for {client_id}: {exc}")
        return False

if __name__ == "__main__":
    signal.signal(signal.SIGINT, sigint_handler)
    main()