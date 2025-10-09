# MeshCore Transport Engine Implementation Plan

## Overview

This document provides a comprehensive plan for implementing the meshcore transport engine for mesh-citadel, enabling BBS access over LoRa mesh networks. This plan clarifies ambiguities from the original design document and provides a clear roadmap for new developers.

## Project Goals

**Primary Objective**: Enable mesh-citadel BBS functionality over LoRa mesh networks using MeshCore USB firmware protocol.

**Target Environment**:
- Raspberry Pi Zero v1 + LoRa node (nRF52840 + SX1262)
- Solar-powered, ultra-low bandwidth operation
- Air-gapped mesh networking (no Internet dependency)

**Key Constraints**:
- 256-byte total LoRa packet size (~140-184 bytes usable payload)
- Unreliable packet delivery and routing
- Significant latency (seconds to minutes)
- Extremely limited power budget

## Architecture Overview

### Transport Layer Integration
The meshcore engine follows the established mesh-citadel transport engine pattern:
```
User ↔ SessionManager ↔ MeshCore Engine ↔ USB Protocol ↔ LoRa Radio ↔ Mesh Network
```

### Key Components

1. **MeshCore USB Interface**: Low-level protocol handler for USB communication with companion node
2. **Packet Manager**: Handles message chunking, acknowledgments, and reassembly
3. **Session Manager Integration**: Maps MeshCore node IDs to mesh-citadel user sessions
4. **Crypto Layer**: Leverages MeshCore's built-in public key encryption for DMs
5. **User Interaction Handler**: Implements bandwidth-optimized UI patterns

## Clarifications and Decisions

### Database Architecture Decision ✓

**Decision**: Use main database with `mc_*` prefixed tables.

**Rationale**:
- Atomic transactions are essential for user registration, authentication, and session management
- Simpler deployment and backup/restore procedures
- Natural foreign key relationships between BBS users and meshcore configuration
- Namespace conflicts avoided with consistent `mc_*` prefixing

**Implementation**: All meshcore tables will be added to the main `citadel.db` with `mc_` prefix to maintain clear separation while enabling cross-table transactions.

### Password Cache System Specification

**Requirements** (clarified from original design):
- **Time-based expiration**: Configurable number of days (default: 7 days)
- **User opt-in**: Users can choose whether to participate in password caching
- **Admin control**: Cache duration configurable in `config.yaml`, not user-modifiable
- **Per-node authentication**: Each MeshCore node ID maintains separate cache state

**Implementation**:
```yaml
# config.yaml addition
meshcore:
  password_cache:
    enabled: true
    default_duration_days: 7
    allow_user_opt_out: true
```

### User Interface Paradigm

**Key Patterns**:
- **Single Period Convention**: "." means "accept default" or "get next batch"
- **Extreme Brevity**: All text optimized for minimal bandwidth
- **Batch Processing**: Messages delivered in small groups with explicit "more available" indicators
- **Default Actions**: Heavy use of ToUser.hints for suggested next steps

### Protocol Version Strategy

**Current Plan**:
- Start with MeshCore protocol v1 support only
- Architecture designed to support v2 when available
- Configuration specifies protocol version for future multi-version support

## Implementation Phases

### Phase 1: Protocol Research and Foundation (Est. 3-5 days)
**Objective**: Understand MeshCore USB protocol and create foundation components

**Detailed Tasks**:
1. **Protocol Research**:
   - Study MeshCore USB protocol documentation
   - Analyze packet structure, overhead, and payload capacity
   - Document acknowledgment mechanisms and timing requirements
   - Understand path specification and routing behavior
   - **Critical**: Determine what packet identification/metadata is available for deduplication

2. **Project Structure Setup**:
   - Create `citadel/transport/engines/meshcore/` directory structure
   - Set up initial module files and imports
   - Add meshcore configuration section to config schema
   - Create exception hierarchy

3. **USB Interface Implementation**:
   - Implement `MeshCoreUSBInterface` class for real hardware
   - Create `MockMeshCoreInterface` for testing
   - Add basic send/receive methods with error handling
   - Implement connection management and health checks

**Deliverables**:
- [ ] Protocol documentation summary (`docs/meshcore-usb-protocol.md`)
- [ ] Complete project directory structure
- [ ] `usb_interface.py` with real and mock implementations
- [ ] `exceptions.py` with complete hierarchy
- [ ] Basic unit tests for USB interface
- [ ] Configuration schema additions

**Success Criteria**:
- Can establish USB connection to MeshCore node (real and mock)
- Can send and receive raw packets reliably
- All interface methods have comprehensive error handling
- Mock interface behaves identically to real interface for testing

### Phase 2: Packet Management and Messaging Core (Est. 4-6 days)
**Objective**: Implement reliable message transmission with chunking and acknowledgments

**Detailed Tasks**:
1. **Message Chunking System**:
   - Implement word-boundary splitting algorithm
   - Create packet sequence numbering system
   - Handle Unicode and special character edge cases
   - Add size calculation with proper overhead accounting

2. **Acknowledgment Protocol**:
   - Implement reliable delivery with ack/nack system
   - Create retry logic with exponential backoff
   - Handle timeout scenarios and failure modes
   - Design packet queue management for pending messages

3. **Packet Deduplication and Forwarding**:
   - Research and implement duplicate packet detection strategy (depends on protocol findings)
   - Forward packets directly to BBS engine as they arrive
   - Handle packet ordering to maintain sequence
   - Clean up tracking data for processed packets

   **Note**: Deduplication approach depends on what identifying information MeshCore provides:
   - If sequence numbers available: use source_node_id + sequence_number
   - If no built-in IDs: generate hash of packet content + metadata
   - May require storing recent packet content for comparison

**Deliverables**:
- [ ] `packet_manager.py` with complete chunking logic
- [ ] Reliable acknowledgment protocol implementation
- [ ] Packet deduplication and forwarding system
- [ ] Comprehensive retry and timeout handling
- [ ] Database schema for packet tracking (`mc_packet_tracking` table)
- [ ] Integration tests for multi-packet messages

**Success Criteria**:
- Can reliably send messages larger than single packet size
- Handles packet loss scenarios gracefully (tested with mock drops)
- Correctly deduplicates retransmitted packets without forwarding duplicates to BBS
- Forwards packets to BBS engine in proper sequence
- Timeout and retry logic works as specified

### Phase 3: Database Schema Integration (Est. 2-3 days)
**Objective**: Create database schema and integrate with existing DatabaseManager

**Detailed Tasks**:
1. **Database Schema Design**:
   - Create `mc_user_config` table for user preferences
   - Create `mc_adverts` table for node discovery
   - Create `mc_packet_tracking` table for deduplication
   - Add appropriate indexes and constraints
   - Design schema migration for existing databases

2. **DatabaseManager Integration**:
   - Use existing DatabaseManager class for all database operations
   - Create meshcore-specific database methods within existing patterns
   - Leverage existing transaction management and connection pooling
   - Follow established database initialization patterns

3. **Configuration Management**:
   - Implement user preference system using DatabaseManager
   - Create default configuration loading
   - Add password cache expiration tracking
   - Handle configuration validation using existing patterns

**Deliverables**:
- [ ] Database schema additions with migration scripts
- [ ] Integration with existing DatabaseManager patterns
- [ ] User preference management using existing database layer
- [ ] Schema initialization following mesh-citadel conventions

**Success Criteria**:
- Database schema integrates seamlessly with existing citadel.db
- All database operations use existing DatabaseManager infrastructure
- Configuration system follows established mesh-citadel patterns
- Migration system works with existing database initialization

### Phase 4: Session Management Integration (Est. 4-5 days)
**Objective**: Integrate with SessionManager and implement authentication

**Detailed Tasks**:
1. **SessionManager Extensions**:
   - Extend SessionManager to support node ID binding
   - Implement 1:1 mapping between node IDs and sessions
   - Handle session creation/destruction for meshcore
   - Add multi-node support for same user

2. **Password Cache System**:
   - Implement time-based cache with configurable duration
   - Add user opt-in/opt-out capability using DatabaseManager
   - Create cache cleanup and expiration logic
   - Handle cache validation and refresh

3. **Authentication Flow**:
   - Design login workflow optimized for bandwidth constraints
   - Implement registration process for new users
   - Create session persistence across disconnections
   - Add proper security validation

**Deliverables**:
- [ ] SessionManager extensions for node ID support
- [ ] Password cache implementation using DatabaseManager
- [ ] Bandwidth-optimized authentication workflows
- [ ] Session persistence and recovery mechanisms
- [ ] Security validation and audit logging

**Success Criteria**:
- Users can authenticate using node ID + password cache
- Same user can connect from multiple nodes simultaneously
- Sessions persist appropriately across network interruptions
- Password cache respects time limits and user preferences

### Phase 5: Core Transport Engine (Est. 5-7 days)
**Objective**: Implement main transport engine following mesh-citadel patterns

**Detailed Tasks**:
1. **Transport Engine Core**:
   - Implement `MeshCoreTransportEngine` class
   - Follow CLI engine async patterns and structure
   - Integrate with TransportManager discovery system
   - Implement proper lifecycle management

2. **Message Routing**:
   - Create bidirectional message queues
   - Implement ToUser/FromUser packet handling
   - Add proper routing between sessions and mesh network
   - Handle broadcast vs. direct message scenarios

3. **User Workflow Integration**:
   - Implement bandwidth-optimized UI patterns
   - Add "." convention for batch processing
   - Create proper ToUser.hints integration
   - Handle user commands and responses

4. **Error Handling and Recovery**:
   - Add comprehensive error handling throughout
   - Implement graceful degradation for network issues
   - Create proper logging and debugging support
   - Handle edge cases and failure scenarios

**Deliverables**:
- [ ] Complete `MeshCoreTransportEngine` class
- [ ] Bidirectional message routing system
- [ ] Bandwidth-optimized user workflows
- [ ] Comprehensive error handling and recovery
- [ ] Integration with existing TransportManager
- [ ] Complete logging and debugging support

**Success Criteria**:
- Transport engine integrates seamlessly with mesh-citadel
- Users can perform basic BBS operations (login, read messages, send DMs)
- Error conditions are handled gracefully with user feedback
- Performance meets Pi Zero constraints

### Phase 6: Advert Collection and Node Discovery (Est. 3-4 days)
**Objective**: Implement network topology awareness and node discovery

**Detailed Tasks**:
1. **Advert Collection System**:
   - Implement advert packet parsing and validation
   - Create automatic collection and storage using DatabaseManager
   - Add signal strength and hop count tracking
   - Handle advert cleanup and storage limits

2. **Node Discovery**:
   - Implement public key discovery and validation
   - Create node type classification system
   - Add automatic peer discovery workflows
   - Handle dynamic network topology changes

3. **Network Awareness**:
   - Create network topology visualization (text-based)
   - Add neighbor discovery and routing hints
   - Implement node reachability tracking
   - Design future path optimization hooks

**Deliverables**:
- [ ] Automatic advert collection using DatabaseManager
- [ ] Public key discovery and management
- [ ] Network topology awareness features
- [ ] Node reachability and routing support
- [ ] Storage cleanup and management policies

**Success Criteria**:
- Automatically discovers and tracks mesh network nodes
- Maintains accurate public key database for encryption
- Provides network awareness without overwhelming storage
- Prepares foundation for future routing optimizations

### Phase 7: Testing, Optimization, and Documentation (Est. 3-4 days)
**Objective**: Comprehensive testing, performance optimization, and documentation

**Detailed Tasks**:
1. **Comprehensive Testing**:
   - Create full integration test suite
   - Add multi-node mesh network testing
   - Implement stress testing for Pi Zero constraints
   - Test all error conditions and edge cases

2. **Performance Optimization**:
   - Profile CPU and memory usage on Pi Zero
   - Optimize database queries and caching
   - Reduce power consumption where possible
   - Fine-tune packet timing and retry logic

3. **Documentation and Deployment**:
   - Create user installation and configuration guide
   - Document troubleshooting procedures
   - Add developer documentation for future enhancements
   - Create deployment and maintenance procedures

**Deliverables**:
- [ ] Complete integration and stress test suites
- [ ] Performance-optimized implementation
- [ ] Comprehensive user and developer documentation
- [ ] Deployment and maintenance guides
- [ ] Troubleshooting and debugging documentation

**Success Criteria**:
- All tests pass on both mock and real hardware
- Performance meets or exceeds targets on Pi Zero
- Documentation enables easy setup and maintenance
- System is ready for production deployment

## Technical Specifications

### Database Schema Requirements

**New Tables Needed**:

```sql
-- User meshcore preferences and configuration
CREATE TABLE mc_user_config (
    user_id INTEGER PRIMARY KEY,
    node_id TEXT,  -- Associated MeshCore node ID (optional)
    message_batch_size INTEGER DEFAULT 3,
    password_cache_enabled BOOLEAN DEFAULT 1,
    password_cache_expiry DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Collected adverts from mesh network
CREATE TABLE mc_adverts (
    node_id TEXT PRIMARY KEY,
    public_key BLOB NOT NULL,
    node_type TEXT DEFAULT 'user',  -- 'user', 'repeater', 'room_server'
    last_heard DATETIME DEFAULT CURRENT_TIMESTAMP,
    signal_strength INTEGER,  -- If available from MeshCore
    hop_count INTEGER         -- If available from MeshCore
);

-- Packet tracking for deduplication (schema TBD based on protocol research)
CREATE TABLE mc_packet_tracking (
    -- Primary key strategy depends on available packet metadata:
    -- Option 1: If sequence numbers available
    -- packet_key TEXT PRIMARY KEY, -- source_node_id + sequence_number

    -- Option 2: If no built-in IDs
    -- content_hash TEXT PRIMARY KEY, -- hash of packet content + metadata

    -- Option 3: Content-based matching
    -- packet_content TEXT, source_node_id TEXT, received_at DATETIME

    -- Will be finalized after protocol research in Phase 1
    placeholder_column TEXT -- Remove after protocol research
);
```

### Configuration Schema

```yaml
# config.yaml additions
meshcore:
  enabled: true

  # Hardware configuration
  usb_port: "/dev/ttyACM0"  # Pi Zero default
  baud_rate: 115200
  protocol_version: "v1"

  # Network configuration
  node_id: null  # Auto-discovered from hardware
  max_packet_size: 184  # Conservative estimate, will be refined

  # Messaging configuration
  default_batch_size: 3
  ack_timeout_seconds: 30
  max_retries: 3

  # Password cache system
  password_cache:
    enabled: true
    default_duration_days: 7
    allow_user_opt_out: true

  # Advert collection
  adverts:
    collect_user_nodes: true
    collect_repeater_nodes: false  # Future feature
    cleanup_after_days: 30
    max_stored_adverts: 1000

  # Development/testing
  mock_hardware: false  # Use mock interface instead of real USB
```

### Error Handling Strategy

Following mesh-citadel conventions and PEP 8 guidelines:

**Exception Hierarchy**:
```python
class MeshCoreError(Exception):
    """Base exception for all MeshCore transport errors"""
    pass

class MeshCoreUSBError(MeshCoreError):
    """USB communication errors"""
    pass

class MeshCoreProtocolError(MeshCoreError):
    """Protocol parsing/formatting errors"""
    pass

class MeshCoreTimeoutError(MeshCoreError):
    """Timeout waiting for acknowledgments or responses"""
    pass
```

**Exception Handling Policy**:
- Catch narrowest possible exceptions at each layer
- USB layer catches `serial.SerialException` and converts to `MeshCoreUSBError`
- Protocol layer catches formatting errors and converts to `MeshCoreProtocolError`
- Transport engine only catches `MeshCoreError` and subclasses
- Use broad `Exception` catches only in main transport loop with clear justification

## Testing Strategy

### Hardware Testing
- Real MeshCore nodes for integration testing
- Multi-node mesh network scenarios
- Solar power and Pi Zero performance validation

### Mock Testing
- Complete USB interface mocking for unit tests
- Simulated packet loss and delay scenarios
- Protocol edge case testing without hardware dependency

### Automated Testing
- Unit tests for all packet management operations
- Integration tests for session management
- Performance tests for Pi Zero constraints
- Security tests for encryption and authentication

## Development Guidelines

### Code Organization
```
citadel/transport/engines/meshcore/
├── __init__.py
├── engine.py              # Main MeshCoreTransportEngine
├── usb_interface.py       # USB communication layer
├── packet_manager.py      # Message chunking and acks
├── session_integration.py # SessionManager extensions
├── advert_collector.py    # Network discovery
├── config.py             # Configuration management
├── exceptions.py         # Exception hierarchy
└── mock_interface.py     # Hardware mocking for tests
```

### Coding Standards
- Follow PEP 8 and existing mesh-citadel patterns
- Use type hints throughout
- Comprehensive docstrings for all public methods
- Async/await patterns following CLI engine model
- Configuration via dataclasses matching existing engines

### Performance Considerations
- Minimize memory allocations (Pi Zero has 512MB RAM)
- Efficient packet queuing and cleanup
- Database query optimization for limited storage
- CPU usage monitoring and optimization

## Risk Assessment

### High Priority Risks
1. **MeshCore USB Protocol Complexity**: Unknown protocol details could require major architecture changes
2. **Packet Size Constraints**: Real-world overhead might be higher than estimated
3. **Reliability Issues**: LoRa mesh routing may be less reliable than assumed
4. **Performance Limitations**: Pi Zero + solar power may struggle with processing requirements

### Mitigation Strategies
1. **Thorough Protocol Research**: Complete MeshCore documentation review before coding
2. **Conservative Size Estimates**: Start with smaller packet assumptions, optimize later
3. **Robust Retry Logic**: Design for high packet loss scenarios from the start
4. **Performance Profiling**: Regular testing on actual Pi Zero hardware

### Medium Priority Risks
1. **Database Growth**: Advert collection could consume excessive storage
2. **Session Management Complexity**: Multi-node scenarios may complicate authentication
3. **Configuration Complexity**: Too many options could confuse users

## Success Criteria

### Minimum Viable Product (MVP)
- [ ] Send and receive direct messages between two nodes
- [ ] Basic user authentication and session management
- [ ] Message chunking and reassembly for messages > packet size
- [ ] Reliable acknowledgment and retry mechanism
- [ ] Integration with existing mesh-citadel user interface

### Full Feature Set
- [ ] Complete BBS functionality (rooms, messaging, user management)
- [ ] Advert collection and node discovery
- [ ] Performance optimization for solar-powered operation
- [ ] Comprehensive error handling and recovery
- [ ] Production-ready configuration and deployment

### Performance Targets
- [ ] Message delivery within 2 minutes under normal conditions
- [ ] Support for 50+ concurrent users on mesh network
- [ ] <10% CPU usage on Pi Zero during normal operation
- [ ] 24-hour operation on typical solar power setup

## Next Steps

1. **Complete Protocol Research**: Thoroughly document MeshCore USB protocol
2. **Database Architecture Decision**: Choose between main vs separate database
3. **Create Project Structure**: Set up directory structure and initial files
4. **Implement Phase 1**: USB interface and basic packet operations

## Questions for Resolution

1. **Database Architecture**: Main database with `mc_*` tables or separate `meshcore.db`?
2. **Advert Storage Policy**: Should we collect non-user node adverts initially?
3. **Path Specification**: Does MeshCore firmware handle path reversal automatically?
4. **Multi-Node Support**: How should TransportManager handle multiple meshcore engines?
5. **Testing Hardware**: What's the minimum hardware setup needed for development testing?

---

This document should be updated as implementation progresses and new information becomes available. All architectural decisions should be documented with clear rationale to help future developers understand the design choices.