// main.js - Frontend logic for CN-Telnet-Web with Multichat Integration
document.addEventListener('DOMContentLoaded', function() {
    const socket = io();  // SocketIO client connection

    // Telnet Elements
    const hostInput = document.getElementById('host');
    const portInput = document.getElementById('port');
    const connectBtn = document.getElementById('connectBtn');
    const disconnectBtn = document.getElementById('disconnectBtn');
    const commandInput = document.getElementById('command');
    const execBtn = document.getElementById('execBtn');
    const uploadFile = document.getElementById('uploadFile');
    const uploadBtn = document.getElementById('uploadBtn');
    const downloadFile = document.getElementById('downloadFile');
    const downloadBtn = document.getElementById('downloadBtn');
    const scanHost = document.getElementById('scanHost');
    const startPort = document.getElementById('startPort');
    const endPort = document.getElementById('endPort');
    const scanBtn = document.getElementById('scanBtn');
    const statusDiv = document.getElementById('status');
    const terminalDiv = document.getElementById('terminal');
    const portChartCanvas = document.getElementById('portChart');

    // Chat Elements
// Chat Elements & State
const usernameInput = document.getElementById('username');
const roomInput = document.getElementById('room');
const joinBtn = document.getElementById('joinBtn');
const leaveBtn = document.getElementById('leaveBtn');
const msgInput = document.getElementById('msgInput');
const sendBtn = document.getElementById('sendBtn');
const messagesDiv = document.getElementById('messages');
let currentRoom = null;
let currentUsername = usernameInput.value || 'Anonymous';  // Lock early
let isJoined = false;  // NEW: Track join state to prevent duplicates

// SocketIO Event Listeners (Multichat) - FIXED: No duplicates
socket.on('connect', function() {
    console.log('SocketIO Connected');
    addMessage('system', 'Connected to chat server');  // Only once
});

socket.on('server_message', function(data) {
    // Only add if it's a join/leave (personal) - avoids broadcast doubles
    if (data.message.includes('Joined') || data.message.includes('Left')) {
        addMessage('system', data.message);
    }
});

socket.on('chat_message', function(data) {
    addMessage(data.user || 'Anonymous', data.msg, new Date(data.timestamp * 1000));
});

// Port Scan SocketIO Events (unchanged)
socket.on('scan_update', function(data) {
    updateTerminal(`Scanning ${data.host}:${data.port} - ${data.status} (${data.service}) - Progress: ${data.progress}`);
});

socket.on('scan_complete', function(data) {
    updateTerminal(`Scan complete: ${data.open_count} open ports on ${data.host}`);
    renderPortChart(data.open_ports);
});

// Join Room - FIXED: Check state, single log
joinBtn.addEventListener('click', function() {
    if (isJoined) return;  // Prevent re-join
    currentUsername = usernameInput.value.trim() || 'Anonymous';  // Re-capture, trim
    currentRoom = roomInput.value.trim() || 'default';
    if (!currentRoom) return;
    
    socket.emit('join', { room: currentRoom, username: currentUsername });
    isJoined = true;  // Set flag
    joinBtn.disabled = true;
    leaveBtn.disabled = false;
    sendBtn.disabled = false;
    msgInput.disabled = false;
    addMessage('system', `Joined room: ${currentRoom}`);  // Single frontend log
});

// Leave Room - FIXED: Reset state
leaveBtn.addEventListener('click', function() {
    if (!currentRoom || !isJoined) return;
    socket.emit('leave', { room: currentRoom });
    isJoined = false;
    currentRoom = null;
    joinBtn.disabled = false;
    leaveBtn.disabled = true;
    sendBtn.disabled = true;
    msgInput.disabled = true;
    addMessage('system', 'Left room');  // Single log
});

// Send Message - FIXED: Trim & check
sendBtn.addEventListener('click', sendChatMessage);
msgInput.addEventListener('keypress', function(e) {
    if (e.key === 'Enter') sendChatMessage();
});

function sendChatMessage() {
    if (!isJoined || !currentRoom || !msgInput.value.trim()) return;
    const msg = msgInput.value.trim();
    socket.emit('chat_message', {
        room: currentRoom,
        message: msg,
        username: currentUsername
    });
    msgInput.value = '';
}

// ... (rest of file unchanged: addMessage, Telnet functions, etc.)

    function addMessage(user, msg, timestamp = new Date()) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'mb-2';
        msgDiv.innerHTML = `<strong>${user} (${timestamp.toLocaleTimeString()}):</strong> ${msg}`;
        messagesDiv.appendChild(msgDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    // Telnet API Calls (using Fetch)
    let isConnected = false;

    connectBtn.addEventListener('click', connectTelnet);
    disconnectBtn.addEventListener('click', disconnectTelnet);
    execBtn.addEventListener('click', execCommand);
    uploadBtn.addEventListener('click', uploadFileFunc);
    downloadBtn.addEventListener('click', downloadFileFunc);
    scanBtn.addEventListener('click', startScan);

    async function connectTelnet() {
        const host = hostInput.value;
        const port = portInput.value;
        try {
            const res = await fetch('/api/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ host, port })
            });
            const data = await res.json();
            if (data.status === 'Connected') {
                isConnected = true;
                connectBtn.disabled = true;
                disconnectBtn.disabled = false;
                execBtn.disabled = false;
                uploadBtn.disabled = false;
                downloadBtn.disabled = false;
                statusDiv.textContent = `Connected to ${host}:${port}`;
                updateTerminal('Connected!');
                // Auto-join chat room on connect for collaboration
                joinBtn.click();
            } else {
                statusDiv.textContent = `Error: ${data.error}`;
            }
        } catch (err) {
            statusDiv.textContent = `Connection failed: ${err}`;
        }
    }

    async function disconnectTelnet() {
        try {
            await fetch('/api/disconnect', { method: 'POST' });
            isConnected = false;
            connectBtn.disabled = false;
            disconnectBtn.disabled = true;
            execBtn.disabled = true;
            uploadBtn.disabled = true;
            downloadBtn.disabled = true;
            statusDiv.textContent = 'Disconnected';
            updateTerminal('Disconnected.');
            // Leave room on disconnect
            leaveBtn.click();
        } catch (err) {
            statusDiv.textContent = `Disconnect failed: ${err}`;
        }
    }

    async function execCommand() {
        if (!isConnected) return;
        const cmd = commandInput.value;
        try {
            const res = await fetch('/api/exec', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: cmd })
            });
            const data = await res.json();
            if (data.status === 'Executed') {
                updateTerminal(`> ${cmd}\n${data.stdout}\n${data.stderr ? 'ERR: ' + data.stderr : ''}`);
                // Broadcast to chat room for multi-user sharing
                if (currentRoom) {
                    socket.emit('chat_message', {
                        room: currentRoom,
                        message: `[Telnet Output] Command: ${cmd} | Output: ${data.stdout.substring(0, 200)}...`,
                        username: currentUsername
                    });
                }
                commandInput.value = '';
            } else {
                updateTerminal(`Exec error: ${data.error}`);
            }
        } catch (err) {
            updateTerminal(`Exec failed: ${err}`);
        }
    }

    async function uploadFileFunc() {
        if (!isConnected || !uploadFile.files[0]) return;
        const formData = new FormData();
        formData.append('file', uploadFile.files[0]);
        try {
            const res = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await res.json();
            updateTerminal(`Upload: ${data.status} - ${data.bytes_sent} bytes`);
            // Broadcast to chat
            if (currentRoom) sendChatMessage(`Uploaded file: ${uploadFile.files[0].name}`);
        } catch (err) {
            updateTerminal(`Upload failed: ${err}`);
        }
    }

    async function downloadFileFunc() {
        if (!isConnected) return;
        const filename = downloadFile.value;
        try {
            const res = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename })
            });
            if (res.ok) {
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                a.click();
                updateTerminal(`Downloaded: ${filename}`);
            } else {
                const data = await res.json();
                updateTerminal(`Download error: ${data.error}`);
            }
        } catch (err) {
            updateTerminal(`Download failed: ${err}`);
        }
    }

    async function startScan() {
        const host = scanHost.value;
        const start = startPort.value;
        const end = endPort.value;
        try {
            const res = await fetch('/api/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ host, start_port: start, end_port: end })
            });
            const data = await res.json();
            updateTerminal(`Scan started: ${data.host} (${data.start_port}-${data.end_port})`);
        } catch (err) {
            updateTerminal(`Scan failed: ${err}`);
        }
    }

    function updateTerminal(text) {
        terminalDiv.textContent += text + '\n';
        terminalDiv.scrollTop = terminalDiv.scrollHeight;
    }

    function renderPortChart(openPorts) {
        const ctx = portChartCanvas.getContext('2d');
        if (portChart) portChart.destroy();
        portChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: openPorts.map(p => `Port ${p.port}`),
                datasets: [{ label: 'Open Ports', data: openPorts.map(() => 1), backgroundColor: 'rgba(75, 192, 192, 0.2)' }]
            },
            options: { scales: { y: { beginAtZero: true, max: 1 } } }
        });
    }

    // Status Check
    async function checkStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            isConnected = data.connected;
            // Update buttons based on status
            connectBtn.disabled = isConnected;
            disconnectBtn.disabled = !isConnected;
            execBtn.disabled = !isConnected;
            uploadBtn.disabled = !isConnected;
            downloadBtn.disabled = !isConnected;
        } catch (err) {
            console.error('Status check failed:', err);
        }
    }
    checkStatus();  // Initial check
    setInterval(checkStatus, 5000);  // Poll every 5s
});