# Mesh-Citadel Architecture & Design Document

## Project Overview

Mesh-Citadel is a modern, efficient bulletin board system (BBS) inspired by the Citadel BBS of the 1980s, designed for low-bandwidth, resource-constrained environments (such as a Raspberry Pi Zero running on solar power). Its initial transport protocol is MeshCore Room Server over USB serial, but the system is architected to support additional protocols via a plugin system.

All code will follow strict PEP8 standards, prioritize code quality, and minimize external dependencies. The project is test-driven, with lightweight and flexible tests using Pytest.

## Design Principles

- **Efficiency:** Suitable for low-power, low-bandwidth hardware.
- **Extensibility:** Modular and plugin-friendly, especially in transport.
- **Security:** Balanced with MeshCore’s trusted environment and practical constraints.
- **Configurability:** Limits and options set via YAML config; restart required for changes.
- **Testability:** TDD approach, Pytest for tests, realistic security/attack simulations.
- **Independence:** No Internet required for core features.

## System Limits (Configurable)

- **Max messages per room:** Default 300
- **Max rooms:** Default 50
- **Max users:** Default 300
- **Change requires restart.**
- All limits set in YAML config file.

## Subsystems

### 1. Rooms Subsystem

- **Data Tracked:**  
  - Room ID (int), Name (str), Description (str)
  - Last-read message per user/room
  - Messages (see Messages subsystem)
  - Room state (read-only/read-write)
- **Features:**  
  - Create, update, delete, reorder rooms (Aides+)
  - Export messages on deletion (format: CSV, JSON, YAML; default off)
  - Relational SQL schema—rooms, messages, user markers linked via keys
- **Room order:** Editable by Aides, stored in DB

### 2. Authentication & User Management

- **Users:**  
  - Username (MeshCore node ID for MeshCore users)
  - Display name
  - Hashed password (PBKDF2), password salt
  - Last login, permission level, block list
- **Password Recovery:**  
  - Sysop can reset
  - User answers a “safe” recovery question (configurable set)
  - Recovery via DM if available
- **Permissions:**  
  - Twit, User, Aide, Sysop
- **Block Lists:**  
  - One-way: Blocker cannot see blockee’s messages; blockee is unaware
  - Blocked messages are marked and sent to transport layer for presentation

### 3. Sessions Subsystem

- **Tracks:**  
  - Username, session start, last activity, current room, session state
- **Rules:**  
  - One session per user/node
  - Time-out inactive sessions
  - Remove session on logout

### 4. Messages Subsystem

- **Circular buffer per room** (max messages per room)
- **Message Fields:**  
  - ID, sender, recipient (for private), contents, timestamp, associated room
  - Marked if sender is blocked for current user
- **Actions:**  
  - Create, retrieve, delete messages
  - Blocked status included in message structure

### 5. Database Subsystem

- **SQLite (default), abstraction for future engines**
- **Thread-safe, single connection manager**
- **Queue writes, lock on write**
- **Interface for arbitrary SQL from BBS subsystems**

### 6. User Interaction Subsystem

- **Executes sanitized user commands from protocol layer**
- **Provides menus, hints, message input**
- **Command Structure:**  
  - Citadel-style single-character commands (G, E, R, N, L, Q, S, C, H, M, W, D)
  - Whole-word commands for admin (CREATE, ROOM, USER)
- **Interaction:**  
  - Output as data structures for protocol layer
  - Minimal DB interaction

### 7. Configuration Subsystem

- **YAML config file, runtime reloadable**
- **Options:**  
  - System name, room/message/user limits, mail limits, starting room
  - Auth: session timeout, max password/username length
  - Transport: serial port, baud rate
  - Database: path(s)
  - Logging: level, file path
  - Export format options
  - Recovery questions set

### 8. Transport Domain

- **Plugin architecture for multiple protocols**
- **Initial implementation:** MeshCore Room Server over USB serial
- **Responsibilities:**  
  - Parse incoming commands/data, present BBS output to user
  - Async, scalable for 10–20 users/hour, up to hundreds with lag
  - Node ID as username for MeshCore
  - Flexible for future protocol evolution

### 9. CLI Interfaces

- **User Console:**  
  - Mimics MeshCore interface, uses protocol plugin
- **Admin CLI:**  
  - Verbose, host access only, no password required
  - Reports usage, alters config, performs admin actions

### 10. Logging

- **Log Levels:** DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Configurable file path, rotation/archiving options**

### 11. Security & Testing

- **Security:**  
  - MeshCore encryption/trust assumed
  - SQL injection, buffer overflow, encoding attacks tested
  - No unnecessary over-engineering beyond MeshCore’s protection
- **Testing:**  
  - Pytest, realistic attack simulations
  - Flexible, lightweight tests (avoid fragility/complexity)

## Data Export

- **Room/message export format:** Configurable (CSV, JSON, YAML)
- **Option set in YAML config**

## Password Hashing

- **PBKDF2 (via Python’s standard library)**
- **Configurable iterations for future hardware**

## Future Considerations

- Networking/linking between BBS instances
- Advanced authentication (PKI, 2FA)
- Door games/external processes

## References

- MeshCore Room Server Protocol documentation: [MeshCore Repo](https://github.com/meshcore-dev/MeshCore)

## Open Questions

- Any additional features or constraints to clarify?
- Preferred data structures/interfaces for plugins?
- Any further security or administrative features needed?

---

_Last updated: 2025-09-16_