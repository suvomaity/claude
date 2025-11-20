# nvt.py - Network Virtual Terminal (NVT) Protocol Implementation
# Implements RFC 854 - Telnet Protocol Specification

"""
NVT (Network Virtual Terminal) Implementation for CN-Telnet-Web

NVT is a standard representation defined in RFC 854 that ensures
compatibility between different systems in telnet communication.

Key Features:
- 7-bit ASCII character set
- CR-LF line termination
- IAC (Interpret As Command) escape sequences
- Option negotiation support
- Command interpretation
"""

# NVT Special Characters (RFC 854)
NULL = b'\x00'      # No operation
LF = b'\x0a'        # Line Feed (newline)
CR = b'\x0d'        # Carriage Return
BEL = b'\x07'       # Bell
BS = b'\x08'        # Backspace
HT = b'\x09'        # Horizontal Tab
VT = b'\x0b'        # Vertical Tab
FF = b'\x0c'        # Form Feed

# Telnet Commands (RFC 854)
SE = b'\xf0'        # End of subnegotiation parameters
NOP = b'\xf1'       # No operation
DM = b'\xf2'        # Data Mark
BRK = b'\xf3'       # Break
IP = b'\xf4'        # Interrupt Process
AO = b'\xf5'        # Abort Output
AYT = b'\xf6'       # Are You There
EC = b'\xf7'        # Erase Character
EL = b'\xf8'        # Erase Line
GA = b'\xf9'        # Go Ahead
SB = b'\xfa'        # Subnegotiation Begin
WILL = b'\xfb'      # Will (option negotiation)
WONT = b'\xfc'      # Won't (option negotiation)
DO = b'\xfd'        # Do (option negotiation)
DONT = b'\xfe'      # Don't (option negotiation)
IAC = b'\xff'       # Interpret As Command (escape)

# Telnet Options (Common ones)
ECHO = b'\x01'              # Echo
SUPPRESS_GO_AHEAD = b'\x03' # Suppress Go Ahead
STATUS = b'\x05'            # Status
TIMING_MARK = b'\x06'       # Timing Mark
TERMINAL_TYPE = b'\x18'     # Terminal Type
WINDOW_SIZE = b'\x1f'       # Window Size (NAWS)
TERMINAL_SPEED = b'\x20'    # Terminal Speed
LINEMODE = b'\x22'          # Line Mode
ENVIRON = b'\x24'           # Environment Variables

# NVT Line Terminators
CRLF = CR + LF              # Standard NVT line ending
CR_NULL = CR + NULL         # CR followed by NULL


class NVTEncoder:
    """
    Encodes data for NVT transmission.
    Converts local format to NVT format following RFC 854.
    """
    
    @staticmethod
    def encode_text(text: str) -> bytes:
        """
        Encode text string to NVT format.
        
        Args:
            text: String to encode
            
        Returns:
            Encoded bytes in NVT format
        """
        if isinstance(text, bytes):
            text = text.decode('utf-8', errors='replace')
        
        # Convert to UTF-8 bytes first
        data = text.encode('utf-8', errors='replace')
        
        # Apply NVT transformations
        result = bytearray()
        
        for byte in data:
            b = bytes([byte])
            
            # Escape IAC by doubling it (IAC IAC)
            if b == IAC:
                result.extend(IAC + IAC)
            # Convert line endings to CR-LF
            elif b == LF:
                # Check if previous char was CR
                if len(result) > 0 and result[-1:] == CR:
                    result.extend(LF)
                else:
                    result.extend(CRLF)
            elif b == CR:
                # Add CR, will handle LF on next iteration
                result.extend(CR)
            else:
                result.extend(b)
        
        # Handle trailing CR without LF
        if len(result) > 0 and result[-1:] == CR:
            result.extend(NULL)
        
        return bytes(result)
    
    @staticmethod
    def create_command(command: bytes, option: bytes = None) -> bytes:
        """
        Create a telnet command sequence.
        
        Args:
            command: Command byte (WILL, WONT, DO, DONT, etc.)
            option: Optional option byte
            
        Returns:
            IAC command sequence
        """
        if option:
            return IAC + command + option
        return IAC + command
    
    @staticmethod
    def encode_with_padding(text: str, chunk_size: int = 4096) -> bytes:
        """
        Encode text and pad to chunk size for fixed-length transmission.
        
        Args:
            text: Text to encode
            chunk_size: Target size for padding
            
        Returns:
            Padded NVT-encoded bytes
        """
        encoded = NVTEncoder.encode_text(text)
        
        # Pad with spaces if needed (but respect NVT encoding)
        if len(encoded) < chunk_size:
            padding = b' ' * (chunk_size - len(encoded))
            return encoded + padding
        
        return encoded


class NVTDecoder:
    """
    Decodes NVT format data to local format.
    Handles IAC sequences and line ending conversions.
    """
    
    def __init__(self):
        self.buffer = bytearray()
        self.in_iac = False
        self.iac_command = None
    
    def decode_bytes(self, data: bytes) -> tuple:
        """
        Decode NVT bytes to text and commands.
        
        Args:
            data: Raw bytes received
            
        Returns:
            Tuple of (decoded_text, commands_list)
        """
        text_buffer = bytearray()
        commands = []
        
        i = 0
        while i < len(data):
            byte = bytes([data[i]])
            
            # IAC sequence handling
            if self.in_iac:
                if self.iac_command is None:
                    # First byte after IAC
                    if byte == IAC:
                        # IAC IAC means literal 0xFF
                        text_buffer.extend(IAC)
                        self.in_iac = False
                    elif byte in [WILL, WONT, DO, DONT]:
                        # Commands that need an option
                        self.iac_command = byte
                    elif byte in [SE, NOP, DM, BRK, IP, AO, AYT, EC, EL, GA]:
                        # Simple commands
                        commands.append(('COMMAND', byte))
                        self.in_iac = False
                    else:
                        # Unknown command, ignore
                        self.in_iac = False
                else:
                    # Second byte (option) after WILL/WONT/DO/DONT
                    commands.append((self.iac_command.decode('latin-1'), byte))
                    self.in_iac = False
                    self.iac_command = None
            elif byte == IAC:
                self.in_iac = True
            else:
                # Regular data
                text_buffer.extend(byte)
            
            i += 1
        
        # Convert CR-LF or CR-NULL to \n
        decoded = bytes(text_buffer)
        decoded = decoded.replace(CRLF, b'\n')
        decoded = decoded.replace(CR_NULL, b'\n')
        decoded = decoded.replace(CR, b'\n')  # Handle bare CR
        
        try:
            text = decoded.decode('utf-8', errors='replace').strip()
        except:
            text = decoded.decode('latin-1', errors='replace').strip()
        
        return text, commands
    
    @staticmethod
    def decode_simple(data: bytes) -> str:
        """
        Simple decode for when you just want the text.
        
        Args:
            data: Raw bytes
            
        Returns:
            Decoded text string
        """
        decoder = NVTDecoder()
        text, _ = decoder.decode_bytes(data)
        return text


class NVTSession:
    """
    Manages an NVT session with option negotiation.
    """
    
    def __init__(self):
        self.local_options = {}   # Options we've agreed to
        self.remote_options = {}  # Options remote has agreed to
        self.encoder = NVTEncoder()
        self.decoder = NVTDecoder()
    
    def negotiate_option(self, option_type: bytes, enable: bool = True) -> bytes:
        """
        Negotiate a telnet option.
        
        Args:
            option_type: The option to negotiate (ECHO, etc.)
            enable: True to enable (WILL), False to disable (WONT)
            
        Returns:
            Command bytes to send
        """
        if enable:
            return self.encoder.create_command(WILL, option_type)
        else:
            return self.encoder.create_command(WONT, option_type)
    
    def respond_to_option(self, command: bytes, option: bytes, accept: bool = True) -> bytes:
        """
        Respond to an option request from remote.
        
        Args:
            command: WILL or WONT from remote
            option: The option they're negotiating
            accept: Whether to accept (True = DO, False = DONT)
            
        Returns:
            Response bytes to send
        """
        if command == WILL:
            # Remote wants to enable option
            if accept:
                self.remote_options[option] = True
                return self.encoder.create_command(DO, option)
            else:
                return self.encoder.create_command(DONT, option)
        elif command == WONT:
            # Remote wants to disable option
            self.remote_options[option] = False
            return self.encoder.create_command(DONT, option)
        elif command == DO:
            # Remote wants us to enable option
            if accept:
                self.local_options[option] = True
                return self.encoder.create_command(WILL, option)
            else:
                return self.encoder.create_command(WONT, option)
        elif command == DONT:
            # Remote wants us to disable option
            self.local_options[option] = False
            return self.encoder.create_command(WONT, option)
        
        return b''
    
    def send_text(self, text: str, chunk_size: int = None) -> bytes:
        """
        Prepare text for sending over NVT.
        
        Args:
            text: Text to send
            chunk_size: Optional chunk size for padding
            
        Returns:
            NVT-encoded bytes
        """
        if chunk_size:
            return self.encoder.encode_with_padding(text, chunk_size)
        return self.encoder.encode_text(text)
    
    def receive_data(self, data: bytes) -> tuple:
        """
        Process received NVT data.
        
        Args:
            data: Raw bytes received
            
        Returns:
            Tuple of (text, commands_to_respond_to)
        """
        text, commands = self.decoder.decode_bytes(data)
        
        # Auto-respond to option negotiations
        responses = []
        for cmd, opt in commands:
            if cmd in [WILL, WONT, DO, DONT]:
                # Auto-accept common options, reject others
                accept = opt in [ECHO, SUPPRESS_GO_AHEAD, TERMINAL_TYPE]
                response = self.respond_to_option(cmd, opt, accept)
                if response:
                    responses.append(response)
        
        return text, responses


# Utility functions for easy integration

def encode_nvt(text: str) -> bytes:
    """Quick encode text to NVT format."""
    return NVTEncoder.encode_text(text)

def decode_nvt(data: bytes) -> str:
    """Quick decode NVT data to text."""
    return NVTDecoder.decode_simple(data)

def create_nvt_command(cmd: str, option: str = None) -> bytes:
    """
    Create NVT command by name.
    
    Examples:
        create_nvt_command('WILL', 'ECHO')
        create_nvt_command('AYT')
    """
    cmd_map = {
        'WILL': WILL, 'WONT': WONT, 'DO': DO, 'DONT': DONT,
        'SE': SE, 'NOP': NOP, 'DM': DM, 'BRK': BRK,
        'IP': IP, 'AO': AO, 'AYT': AYT, 'EC': EC,
        'EL': EL, 'GA': GA, 'SB': SB
    }
    
    opt_map = {
        'ECHO': ECHO, 'SUPPRESS_GO_AHEAD': SUPPRESS_GO_AHEAD,
        'STATUS': STATUS, 'TIMING_MARK': TIMING_MARK,
        'TERMINAL_TYPE': TERMINAL_TYPE, 'WINDOW_SIZE': WINDOW_SIZE,
        'TERMINAL_SPEED': TERMINAL_SPEED, 'LINEMODE': LINEMODE,
        'ENVIRON': ENVIRON
    }
    
    cmd_byte = cmd_map.get(cmd.upper())
    opt_byte = opt_map.get(option.upper()) if option else None
    
    if cmd_byte:
        return NVTEncoder.create_command(cmd_byte, opt_byte)
    return b''


# Testing and validation functions

def test_nvt():
    """Test NVT encoding/decoding."""
    print("Testing NVT Implementation...")
    print("=" * 50)
    
    # Test 1: Simple text
    text1 = "Hello, World!"
    encoded = encode_nvt(text1)
    decoded = decode_nvt(encoded)
    print(f"Test 1 - Simple text:")
    print(f"  Original: {text1}")
    print(f"  Encoded:  {encoded}")
    print(f"  Decoded:  {decoded}")
    print(f"  Success:  {text1 == decoded}")
    print()
    
    # Test 2: Line endings
    text2 = "Line 1\nLine 2\rLine 3\r\nLine 4"
    encoded = encode_nvt(text2)
    decoded = decode_nvt(encoded)
    print(f"Test 2 - Line endings:")
    print(f"  Original: {repr(text2)}")
    print(f"  Encoded:  {encoded}")
    print(f"  Decoded:  {repr(decoded)}")
    print()
    
    # Test 3: IAC escaping
    text3 = "Text with \xff (IAC) character"
    encoded = encode_nvt(text3)
    decoded = decode_nvt(encoded)
    print(f"Test 3 - IAC escaping:")
    print(f"  Original: {repr(text3)}")
    print(f"  Encoded:  {encoded.hex()}")
    print(f"  Decoded:  {repr(decoded)}")
    print()
    
    # Test 4: Command creation
    cmd = create_nvt_command('WILL', 'ECHO')
    print(f"Test 4 - Command creation:")
    print(f"  WILL ECHO: {cmd.hex()}")
    print()
    
    # Test 5: Session negotiation
    session = NVTSession()
    text = session.send_text("Hello NVT")
    print(f"Test 5 - Session:")
    print(f"  Encoded text: {text}")
    
    decoded_text, commands = session.receive_data(text)
    print(f"  Decoded text: {decoded_text}")
    print(f"  Commands: {commands}")
    print()
    
    print("=" * 50)
    print("All tests completed!")


if __name__ == "__main__":
    test_nvt()