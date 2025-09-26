# Transport Layer Design

## Overview

The transport layer provides a modular system that allows the Mesh-Citadel BBS to communicate over different protocols and interfaces. The goal is to create reusable components so that functionally-similar transport methods can share code while allowing protocol-specific optimizations.

## Architecture

The transport layer is organized into several distinct layers, from low-level hardware interfaces to high-level command processing:

### Layer Stack (bottom to top)

1. **Physical Layer** - Hardware-specific interfaces
   - Mesh radio hardware
   - Dial-up modem
   - TCP sockets (telnet/SSH)
   - Terminal I/O (CLI)

2. **Protocol Layer** - Transport-specific formatting and flow control
   - **MeshCore**: Packet chunking, mesh addressing, reliability handling
   - **Telnet/SSH**: Character-by-character input, escape sequence handling
   - **HTTP**: Request/response cycle, JSON payload formatting
   - **CLI**: Line buffering, terminal control handling

3. **Text Parser Layer** - Converts text input to BaseCommand objects
   - Parses "G" → `GoNextUnreadCommand()`
   - Parses "H V" → `HelpCommand()` with verbose arguments
   - **Shared by all text-based transports** (mesh, telnet, CLI, dial-up)
   - Returns `BaseCommand` objects or `ErrorResponse` for invalid input

4. **Command Interface** - Existing system
   - `BaseCommand` objects → `CommandProcessor`
   - Consistent interface regardless of transport origin

## Key Reusability Points

### Shared Components

- **Text Parser**: The core text-to-command parsing logic is shared by mesh, telnet, dial-up, and CLI transports
- **Command Objects**: All transports deliver the same `BaseCommand` interface to `CommandProcessor`
- **Session Management**: Login flows and session lifecycle can be shared
- **Response Formatting**: Basic response structures can be reused with transport-specific formatting

### Transport-Specific Components

- **Protocol Chunking**: MeshCore's packet chunking for size-constrained messaging
- **Terminal Handling**: CLI-specific keyboard interrupt and terminal control
- **Network Management**: Connection handling for TCP-based transports

## Transport-Specific Bypasses

Some transports may bypass certain layers for efficiency or functionality:

- **HTTP/Web Interface**: Could skip Text Parser entirely, generating `BaseCommand` objects directly from button clicks and form submissions
- **Future GUI Applications**: Same bypass potential for rich client interfaces

## Implementation Components

### TransportManager

- **Location**: `citadel/transport/manager.py`
- **Purpose**: Factory for loading appropriate transport engines based on configuration
- **Responsibilities**:
  - Read transport configuration from config file
  - Instantiate the correct transport engines (CLI, MeshCore, etc.)
  - Provide common initialization and shutdown interfaces

### Text Parser

- **Location**: `citadel/transport/parser.py` ✓ (implemented)
- **Purpose**: Convert text strings to BaseCommand objects
- **Interface**: `parse_command(text: str) -> Union[BaseCommand, ErrorResponse]`
- **Shared by**: CLI, MeshCore, Telnet, Dial-up transports

### Transport Engines

Currently-planned individual transport implementations:

- **CLI Transport**: `citadel/transport/cli.py`
  - Terminal I/O handling
  - Line buffering and keyboard input
  - Session management for single-user CLI access
  - Temporary KeyboardInterrupt handling during development

- **MeshCore Transport**: `citadel/transport/meshcore.py` (future)
  - Packet chunking for mesh constraints (140-184 character messages)
  - Node ID as username integration
  - DM-based session establishment

## Configuration Integration

The transport layer will read configuration from the main config file to determine:

- Which transport engines to load (more than one possible at a time)
- Transport-specific settings (ports, timeouts, packet sizes, etc.)
- Protocol-specific parameters

Example config structure:
```yaml
transport:
  engines: 
    - "cli"  # or "telnet", etc.
    - "meshcore"
  cli:
    # CLI-specific settings
  meshcore:
    # MeshCore-specific settings
```

## Session Management Patterns

### CLI Transport
- Single-user session on startup
- Session persists until logout or timeout
- Direct stdin/stdout interaction
- Ending CLI session shuts down server
- Primarily useful for debugging and development

### MeshCore Transport (future)
- Session per node ID
- Sessions established via DM contact
- Node ID becomes username automatically
- Multiple concurrent connections possible

### Network Transports (future)
- Session per connection
- Standard login/logout flows
- Connection-based session lifecycle
- Multiple concurrent connections possible

## Development Approach

### Phase 1: CLI Transport (Current)
1. ✓ Text Parser implementation
2. ✓ Updated main.py with system initialization
3. TransportManager factory pattern
4. CLI transport engine with basic I/O
5. Response formatting for terminal output

### Phase 2: MeshCore Integration (Future)
1. MeshCore protocol layer implementation
2. Packet chunking for message size constraints
3. Node ID integration with user system
4. DM-based session management

### Phase 3: Additional Transports (Future)
- Telnet/SSH transport
- HTTP/Web interface transport
- Additional protocol support as needed

## Design Principles

- **Modularity**: Each layer has clear responsibilities and interfaces
- **Reusability**: Common functionality shared across similar transports
- **Extensibility**: New transports can be added without modifying existing code
- **Efficiency**: Transport-specific optimizations where needed
- **Consistency**: All transports deliver the same command interface to the BBS core

---

*Document created: 2025-09-24*
*Status: Phase 1 (CLI Transport) in development*
