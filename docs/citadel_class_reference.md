# Citadel Class Reference Map

Quick reference for classes and their public methods/attributes in the citadel codebase.

## 🔐 `citadel/auth/`

### Functions
- `is_allowed(action: str, user, room=None) -> bool` - citadel/auth/checker.py:8
- `permission_denied(action: str, user, room=None)` - citadel/auth/checker.py:43

### Classes
- `PermissionLevel(IntEnum)` - citadel/auth/permissions.py:5
  - `UNVERIFIED = 0`
  - `TWIT = 1`
  - `USER = 2`
  - `AIDE = 3`
  - `SYSOP = 4`

- `PermissionInfo` - citadel/auth/permissions.py:14
  - `level: PermissionLevel`
  - `description: str`

### Constants
- `ACTION_REQUIREMENTS` - citadel/auth/permissions.py:21 (maps actions to permission requirements)

## 🗄️ `citadel/db/`

### Classes
- `DatabaseManager` - citadel/db/manager.py:11
  - `__init__(config)`
  - `start()`
  - `reset()` (classmethod)
  - `execute(query: str, params: tuple, callback: Optional[Callable])`
  - `shutdown()`

### Functions
- `initialize_database(db_manager, config=None)` - citadel/db/initializer.py:7
- `initialize_system_rooms(db_manager, config)` - citadel/db/initializer.py:104

## 💬 `citadel/message/`

### Classes
- `MessageManager` - citadel/message/manager.py:11
  - `__init__(config, db_manager)`
  - `post_message(sender: str, content: str, recipient: Optional[str]) -> int`
  - `get_message(message_id: int, recipient_user: Optional[User]) -> Optional[dict]`
  - `delete_message(message_id: int) -> bool`
  - `get_messages(message_ids: list[int], recipient_user: Optional[User]) -> list[dict]`
  - `get_message_summary(message_id: int) -> Optional[str]`

### Exceptions
- `MessageError` - citadel/message/errors.py:1
- `InvalidContentError(MessageError)` - citadel/message/errors.py:5
- `InvalidRecipientError(MessageError)` - citadel/message/errors.py:9

## 🏠 `citadel/room/`

### Classes
- `SystemRoomIDs` - citadel/room/room.py:14
  - `LOBBY_ID = 1`
  - `MAIL_ID = 2`
  - `AIDES_ID = 3`
  - `SYSOP_ID = 4`
  - `SYSTEM_ID = 5`
  - `TWIT_ID = 6`
  - `as_set()` (classmethod)

- `Room` - citadel/room/room.py:27
  - `__init__(db, config, identifier: int | str)`
  - `load(force=False)`
  - `get_id_by_name(name: str) -> int`

  **Permissions:**
  - `can_user_read(user: User) -> bool`
  - `can_user_post(user: User) -> bool`

  **Ignore management:**
  - `is_ignored_by(user: User) -> bool`
  - `ignore_for_user(user: User)`
  - `unignore_for_user(user: User)`

  **Navigation:**
  - `go_to_next_room(user: User, with_unread: bool) -> Room | None`
  - `go_to_previous_room(user: User) -> Room | None`
  - `has_unread_messages(user: User) -> bool`
  - `get_room_id(identifier: int | str) -> int`
  - `go_to_room(identifier: int | str) -> Room`

  **Message handling:**
  - `get_message_ids() -> list[int]`
  - `get_oldest_message_id() -> int | None`
  - `get_newest_message_id() -> int | None`
  - `post_message(sender: str, content: str) -> int`
  - `get_next_unread_message(user: User) -> dict | None`
  - `skip_to_latest(user: User)`

  **Room management:**
  - `insert_room_between()` (classmethod)
  - `delete_room(sys_user: str)`
  - `initialize_room_order()` (classmethod)

### Exceptions
- `RoomError` - citadel/room/errors.py:1
- `RoomNotFoundError(RoomError)` - citadel/room/errors.py:5
- `PermissionDeniedError(RoomError)` - citadel/room/errors.py:9

## 🔑 `citadel/session/`

### Classes
- `SessionManager` - citadel/session/manager.py:13
  - `__init__(config, db)`
  - `create_session_state(username: str) -> SessionState`
  - `create_session(username: str) -> str`
  - `validate_session(token: str) -> SessionState | None`
  - `touch_session(token: str) -> bool`
  - `expire_session(token: str) -> bool`
  - `sweep_expired_sessions()`
  - `get_username(token: str) -> str | None`
  - `get_current_room(token: str) -> str | None`
  - `set_current_room(token: str, room: str)`
  - `get_workflow(token: str) -> WorkflowState | None`
  - `set_workflow(token: str, wf: WorkflowState)`
  - `clear_workflow(token: str)`

- `SessionState` - citadel/session/state.py:15
  - `username: str`
  - `current_room: Optional[str]`
  - `workflow: Optional[WorkflowState]`

- `WorkflowState` - citadel/session/state.py:8
  - `kind: str`
  - `step: int`
  - `data: Dict[str, Any]`

## 👤 `citadel/user/`

### Classes
- `User` - citadel/user/user.py:12
  - `__init__(db_manager, username: str)`
  - `load(force=False)`
  - `create()` (classmethod)

  **Properties:**
  - `display_name`
  - `permission`
  - `last_login`
  - `password_hash`
  - `salt`

  **Setters:**
  - `set_display_name(new_name: str)`
  - `set_permission(new_permission: str)`
  - `set_last_login(timestamp)`
  - `update_password(new_hash: str, new_salt: bytes)`

  **User blocking:**
  - `block_user(target_username: str)`
  - `unblock_user(target_username: str)`
  - `is_blocked(sender_username: str) -> bool`

### Constants
- `PERMISSIONS = {"unverified", "twit", "user", "aide", "sysop"}` - citadel/user/user.py:9

## 🔄 `citadel/workflows/`

### Classes
- `Workflow` - citadel/workflows/base.py:6
  - `kind: str`
  - `handle(processor, token, state, command, wf_state)` (abstract)

- `ValidateUsersWorkflow(Workflow)` - citadel/workflows/validate_users.py:9
  - `kind = "validate_users"`
  - `handle(processor, token, state, command, wf_state)`

### Functions
- `register(workflow_cls)` - citadel/workflows/registry.py:6
- `get(kind: str)` - citadel/workflows/registry.py:13
- `all_workflows()` - citadel/workflows/registry.py:17

---

*Generated for working with citadel/commands/process.py module*