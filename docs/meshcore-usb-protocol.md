# MeshCore USB Protocol Research Findings

Based on analysis of the MeshCore repository, here are the critical findings for implementing the mesh-citadel transport engine.

## USB Serial Protocol Structure

### Physical Layer
- **Baud Rate**: 115200 (standard across all platforms)
- **Connection**: Standard USB serial (e.g., `/dev/ttyACM0` on Pi Zero)
- **Frame-based protocol**: Each message is a complete frame
- **Implementation**: **Use async/await patterns for all serial I/O operations**

### Frame Format
```
Outgoing (Host → MeshCore):  >LengthLSB LengthMSB [payload...]
Incoming (MeshCore → Host):  <LengthLSB LengthMSB [payload...]
```

**Frame Structure**:
- Header: 1 byte (`>` for outgoing, `<` for incoming)
- Length: 2 bytes (little-endian, LSB first)
- Payload: Variable length (max 172 bytes)

### Maximum Frame Size
**Critical**: `MAX_FRAME_SIZE = 172 bytes` (payload only, excludes 3-byte header)

## Command/Response Protocol

### Command Types (Host → MeshCore)
Key commands for BBS integration:

- `CMD_DEVICE_QEURY (0x16)`: Initialize connection, get device info
- `CMD_APP_START (0x01)`: Start application session
- `CMD_SEND_TXT_MSG (0x02)`: Send text message to contact
- `CMD_SYNC_NEXT_MESSAGE (0x0A)`: Get next incoming message
- `CMD_GET_CONTACTS (0x04)`: Get contact list
- `CMD_ADD_UPDATE_CONTACT (0x09)`: Add/update contact
- `CMD_SEND_SELF_ADVERT (0x07)`: Broadcast advertisement

### Response Types (MeshCore → Host)
Key responses for message handling:

- `RESP_CODE_CONTACT_MSG_RECV_V3 (0x10)`: Incoming message (protocol v3+)
- `RESP_CODE_SENT (0x06)`: Message send confirmation
- `RESP_CODE_CONTACT (0x03)`: Contact information
- `RESP_CODE_DEVICE_INFO (0x0D)`: Device information response

### Push Notifications (MeshCore → Host, Async)
- `PUSH_CODE_ADVERT (0x80)`: Node advertisement received
- `PUSH_CODE_SEND_CONFIRMED (0x82)`: Message delivery confirmed
- `PUSH_CODE_MSG_WAITING (0x83)`: Message available for retrieval

## Message Structure and Deduplication

### **Critical Finding: No Built-in Message IDs**

**The MeshCore protocol does NOT provide sequence numbers or message IDs for deduplication.**

**Available for Deduplication**:
1. **Source Node**: 6-byte public key prefix
2. **Message Timestamp**: 4-byte sender timestamp
3. **Message Content**: The actual text payload
4. **SNR Data**: Signal-to-noise ratio (protocol v3+)
5. **Path Length**: Number of hops (0xFF for direct messages)

**Recommended Deduplication Strategy**:
```python
# Generate hash for deduplication
dedup_key = hash(source_pubkey_prefix + timestamp + message_content)
```

### Message Receive Format (Protocol v3)
```
Byte 0:    RESP_CODE_CONTACT_MSG_RECV_V3 (0x10)
Byte 1:    SNR * 4 (int8_t)
Byte 2-3:  Reserved (0x00)
Byte 4-9:  Source public key (6 bytes)
Byte 10:   Path length (0xFF for direct)
Byte 11:   Text type (TXT_TYPE_PLAIN=0, TXT_TYPE_CLI_DATA=1, etc.)
Byte 12-15: Sender timestamp (4 bytes, little-endian)
Byte 16+:  Message text (null-terminated)
```

## Text Message Types

- `TXT_TYPE_PLAIN (0)`: Regular text messages
- `TXT_TYPE_CLI_DATA (1)`: Command/response data
- `TXT_TYPE_SIGNED_PLAIN (2)`: Cryptographically signed messages

## LoRa Packet Constraints

### Packet Size Analysis
- **Total LoRa packet**: 256 bytes max
- **MeshCore headers**: Varies by routing type and path length
- **Usable payload**: ~140-184 bytes (depends on path length)
- **USB frame limit**: 172 bytes max

### LoRa Packet Structure
```
Header:          1 byte (route type, payload type, version)
Transport codes: 4 bytes (optional, for bridging)
Path length:     1 byte
Path:           0-64 bytes (routing path)
Payload:        0-184 bytes (actual data)
```

### Payload Types Relevant to BBS
- `PAYLOAD_TYPE_TXT_MSG (0x02)`: Text messages
- `PAYLOAD_TYPE_ACK (0x03)`: Acknowledgments
- `PAYLOAD_TYPE_ADVERT (0x04)`: Node advertisements
- `PAYLOAD_TYPE_REQ (0x00)`: Requests (login, etc.)

## Contact Management

### Contact Structure
- **Public Key**: 32 bytes (only 6-byte prefix used in messages)
- **Name**: Variable length string
- **Last Contact**: Timestamp of last communication
- **Path Information**: Routing path to contact

### Contact Discovery
- **Advertisements**: Periodic broadcasts containing public key and name
- **Auto-add**: Can be enabled/disabled via preferences
- **Manual add**: Explicit contact addition via public key

## Authentication and Security

### Key Findings
- **Public Key Encryption**: All direct messages use contact's public key
- **No Built-in Sessions**: Authentication is per-message, not session-based
- **Identity**: Node identity is 32-byte public key + optional name
- **Path Security**: Paths can be verified but routing is generally trusted

## Implementation Implications

### 1. Async Serial I/O Architecture
**All serial operations must use async/await patterns following mesh-citadel conventions:**

```python
async def send_command_async(self, command: int, data: bytes) -> None:
    """Send command to MeshCore device asynchronously"""
    frame = self._build_frame(command, data)
    await self.serial_writer.write(frame)
    await self.serial_writer.drain()

async def read_frame_async(self) -> Optional[bytes]:
    """Read incoming frame from MeshCore device asynchronously"""
    header = await self.serial_reader.readexactly(1)
    if header[0] != ord('<'):
        return None

    length_bytes = await self.serial_reader.readexactly(2)
    frame_len = struct.unpack('<H', length_bytes)[0]

    if frame_len > 0:
        payload = await self.serial_reader.readexactly(frame_len)
        return payload
    return b''

async def message_polling_loop(self):
    """Continuously poll for incoming messages"""
    while self.running:
        try:
            frame = await asyncio.wait_for(
                self.read_frame_async(),
                timeout=1.0
            )
            if frame is not None:
                await self.process_incoming_frame(frame)
        except asyncio.TimeoutError:
            continue  # Normal timeout, keep polling
```

### 2. Packet Deduplication Strategy
Since no sequence numbers are provided:
```python
async def generate_packet_id(self, source_prefix: bytes, timestamp: int, content: str) -> str:
    """Generate unique ID for deduplication"""
    data = source_prefix + timestamp.to_bytes(4, 'little') + content.encode('utf-8')
    return hashlib.sha256(data).hexdigest()[:16]

async def is_duplicate_packet(self, packet_id: str) -> bool:
    """Check if packet has already been processed"""
    # Use DatabaseManager async methods
    return await self.db.check_packet_exists_async(packet_id)
```

### 3. Message Chunking Requirements
- **Word boundaries**: Must break on word boundaries for readability
- **Size calculation**: Account for MeshCore protocol overhead
- **Reassembly**: BBS engine handles, we just forward packets sequentially

### 4. Acknowledgment Handling
- **No automatic acks**: Application must request explicit acknowledgments
- **Timeout handling**: No built-in retry, must implement at transport layer using async timers
- **Delivery confirmation**: Available via `PUSH_CODE_SEND_CONFIRMED`

### 5. Session Management
- **Stateless protocol**: Each command is independent
- **Connection management**: Persistent async USB connection
- **Contact lookup**: By 6-byte public key prefix

## Database Schema Implications

Based on protocol analysis, update the packet tracking table:

```sql
CREATE TABLE mc_packet_tracking (
    packet_hash TEXT PRIMARY KEY,        -- SHA256 of source + timestamp + content
    source_node_prefix BLOB(6) NOT NULL, -- 6-byte public key prefix
    sender_timestamp INTEGER NOT NULL,   -- 4-byte timestamp from packet
    content_preview TEXT,               -- First 100 chars for debugging
    received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    forwarded_to_bbs BOOLEAN DEFAULT 1
);

CREATE INDEX idx_mc_packet_source_time
ON mc_packet_tracking(source_node_prefix, sender_timestamp);
```

## Configuration Requirements

```yaml
meshcore:
  usb_port: "/dev/ttyACM0"
  baud_rate: 115200
  protocol_version: 3              # Use v3 for SNR data

  # Size constraints (conservative estimates)
  max_usb_frame_size: 172         # MeshCore limit
  max_lora_payload: 140           # Conservative estimate

  # Async operation settings
  read_timeout_seconds: 1.0       # Timeout for frame reads
  write_timeout_seconds: 5.0      # Timeout for frame writes
  polling_interval_ms: 100        # Message polling frequency

  # Deduplication settings
  packet_cache_duration_hours: 24
  max_cached_packets: 1000

  # Message handling
  default_batch_size: 3
  message_timeout_seconds: 30
```

## Async Protocol Initialization Sequence

```python
async def initialize_meshcore_connection(self):
    """Initialize MeshCore connection using async patterns"""
    # 1. Establish async USB serial connection
    self.serial_reader, self.serial_writer = await serial_asyncio.open_serial_connection(
        url='/dev/ttyACM0',
        baudrate=115200
    )

    # 2. Send device query
    await self.send_command_async(CMD_DEVICE_QEURY, [3])  # Protocol version 3
    device_info = await self.await_response_async(RESP_CODE_DEVICE_INFO, timeout=5.0)

    # 3. Start application
    await self.send_command_async(CMD_APP_START, [...])
    self_info = await self.await_response_async(RESP_CODE_SELF_INFO, timeout=5.0)

    # 4. Begin async message polling
    asyncio.create_task(self.message_polling_loop())

async def await_response_async(self, expected_code: int, timeout: float = 10.0) -> bytes:
    """Wait for specific response code with timeout"""
    end_time = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < end_time:
        frame = await asyncio.wait_for(
            self.read_frame_async(),
            timeout=min(1.0, end_time - asyncio.get_event_loop().time())
        )
        if frame and len(frame) > 0 and frame[0] == expected_code:
            return frame

    raise TimeoutError(f"No response received for code {expected_code:#04x}")
```

## Async Message Flow Examples

### Sending a Message (Async)
```python
async def send_message_async(self, recipient_pubkey: bytes, message: str) -> bool:
    """Send message asynchronously with delivery confirmation"""
    timestamp = int(time.time())

    # Build and send command
    command_data = struct.pack('<BBI6s',
        TXT_TYPE_PLAIN, 0, timestamp, recipient_pubkey[:6]
    ) + message.encode('utf-8')

    await self.send_command_async(CMD_SEND_TXT_MSG, command_data)

    # Wait for send confirmation
    response = await self.await_response_async(RESP_CODE_SENT, timeout=10.0)
    return response[1] == 0  # Success code

async def wait_for_delivery_confirmation(self, timeout: float = 60.0):
    """Wait for PUSH_CODE_SEND_CONFIRMED asynchronously"""
    # This would be handled in the main polling loop
    pass
```

### Receiving a Message (Async)
```python
async def process_incoming_message(self, frame: bytes):
    """Process incoming message frame asynchronously"""
    if frame[0] == PUSH_CODE_MSG_WAITING:
        # Message available - request it
        await self.send_command_async(CMD_SYNC_NEXT_MESSAGE, b'')

    elif frame[0] == RESP_CODE_CONTACT_MSG_RECV_V3:
        # Parse message
        source_prefix = frame[4:10]
        timestamp = struct.unpack('<I', frame[12:16])[0]
        message = frame[16:].decode('utf-8', errors='ignore').rstrip('\x00')

        # Check for duplicates
        packet_id = await self.generate_packet_id(source_prefix, timestamp, message)
        if not await self.is_duplicate_packet(packet_id):
            # Forward to BBS engine
            await self.forward_to_bbs_async(source_prefix, message, timestamp)
            # Mark as processed
            await self.mark_packet_processed_async(packet_id, source_prefix, timestamp)
```

## Key Architectural Decisions

### 1. Async-First Design
**All I/O operations use async/await** to prevent blocking the transport engine and maintain responsiveness.

### 2. Deduplication Approach
**Use content-based hashing** since no sequence numbers are available.

### 3. Message Forwarding
**Forward packets immediately** to BBS engine using async methods rather than buffering for reassembly.

### 4. Session Binding
**Map MeshCore public key prefixes to mesh-citadel user sessions** for authentication.

### 5. Error Handling
**Implement async retry logic** at transport layer since MeshCore doesn't provide automatic retries.

### 6. Path Handling
**Use reverse path automatically** - MeshCore firmware handles path reversal for responses.

---

## Summary for Implementation

The MeshCore USB protocol is well-documented and straightforward to implement with async patterns. The key insights:

1. **Async I/O required**: All serial operations must use async/await patterns
2. **No sequence numbers**: Must use content+timestamp hashing for deduplication
3. **Frame-based USB protocol**: 172-byte max frames with length prefixes
4. **Rich command set**: Full support for messaging, contacts, and advertisements
5. **Stateless design**: Perfect for unreliable mesh networks
6. **Conservative payload**: ~140 bytes usable after all protocol overhead
7. **Async polling**: Continuous async polling required for incoming messages

This provides a solid foundation for implementing the mesh-citadel transport engine using async/await patterns throughout, ensuring proper integration with the existing mesh-citadel async architecture.