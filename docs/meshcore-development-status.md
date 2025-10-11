# MeshCore Transport Engine Development Status

**Date:** October 10, 2025
**Status:** In Development - Architecture Clarified, Implementation Partial

## Overview

This document captures the current state of MeshCore transport engine development for mesh-citadel, including architectural decisions, implementation progress, and next steps for continuing development.

## Current Implementation State

### Completed Components

1. **Basic MeshCore Integration** (`citadel/transport/engines/meshcore/transport.py`):
   - MeshCore library integration with event subscription system
   - Lifecycle management (start/stop) with proper error handling
   - Event handlers registered for: message receipt, node adverts, delivery confirmations
   - Missing imports added: `FromUser`, `FromUserType`, `ToUser`, `CommandProcessor`, `TextParser`
   - Command processor and text parser initialized in constructor

2. **SessionManager Analysis**:
   - Existing methods available: session lifecycle, authentication state, workflow management, message queuing
   - Missing methods identified for node binding (documented as TODOs)

### Partially Completed Components

1. **Database Integration** (`transport.py:144-171`):
   - Advert handler completed with proper async database calls and narrow exception handling
   - Uses proper `await self.db.execute()` pattern
   - Handles KeyError and TypeError/ValueError specifically
   - **Issue**: `mc_adverts` table schema not yet added to `citadel/db/initializer.py`

2. **Confirmation Handler** (`transport.py:173-180`):
   - Basic structure implemented
   - Logs delivery confirmations
   - **TODO**: Update packet tracking table with delivery status

### Stub/Placeholder Components

1. **Node Binding Methods** (referenced but not implemented):
   - `SessionManager.get_session_by_node(node_id)` - lookup session by mesh node
   - `SessionManager.bind_node_to_session(node_id, session_id)` - create mapping
   - **Status**: Commented out with TODO notes in transport.py

2. **Password Cache System** (`transport.py:182-189`):
   - `_node_has_password_cache()` returns False (placeholder)
   - **TODO**: Implement once `mc_password_cache` table exists

3. **Message Sending** (`transport.py:191-202`):
   - `send_to_node()` method is stub with comprehensive TODO comments
   - **TODO**: Node lookup, message chunking, MeshCore command creation, retry logic

### Incomplete/Truncated Code

- **File was previously truncated at line 153** - now completed through line 202
- All methods now have complete implementations (stubs where appropriate)

## Architectural Decisions & Design Patterns

### Core Architecture: Async Queue-Based Messaging

**Key Decision**: MeshCore transport uses fully asynchronous, queue-based messaging instead of CLI transport's synchronous call-and-response pattern.

**Rationale**:
- **Mesh networking is unreliable**: Messages can be lost, delayed, or arrive out of order
- **No guaranteed delivery timing**: Responses might take minutes or fail entirely
- **Multiple nodes per user**: Same user can connect from different mesh nodes simultaneously
- **Session isolation**: Each session acts as independent "phone line" even for same username

### Session Management Model

**Multi-Session Per User Support**:
- Each mesh node connection creates its own session_id
- Commands from session N → responses to session N
- Sessions operate independently even with same username
- Supports organizational use case: multiple operators using shared username from different nodes

**Message Flow**:
- **Inbound**: MeshCore packet → session lookup → queue for async processing → command processor → results to session msg_queue
- **Outbound**: Session msg_queue → outbound processor → chunk/format → MeshCore transmission with retry

### Authentication Architecture

**Critical Decision**: MeshCore uses different authentication model than CLI transport.

#### CLI vs MeshCore Authentication Differences

| Aspect | CLI Transport | MeshCore Transport |
|--------|--------------|-------------------|
| **Interface** | Text-based command line | Chat application with history |
| **Login Method** | Workflow system (prompts in CLI) | Special application packets (dedicated login UI) |
| **Security** | Credentials not stored in history | Credentials would appear in chat history if using workflows |
| **Registration** | Workflow system appropriate | Must use chat (no other option with existing clients) |

#### MeshCore Authentication Flow

1. **New user connects** → Send `room_server_handshake` packet with `login_required: true`
2. **Client displays dedicated login page** → User enters credentials in secure UI (not chat)
3. **Client sends credentials** → Via special authentication packet (not chat message)
4. **Server validates username/password**:
   - **Username exists** → Validate password, login if correct
   - **Username doesn't exist** → Registration required first
5. **Registration flow** → Happens in chat (unavoidable security compromise)
   - User creates username/password via chat messages
   - Registration credentials will appear in chat history (accepted tradeoff)
   - Registration workflow completes via chat-based workflow system
6. **After registration** → User must authenticate again with new credentials via secure packets
7. **Successful login** → Normal BBS operation

#### Why Authentication Bypasses Workflow System

- **Security**: Login credentials sent via secure application packets, not chat messages
- **UX**: Proper login page instead of confusing chat-based prompts
- **Protocol**: Leverages MeshCore's application packet types for authentication
- **Registration Exception**: Only registration uses chat-based workflow (no other choice)

**Code Implication**: Direct `self.session_mgr.authenticate(session_id, payload)` calls are correct for MeshCore, not a design flaw.

## Database Schema Requirements

### Missing Tables (need to be added to `citadel/db/initializer.py`)

1. **`mc_adverts`** - Node advertisement storage
   ```sql
   CREATE TABLE mc_adverts (
       node_id TEXT PRIMARY KEY,
       public_key TEXT NOT NULL,
       node_type TEXT DEFAULT 'user',
       last_heard TEXT NOT NULL,  -- ISO datetime
       signal_strength INTEGER DEFAULT 0,
       hop_count INTEGER DEFAULT 0
   );
   ```

2. **`mc_password_cache`** - Password cache with expiration
   ```sql
   CREATE TABLE mc_password_cache (
       node_id TEXT PRIMARY KEY,
       username TEXT NOT NULL,
       expires_at TEXT NOT NULL  -- ISO datetime
   );
   ```

3. **`mc_packet_tracking`** - Message deduplication and retry tracking
   ```sql
   CREATE TABLE mc_packet_tracking (
       packet_hash TEXT PRIMARY KEY,  -- hash of sender + timestamp + content
       node_id TEXT NOT NULL,
       session_id TEXT NOT NULL,
       created_at TEXT NOT NULL,
       delivery_status TEXT DEFAULT 'pending'  -- pending, confirmed, failed
   );
   ```

4. **`mc_node_sessions`** - Node to session mapping
   ```sql
   CREATE TABLE mc_node_sessions (
       node_id TEXT NOT NULL,
       session_id TEXT NOT NULL,
       created_at TEXT NOT NULL,
       last_active TEXT NOT NULL,
       PRIMARY KEY (node_id, session_id)
   );
   ```

## Exception Handling Strategy

**Pattern**: Use narrow exception handling following PEP8 principles.

**Implemented Examples**:
- `KeyError` - Missing required fields in advert data
- `TypeError`, `ValueError` - Invalid advert data format
- `UnicodeDecodeError` - Failed message decoding
- `SerialException`, `OSError` - Hardware/system errors
- `Exception` - Only as last resort in lifecycle methods with clear justification

**Anti-Pattern Avoided**: Broad `except Exception:` in message handlers that could mask protocol-specific errors.

## Missing SessionManager Methods

The following methods are referenced in transport.py but don't exist in SessionManager yet:

```python
# Node binding methods (required for MeshCore)
def get_session_by_node(self, node_id: str) -> str | None:
    """Look up session_id by mesh node_id."""

def bind_node_to_session(self, node_id: str, session_id: str) -> None:
    """Create node_id → session_id mapping."""

def get_nodes_for_session(self, session_id: str) -> list[str]:
    """Get all node_ids mapped to a session (for multi-node support)."""
```

These methods will query the `mc_node_sessions` table when implemented.

## Current File Status

### `citadel/transport/engines/meshcore/transport.py`

**Status**: File structure complete, imports fixed, stubs documented
**Lines**: 202 total (was truncated at 153)
**Key Issues Fixed**:
- Added missing imports (`FromUser`, `FromUserType`, `ToUser`, etc.)
- Completed truncated `_handle_advert()` method with proper async/await
- Added `_handle_confirmation()` method
- Added stub implementations for `_node_has_password_cache()` and `send_to_node()`
- Used narrow exception handling throughout

**TODOs Documented in Code**:
- SessionManager node binding methods (lines 85, 90)
- Password cache implementation (lines 185-187)
- Message sending implementation (lines 194-199)
- Packet tracking updates (line 177)

## Next Steps Priority Order

### Critical Blockers (Must Complete First)

1. **Add Database Schema** (`citadel/db/initializer.py`)
   - Add `mc_*` tables to database initialization
   - Update schema migration logic if needed
   - Priority: CRITICAL - blocks most functionality

2. **Extend SessionManager** (`citadel/session/manager.py`)
   - Implement `get_session_by_node()`, `bind_node_to_session()`, `get_nodes_for_session()`
   - Add database operations for `mc_node_sessions` table
   - Priority: CRITICAL - blocks message routing

3. **Complete Message Handling** (`transport.py`)
   - Fix message handler to use proper async queue architecture
   - Remove synchronous call-and-response pattern
   - Implement proper session-to-session message routing
   - Priority: HIGH - core functionality

### High Priority (MVP Functionality)

4. **Implement Message Sending Pipeline**
   - Complete `send_to_node()` method with MeshCore integration
   - Handle message chunking for packet size limits
   - Integrate with session message queues
   - Priority: HIGH - needed for responses

5. **Add Outbound Message Processor**
   - Create async task to poll session msg_queues
   - Implement retry logic with timeouts
   - Handle delivery failure gracefully (discard after timeout)
   - Priority: HIGH - needed for reliable delivery

6. **Password Cache System**
   - Implement `_node_has_password_cache()` with database lookup
   - Add cache expiration logic
   - Integrate with sweeper thread cleanup
   - Priority: MEDIUM - improves UX

### Configuration & Integration

7. **TransportManager Integration**
   - Add meshcore engine type to TransportManager
   - Create configuration schema for meshcore section
   - Enable multi-engine support (CLI + MeshCore simultaneously)
   - Priority: MEDIUM - needed for deployment

8. **Message Deduplication**
   - Implement content-based deduplication using packet hashing
   - Add `mc_packet_tracking` operations
   - Handle duplicate detection in `_handle_message()`
   - Priority: MEDIUM - prevents duplicate processing

9. **Testing Infrastructure**
   - Create mock MeshCoreSerial for unit tests
   - Add integration tests with simulated mesh network
   - Test multi-session scenarios
   - Priority: LOW - quality assurance

## Design Patterns Used

### Async-First Architecture
- All event handlers designed to be async (even though MeshCore subscription requires sync handlers initially)
- Database operations use `await self.db.execute()`
- Message processing queued for async execution

### Factory Pattern
- TransportManager loads engines dynamically
- CommandProcessor factory for different command types

### Observer Pattern
- MeshCore event subscription system
- Session message queue notifications

### Queue-Based Messaging
- Inbound message queues per session
- Outbound message queues with retry logic
- Eliminates synchronous response expectations

## Known Limitations & Future Considerations

### Current Limitations

1. **Registration Security**: Registration credentials appear in chat history (unavoidable with existing clients)
2. **No Custom Client**: Limited to existing MeshCore client capabilities
3. **Packet Size Limits**: Need message chunking (not yet implemented)
4. **Delivery Guarantees**: No "too many retries" failure handling designed yet

### Future Improvements

1. **Custom Client**: Could handle registration via secure packets
2. **Message Compression**: Optimize for bandwidth-constrained mesh networks
3. **Advanced Retry Logic**: Exponential backoff, priority queuing
4. **Multi-Node Session Management**: Enhanced support for organizational use cases

## References

- **Existing Documents**: `docs/meshcore-implementation-plan.md`, `docs/meshcore-usb-protocol.md`
- **Code Files**: `citadel/transport/engines/meshcore/transport.py`, `citadel/session/manager.py`
- **Database**: `citadel/db/initializer.py`, `citadel/db/manager.py`
- **Similar Implementation**: `citadel/transport/engines/cli.py` (for patterns, not architecture)

---

**Note**: This document represents the state as of the October 10, 2025 development session. Continue development by addressing the Critical Blockers in order, then proceeding through High Priority items.