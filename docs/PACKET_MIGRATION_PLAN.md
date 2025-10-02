# Packet Type Migration Implementation Plan

## Overview
Migration from current response types (`CommandResponse`, `MessageResponse`, `ErrorResponse`) to unified packet system (`ToUser`, `FromUser`) with proper error boundary separation.

## Error Boundary Clarification

### Transport Layer Responsibilities:
- Command parsing errors → Handle locally, re-prompt user
- Input validation (format, length, options) → Handle locally, re-prompt user
- Session creation/connection issues → Handle locally
- Multi-line input collection (message entry) → Handle locally until terminator

### BBS Layer Responsibilities:
- Business logic errors (user doesn't exist, permission denied)
- Workflow validation (password requirements, username conflicts)
- System state errors (room full, user blocked)

**Key Principle:** Transport only sends valid `BaseCommand` objects to BBS. All command parsing happens in transport layer.

## Updated Packet Structures

### ToUser (Updated)
```python
@dataclass
class ToUser:
    session_id: str
    text: str
    hints: Dict[str, Any] = field(default_factory=dict)
    message: Optional[MessageResponse] = None
    is_error: bool = False
    error_code: Optional[str] = None
```

## Phase 1: Update Packet Structures

### 1.1 Update ToUser Definition
**File:** `citadel/transport/packets.py`
- **Lines 16-21**: Add error fields to `ToUser`:
  ```python
  @dataclass
  class ToUser:
      session_id: str
      text: str
      hints: Dict[str, Any] = field(default_factory=dict)
      message: Optional[MessageResponse] = None
      is_error: bool = False
      error_code: Optional[str] = None
  ```

### 1.2 Update Input Validator
**File:** `citadel/transport/validator.py`
- **Lines 25-30**: Change return type from `Optional[ErrorResponse]` to `Optional[ToUser]`
- **Lines 31-36**: Return `ToUser` error packets:
  ```python
  def validate(self, packet: FromUser) -> Optional[ToUser]:
      session_state = self.session_manager.validate_session(packet.session_id)
      if not session_state:
          return ToUser(
              session_id=packet.session_id,
              text="Session expired. Please reconnect.",
              is_error=True,
              error_code="invalid_session"
          )
  ```
- **Lines 45-52**: Update transport error returns to `ToUser` format
- **Lines 60-67**: Update payload validation error returns to `ToUser` format

## Phase 2: Core Interface Foundation

### 2.1 Update Command Processor Interface
**File:** `citadel/commands/processor.py`
- **Lines 27-31**: Change `process()` signature from:
  ```python
  async def process(self, session_id: str, command) -> CommandResponse | MessageResponse:
  ```
  to:
  ```python
  async def process(self, packet: FromUser) -> ToUser:
  ```
- **Lines 27-34**: Add input validation at method start:
  ```python
  # Validate input packet
  validation_error = self.validator.validate(packet)
  if validation_error:
      return validation_error  # Already a ToUser error packet
  ```
- **Line 18**: Add validator initialization:
  ```python
  from citadel.transport.validator import InputValidator
  self.validator = InputValidator(session_mgr)
  ```
- **Throughout method**: Convert all `ErrorResponse` returns to `ToUser` error format

### 2.2 Update Base Command Interface
**File:** `citadel/commands/base.py`
- **Line 99**: Change `run()` signature from:
  ```python
  async def run(self, context: CommandContext) -> "CommandResponse | MessageResponse | list[MessageResponse]":
  ```
  to:
  ```python
  async def run(self, context: CommandContext) -> "ToUser | list[ToUser]":
  ```

## Phase 3: Workflow System Updates

### 3.1 Update Workflow Base Class
**File:** `citadel/workflows/base.py`
- Update `handle()` method signature to return `ToUser`
- Remove `WorkflowPrompt` embedding logic

### 3.2 Update Registration Workflow
**File:** `citadel/workflows/register_user.py`
- **Lines 46-49**: Convert `ErrorResponse` to `ToUser` error format:
  ```python
  # FROM:
  return ErrorResponse(
      code="invalid_username",
      text="Usernames are limited to ASCII characters only"
  )

  # TO:
  return ToUser(
      session_id=session_id,
      text="Usernames are limited to ASCII characters only",
      is_error=True,
      error_code="invalid_username"
  )
  ```
- **Lines 62-70**: Convert `CommandResponse` with `WorkflowPrompt` to `ToUser`:
  ```python
  # FROM:
  return CommandResponse(
      success=True,
      code="workflow_prompt",
      payload=WorkflowPrompt(
          workflow=self.kind,
          step=2,
          prompt="Choose a display name."
      ).__dict__
  )

  # TO:
  return ToUser(
      session_id=session_id,
      text="Choose a display name.",
      hints={"type": "text", "workflow": self.kind, "step": 2}
  )
  ```
- **Apply similar changes to all workflow steps** (lines ~80, ~110, ~140, ~160, ~190)
- **All error cases**: Convert to `ToUser` error format

### 3.3 Update Login Workflow
**File:** `citadel/workflows/login.py`
- Similar `CommandResponse` → `ToUser` conversions throughout
- Update all error responses to `ToUser` error format

### 3.4 Update Other Workflows
**File:** `citadel/workflows/validate_users.py`
- Convert response types to `ToUser` and `ToUser` error format

## Phase 4: Command System Updates

### 4.1 Update All Builtin Commands
**File:** `citadel/commands/builtins.py`
- **Throughout file**: Update all command `run()` methods to return `ToUser`
- **Message display commands**: Convert `MessageResponse` to embedded message in `ToUser`:
  ```python
  # FROM:
  return MessageResponse(id=msg.id, sender=msg.sender, ...)

  # TO:
  return ToUser(
      session_id=context.session_id,
      text="",  # Or summary text
      message=MessageResponse(id=msg.id, sender=msg.sender, ...)
  )
  ```
- **Error conditions**: Convert to `ToUser` error format

### 4.2 Update Permission Checker
**File:** `citadel/auth/checker.py`
- Update `permission_denied()` function to return `ToUser` error instead of `ErrorResponse`

## Phase 5: Transport Layer Overhaul

### 5.1 Update CLI Transport Engine
**File:** `citadel/transport/engines/cli.py`

#### 5.1.1 Input Processing with Local Error Handling
- **Lines 190-230**: Replace current command processing with robust input handling:
  ```python
  async def _process_command(self, command_line: str, session_id: Optional[str], client_id: int) -> ToUser:
      # Handle command parsing locally - never send bad commands to BBS
      try:
          if session_id and self.session_manager.get_workflow(session_id):
              # In workflow - validate response locally if needed
              if not command_line.strip():
                  # Re-prompt for empty input
                  return ToUser(
                      session_id=session_id,
                      text="Please enter a response.",
                      is_error=True,
                      error_code="empty_input"
                  )

              packet = FromUser(
                  session_id=session_id,
                  payload=command_line.strip(),
                  payload_type=FromUserType.WORKFLOW_RESPONSE
              )
          else:
              # Parse command - handle errors locally
              command = self.text_parser.parse_command(command_line)
              if isinstance(command, ErrorResponse):  # Parser returned error
                  # Handle locally, don't send to BBS
                  return ToUser(
                      session_id=session_id,
                      text=command.text,
                      is_error=True,
                      error_code="invalid_command"
                  )

              packet = FromUser(
                  session_id=session_id or "anonymous",
                  payload=command,
                  payload_type=FromUserType.COMMAND
              )

          # Only send valid packets to BBS
          return await self.command_processor.process(packet)

      except Exception as e:
          # Transport-level error - handle locally
          logger.error(f"Transport error processing '{command_line}': {e}")
          return ToUser(
              session_id=session_id or "anonymous",
              text="Internal error processing command.",
              is_error=True,
              error_code="transport_error"
          )
  ```

#### 5.1.2 Output Processing
- **Lines 150-170**: Update response handling to process `ToUser` packets:
  ```python
  async def _handle_response(self, to_user: ToUser, writer: StreamWriter):
      # Handle error formatting
      if to_user.is_error:
          response_text = f"ERROR: {to_user.text}"
      else:
          response_text = to_user.text

      # Handle embedded message
      if to_user.message:
          response_text += f"\n[Message from {to_user.message.sender}]\n{to_user.message.content}"

      # Handle hints for special input types
      hints = to_user.hints
      if hints.get("type") == "password":
          response_text += "\n(Password input - characters will not be displayed)"
      elif hints.get("options"):
          options_text = "/".join(hints["options"])
          default = hints.get("default")
          if default:
              response_text += f"\n({options_text}) [Default: {default}]: "
          else:
              response_text += f"\n({options_text}): "

      writer.write(f"{response_text}\n".encode('utf-8'))
      await writer.drain()
  ```

#### 5.1.3 Session Management
- **Lines 140-180**: Remove manual session_id handling - delegate to session manager
- **Lines 190-200**: Remove `__workflow:login:` special handling - move to proper command

### 5.2 Update Text Parser Error Handling
**File:** `citadel/transport/parser.py`
- **Lines 28-32**: Ensure parser returns `ErrorResponse` for malformed commands (handled by transport)
- **Lines 40-45**: Add better error messages for unknown commands
- Transport layer will catch these and handle locally

## Phase 6: Supporting Updates

### 6.1 Session Manager Enhancements
**File:** `citadel/session/manager.py`
- Add `create_provisional_session()` method if not exists
- Ensure session state tracking is robust for anonymous users

### 6.2 Create Enter Message Workflow
**File:** `citadel/workflows/enter_message.py` (new)
- Implement message entry workflow with terminator handling
- Handle conditional recipient step for Mail room
- Return `ToUser` packets with appropriate hints

### 6.3 Remove/Deprecate Old Response Types
**File:** `citadel/commands/responses.py`
- Keep `MessageResponse` (still used embedded in `ToUser`)
- Add deprecation warnings to `CommandResponse` and `ErrorResponse`

## Phase 7: Test Updates

### 7.1 Update All Tests
**Files:** `tests/test_*.py` (all test files)
- Update test expectations from old response types to `ToUser`
- Update mock objects and assertions
- Test `FromUser` packet validation
- Test transport-level error handling

## Implementation Order

1. **Phase 1** - Update packet structures and validator
2. **Phase 2** - Core interfaces (breaks everything, but establishes foundation)
3. **Phase 3** - Workflows (enables workflow functionality)
4. **Phase 4** - Commands (enables command functionality)
5. **Phase 5** - Transport layer (enables end-to-end flow)
6. **Phase 6** - Supporting changes
7. **Phase 7** - Test fixes

## Risk Mitigation

- After Phase 2: System will be completely broken until Phase 5 complete
- Recommend implementing Phases 1-5 in single development session
- Keep git commits granular for easier rollback
- Test basic functionality after each phase

## Success Criteria

- [ ] User can connect and get session
- [ ] Invalid commands handled gracefully by transport (no BBS errors)
- [ ] User can run basic commands
- [ ] User can complete registration workflow with proper error handling
- [ ] User can complete login workflow
- [ ] Transport validation catches malformed packets
- [ ] BBS-level errors properly formatted as `ToUser` error packets
- [ ] All tests pass

## Key Validation Points

1. **Transport Error Boundary**: Malformed commands never reach BBS layer
2. **BBS Error Handling**: All business logic errors return `ToUser` error packets
3. **Packet Consistency**: All BBS → Transport communication uses `ToUser`
4. **Input Validation**: `FromUser` packets are validated before processing
5. **Error User Experience**: Errors are clearly formatted and actionable