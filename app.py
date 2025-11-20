# app.py - Flask + Socket.IO backend for CN-Telnet-Web with NVT
import web_client
import os
import time  # Added for chat timestamps
from flask import Flask, request, jsonify, render_template, send_from_directory, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
import threading

import web_client  # uses NVTSession internally

# --------------------------
# Flask / Socket.IO setup
# --------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "temp_uploads")
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = "cn-telnet-web-secret"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")


# --------------------------
# Basic pages
# --------------------------

@app.route("/")
def index():
    """
    Main UI page.
    Expect a template 'index.html' that calls the REST APIs / Socket.IO events.
    """
    # If you don't have templates, you can return a simple message instead:
    # return "CN-Telnet-Web NVT backend is running"
    return render_template("index.html")


# --------------------------
# Telnet / NVT REST API
# --------------------------

@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.get_json(force=True)
    host = data.get("host")
    port = data.get("port")

    if not host or not port:
        return jsonify({"status": "Error", "error": "host and port are required"}), 400

    result = web_client.connect(host, port)
    return jsonify(result)


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    result = web_client.disconnect()
    return jsonify(result)


@app.route("/api/status", methods=["GET"])
def api_status():
    result = web_client.get_connection_status()
    return jsonify(result)


@app.route("/api/send", methods=["POST"])
def api_send_message():
    data = request.get_json(force=True)
    msg = data.get("message", "")

    if not msg:
        return jsonify({"status": "Error", "error": "message is required"}), 400

    result = web_client.send_message(msg)
    return jsonify(result)


@app.route("/api/exec", methods=["POST"])
def api_exec_command():
    data = request.get_json(force=True)
    cmd = data.get("command", "")

    if not cmd:
        return jsonify({"status": "Error", "error": "command is required"}), 400

    result = web_client.exec_command(cmd)
    return jsonify(result)


@app.route("/api/upload", methods=["POST"])
def api_upload_file():
    """
    HTTP file upload -> send to telnet server over NVT (binary for file body).
    """
    if "file" not in request.files:
        return jsonify({"status": "Error", "error": "No file part in request"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"status": "Error", "error": "No selected file"}), 400

    filename = secure_filename(file.filename)
    local_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(local_path)

    try:
        result = web_client.upload_file(local_path)
    finally:
        # Clean up temp file
        if os.path.exists(local_path):
            os.remove(local_path)

    return jsonify(result)


@app.route("/api/download", methods=["POST"])
def api_download_file():
    """
    Request file from remote telnet server and send it back to browser.
    """
    data = request.get_json(force=True)
    filename = data.get("filename", "")

    if not filename:
        return jsonify({"status": "Error", "error": "filename is required"}), 400

    result = web_client.download_file(filename)

    if result.get("status") != "Downloaded":
        return jsonify(result), 400

    local_path = result.get("path")
    if not local_path or not os.path.exists(local_path):
        return jsonify({"status": "Error", "error": "Downloaded file not found on server"}), 500

    # send_file will stream it to the browser
    return send_file(local_path, as_attachment=True, download_name=os.path.basename(local_path))


# --------------------------
# Port scanner API + Socket.IO
# --------------------------

def _scan_task(host, start_port, end_port):
    """
    Background worker for port scanning.
    Emits scan_update events from web_client.scan_ports via socketio instance.
    """
    try:
        result = web_client.scan_ports(host, start_port, end_port, sio=socketio)
    except Exception as e:
        socketio.emit("scan_complete", {
            "status": "Error",
            "error": str(e),
            "host": host
        }, namespace="/")
        return

    socketio.emit("scan_complete", result, namespace="/")


@app.route("/api/scan", methods=["POST"])
def api_scan_ports():
    """
    Start a port scan as an HTTP-triggered background task.
    Frontend can listen to 'scan_update' + 'scan_complete' Socket.IO events.
    """
    data = request.get_json(force=True)
    host = data.get("host")
    start_port = int(data.get("start_port", 1))
    end_port = int(data.get("end_port", 100))

    if not host:
        return jsonify({"status": "Error", "error": "host is required"}), 400

    thread = threading.Thread(
        target=_scan_task,
        args=(host, start_port, end_port),
        daemon=True
    )
    thread.start()

    return jsonify({
        "status": "Started",
        "host": host,
        "start_port": start_port,
        "end_port": end_port
    })


# Optional: Socket.IO event to start scan directly from WS
@socketio.on("start_scan")
def socket_start_scan(data):
    host = data.get("host")
    start_port = int(data.get("start_port", 1))
    end_port = int(data.get("end_port", 100))

    if not host:
        emit("scan_complete", {"status": "Error", "error": "host is required"})
        return

    thread = threading.Thread(
        target=_scan_task,
        args=(host, start_port, end_port),
        daemon=True
    )
    thread.start()

    emit("scan_started", {
        "status": "Started",
        "host": host,
        "start_port": start_port,
        "end_port": end_port
    })


# --------------------------
# Chat (Socket.IO) - FIXED: Structured emit for user/msg
# --------------------------

@socketio.on("connect")
def handle_connect():
    print("[Socket.IO] Client connected")
    emit("server_message", {"message": "Connected to CN-Telnet-Web server"})


@socketio.on("disconnect")
def handle_disconnect():
    print("[Socket.IO] Client disconnected")


@socketio.on("join")
def on_join(data):
    room = data.get("room", "default")
    username = data.get("username", "Anonymous")  # Capture for logs
    join_room(room)
    # FIXED: Emit ONLY to this user (request.sid) - no broadcast
    emit("{username}", {"message": f"Joined room {room}"}, room=request.sid)
   # print(f"[Chat] {username} joined {room}")  # Console only

@socketio.on("leave")
def on_leave(data):
    room = data.get("room", "default")
    leave_room(room)
    emit("server_message", {"message": f"Left room {room}"}, room=request.sid)
    print(f"[Chat] User left {room}")

@socketio.on("chat_message")
def handle_chat_message(data):
    """
    Simple broadcast chat with structured data.
    """
    room = data.get("room", "default")
    msg = data.get("message", "").strip()  # Strip to avoid empty sends
    username = data.get("username", "Anonymous")
    
    if not msg:  # Ignore empty messages
        return
    
    # Emit structured: separate user, msg, timestamp
    emit("chat_message", {
        "user": username,
        "msg": msg,
        "room": room,
        "timestamp": time.time()
    }, room=room)
    print(f"[Chat] Room {room}: {username}: {msg}")  # Console output for debugging


# --------------------------
# Static download of local files (if needed)
# --------------------------

@app.route("/downloads/<path:filename>")
def serve_download(filename):
    """
    Serve files from local downloads/ directory (optional).
    """
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)


# --------------------------
# Main entrypoint
# --------------------------

if __name__ == "__main__":
    # Use socketio.run instead of app.run to support WebSocket
    # host/port can be changed as needed
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)