# MeshCore Error Codes Reference

This document describes the error codes returned by MeshCore companion radio commands when using meshcore_py or other interfaces.

## Error Code Definitions

The error codes are defined in `/MeshCore/examples/companion_radio/MyMesh.cpp:103-108`:

| Code | Constant | Meaning | Description |
|------|----------|---------|-------------|
| 1 | `ERR_CODE_UNSUPPORTED_CMD` | Unsupported command | Unknown or unsupported command received, unsupported text message types, or features not yet implemented |
| 2 | `ERR_CODE_NOT_FOUND` | Resource not found | Contact not found, invalid channel index, or resource lookup failures |
| 3 | `ERR_CODE_TABLE_FULL` | Table/queue is full | Message send queue is full, contact table is full, or data buffer overflow conditions |
| 4 | `ERR_CODE_BAD_STATE` | Invalid state for operation | Iterator is currently busy, invalid state for signing operations, or attempting operations when system isn't ready |
| 5 | `ERR_CODE_FILE_IO_ERROR` | File I/O error | File system operations failed or storage/persistence errors |
| 6 | `ERR_CODE_ILLEGAL_ARG` | Illegal argument provided | Invalid parameters such as coordinates, radio settings, transmission power values, or malformed command arguments |

## How Error Codes Are Generated

Error codes are sent through the `writeErrFrame()` method:

```cpp
void MyMesh::writeErrFrame(uint8_t err_code) {
  uint8_t buf[2];
  buf[0] = RESP_CODE_ERR;  // Response type indicating error
  buf[1] = err_code;       // The specific error code (1-6)
  _serial->writeFrame(buf, 2);
}
```

## Detailed Use Cases

### Error Code 1: ERR_CODE_UNSUPPORTED_CMD
**Common triggers:**
- Unknown command received
- Unsupported text message types
- Features not yet implemented (like flood messaging)
- Command format doesn't match expected structure

**Example scenarios:**
- Sending a command ID that doesn't exist
- Command length doesn't match expected format
- Using deprecated or removed commands

### Error Code 2: ERR_CODE_NOT_FOUND
**Common triggers:**
- Contact not found when trying to send messages
- Invalid channel index specified
- Resource lookup failures

**Example scenarios:**
- `reset_path()` called with unknown contact public key
- Trying to send message to non-existent contact
- Invalid channel specified in channel operations

### Error Code 3: ERR_CODE_TABLE_FULL
**Common triggers:**
- Message send queue is full
- Contact table is full
- Data buffer overflow conditions
- Unable to add new entries to tables

**Example scenarios:**
- Too many pending messages in queue
- Contact storage limit reached
- Signing data buffer exceeded maximum size

### Error Code 4: ERR_CODE_BAD_STATE
**Common triggers:**
- Iterator is currently busy when trying to start another operation
- Invalid state for signing operations
- Attempting operations when system isn't ready

**Example scenarios:**
- Calling `get_contacts()` while another contact iteration is active
- Starting signing operation without proper initialization
- System not properly initialized

### Error Code 5: ERR_CODE_FILE_IO_ERROR
**Common triggers:**
- File system operations failed
- Storage/persistence errors
- Data corruption or storage device issues

**Example scenarios:**
- Failed to save contacts to storage
- Corrupted configuration files
- Storage device not responding

### Error Code 6: ERR_CODE_ILLEGAL_ARG
**Common triggers:**
- Invalid geographic coordinates
- Invalid radio parameters (frequency, bandwidth, etc.)
- Invalid transmission power values
- Malformed command arguments

**Example scenarios:**
- Setting invalid GPS coordinates
- Radio frequency outside allowed range
- TX power exceeding maximum allowed value
- Invalid argument lengths or formats

## Architecture Context

These error codes are part of the serial communication protocol between companion devices (like smartphone apps using meshcore_py) and MeshCore firmware running on radio hardware.

When commands are sent to the radio:
1. Radio processes the command
2. Responds with either `RESP_CODE_OK` (success) or `RESP_CODE_ERR` + specific error code
3. The error codes provide specific information about what went wrong

## Troubleshooting Tips

- **Error 1**: Check command ID and format against latest MeshCore documentation
- **Error 2**: Verify contact exists and public key is correct
- **Error 3**: Wait for current operations to complete or reduce message frequency
- **Error 4**: Ensure proper initialization sequence and avoid concurrent operations
- **Error 5**: Check storage device and file system integrity
- **Error 6**: Validate all parameters are within expected ranges and formats

## Source Location

Error codes are defined and used in:
- **Definitions**: `/MeshCore/examples/companion_radio/MyMesh.cpp:103-108`
- **Implementation**: Throughout the `processCommandFrame()` method in same file
- **Response method**: `writeErrFrame()` in `/MeshCore/examples/companion_radio/MyMesh.cpp:117-122`