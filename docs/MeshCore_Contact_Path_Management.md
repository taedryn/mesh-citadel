# MeshCore Contact Path Management Guide

This document explains how to examine and modify contact routing paths using meshcore_py.

## Understanding Contacts

A **contact** in meshcore_py is a dictionary representing a node in the mesh network:

```python
contact = {
    "public_key": "abc123...",     # 64-character hex string (32 bytes)
    "out_path": "fedcba9876...",   # Hex string representing the routing path
    "out_path_len": 6,             # Length of the path in bytes (-1 means flood/no path)
    "adv_name": "NodeName",        # Human-readable name
    "type": 1,                     # Contact type
    "flags": 0,                    # Contact flags
    "last_advert": 1234567890,     # Timestamp of last advertisement
    "adv_lat": 40.7128,           # Latitude (if available)
    "adv_lon": -74.0060           # Longitude (if available)
}
```

### Path Format

- **`out_path`**: Hex string where each 6 bytes (12 hex characters) represents a node's address
- **`out_path_len`**: Number of bytes in the path, or -1 for flood mode (no specific path)
- **Maximum path length**: 64 bytes (128 hex characters)

Example path breakdown:
```python
out_path = "fedcba987654321098765432"
# This represents a 3-hop path:
# Hop 1: fedcba987654
# Hop 2: 321098765432
# Hop 3: (would be next 12 chars if present)
```

## Getting Contacts

### Method 1: Direct Command
```python
from meshcore import EventType

result = await meshcore.commands.get_contacts()
if result.type == EventType.ERROR:
    print(f"Error: {result.payload}")
else:
    contacts = result.payload  # Dict[str, contact]
    for key, contact in contacts.items():
        print(f"{contact['adv_name']}: {contact['public_key']}")
```

### Method 2: Using MeshCore Convenience Methods
```python
# Fetches contacts if needed and caches them locally
await meshcore.ensure_contacts()
contacts = meshcore.contacts  # Dict[str, contact] - cached locally

# Access individual contacts
for key, contact in contacts.items():
    print(f"Contact: {contact['adv_name']}")
    print(f"Path: {contact['out_path']}")
    print(f"Path length: {contact['out_path_len']}")
```

### Finding Specific Contacts

```python
# Find by human-readable name
contact = meshcore.get_contact_by_name("NodeName")

# Find by public key prefix (minimum 6 characters)
contact = meshcore.get_contact_by_key_prefix("abc123")

if contact:
    print(f"Found: {contact['adv_name']}")
else:
    print("Contact not found")
```

## Examining Paths

### Basic Path Information
```python
if contact:
    current_path = contact["out_path"]        # Hex string like "fedcba987654"
    path_length = contact["out_path_len"]     # Number of bytes in path

    print(f"Contact: {contact['adv_name']}")
    print(f"Raw path: {current_path}")
    print(f"Path length: {path_length} bytes")

    if path_length == -1:
        print("Using flood mode (no specific path)")
```

### Parsing Path into Hops
```python
def parse_path(path_hex):
    """Convert hex path string into list of hop addresses"""
    if not path_hex:
        return []

    path_bytes = bytes.fromhex(path_hex)
    hops = []

    # Each hop is 6 bytes (12 hex characters)
    for i in range(0, len(path_bytes), 6):
        hop = path_bytes[i:i+6].hex()
        hops.append(hop)

    return hops

# Usage
if contact:
    hops = parse_path(contact["out_path"])
    print(f"Path hops: {hops}")
    if hops:
        print(f"First hop: {hops[0]}")
        print(f"Number of hops: {len(hops)}")
```

## Modifying Paths

### Update Contact Path
```python
# Method 1: Using change_contact_path (recommended)
new_path = "123456789abc" + contact["out_path"]  # Prepend new hop
result = await meshcore.commands.change_contact_path(contact, new_path)

# Method 2: Using update_contact with explicit path
result = await meshcore.commands.update_contact(contact, path=new_path)

# Check result
if result.type == EventType.ERROR:
    print(f"Error updating path: {result.payload}")
else:
    print("Path updated successfully")
```

### Adding a First Hop
```python
def add_first_hop(contact, new_first_hop):
    """
    Add a node as the first hop if it's not already there.

    Args:
        contact: Contact dictionary
        new_first_hop: 6-byte hex string (12 characters)

    Returns:
        tuple: (new_path, changed) where changed is True if path was modified
    """
    current_path = contact["out_path"]
    new_first_hop = new_first_hop.lower()

    # Check if new_first_hop is already the first hop
    if current_path.startswith(new_first_hop):
        return current_path, False  # No change needed

    # Add the new hop at the beginning
    new_path = new_first_hop + current_path

    # Truncate if too long (max 64 bytes = 128 hex chars)
    if len(new_path) > 128:
        new_path = new_path[:128]

    return new_path, True

# Usage
new_path, changed = add_first_hop(contact, "123456789abc")
if changed:
    result = await meshcore.commands.change_contact_path(contact, new_path)
    if result.type == EventType.ERROR:
        print(f"Error: {result.payload}")
    else:
        print("Successfully added first hop")
else:
    print("First hop already present")
```

## Complete Example: Path Management Function

```python
async def manage_contact_path(meshcore, contact_identifier, new_first_hop):
    """
    Add a node as the first hop in a contact's path if it's not already there.

    Args:
        meshcore: MeshCore instance
        contact_identifier: Contact name or public key prefix
        new_first_hop: 6-byte hex string (12 characters) of the node to add

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Ensure we have contacts
        await meshcore.ensure_contacts()

        # Find the contact
        if len(contact_identifier) >= 12:  # Looks like a key prefix
            contact = meshcore.get_contact_by_key_prefix(contact_identifier)
        else:  # Treat as name
            contact = meshcore.get_contact_by_name(contact_identifier)

        if not contact:
            print(f"Contact '{contact_identifier}' not found")
            return False

        # Validate new_first_hop format
        if len(new_first_hop) != 12:
            print(f"Error: new_first_hop must be exactly 12 hex characters")
            return False

        # Validate hex string
        try:
            bytes.fromhex(new_first_hop)
        except ValueError:
            print(f"Error: new_first_hop must be a valid hex string")
            return False

        current_path = contact["out_path"]
        new_first_hop = new_first_hop.lower()

        # Check if new_first_hop is already the first hop
        if current_path.startswith(new_first_hop):
            print(f"Node {new_first_hop} is already the first hop for {contact['adv_name']}")
            return True

        # Add the new hop at the beginning
        new_path = new_first_hop + current_path

        # Truncate if too long (max 64 bytes = 128 hex chars)
        if len(new_path) > 128:
            old_hops = len(current_path) // 12
            new_hops = len(new_path[:128]) // 12
            new_path = new_path[:128]
            print(f"Warning: Path truncated from {old_hops + 1} to {new_hops} hops due to length limit")

        # Update the contact
        result = await meshcore.commands.change_contact_path(contact, new_path)
        if result.type == EventType.ERROR:
            print(f"Error updating path: {result.payload}")
            return False

        print(f"Successfully added {new_first_hop} as first hop for {contact['adv_name']}")
        return True

    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

# Usage examples:
# await manage_contact_path(meshcore, "NodeName", "123456789abc")
# await manage_contact_path(meshcore, "fedcba987654", "123456789abc")
```

## Additional Path Operations

### Remove First Hop
```python
def remove_first_hop(contact):
    """Remove the first hop from a contact's path"""
    current_path = contact["out_path"]
    if len(current_path) >= 12:
        new_path = current_path[12:]  # Remove first 12 characters (6 bytes)
        return new_path
    return ""  # Path becomes empty

# Usage
if contact:
    new_path = remove_first_hop(contact)
    result = await meshcore.commands.change_contact_path(contact, new_path)
```

### Clear Path (Set to Flood Mode)
```python
# Set path to empty and length to -1 (flood mode)
result = await meshcore.commands.change_contact_path(contact, "")
```

### Reset Path
```python
# Reset the path discovery for a contact
result = await meshcore.commands.reset_path(contact["public_key"])
if result.type == EventType.ERROR:
    print(f"Error resetting path: {result.payload}")
else:
    print("Path reset successfully - device will rediscover route")
```

## Best Practices

1. **Always validate hex strings**: Ensure hop addresses are exactly 12 hex characters
2. **Check path length limits**: Maximum 64 bytes (128 hex characters) total
3. **Handle errors gracefully**: Always check command results for errors
4. **Use contact lookup methods**: Prefer `get_contact_by_name()` for user-friendly interfaces
5. **Cache contacts**: Use `ensure_contacts()` and `meshcore.contacts` for efficiency
6. **Validate contact existence**: Always check if contact is found before modifying

## Command Reference

| Method | Purpose | Parameters | Returns |
|--------|---------|------------|---------|
| `get_contacts()` | Fetch all contacts | `lastmod: int` (optional) | `Event` with contacts payload |
| `ensure_contacts()` | Ensure contacts are cached | None | `bool` (True if fetched) |
| `get_contact_by_name()` | Find contact by name | `name: str` | `contact dict` or `None` |
| `get_contact_by_key_prefix()` | Find contact by key prefix | `prefix: str` (6+ chars) | `contact dict` or `None` |
| `change_contact_path()` | Update contact path | `contact: dict, path: str` | `Event` |
| `update_contact()` | Update contact (general) | `contact: dict, path: str, flags: int` | `Event` |
| `reset_path()` | Reset path discovery | `key: str/bytes/dict` | `Event` |

## Error Handling

Common error scenarios and handling:

```python
# Contact not found
if not contact:
    print("Contact not found - check name or key prefix")

# Command failed
if result.type == EventType.ERROR:
    error_code = result.payload.get("error_code")
    if error_code == 2:  # ERR_CODE_NOT_FOUND
        print("Contact not found on device")
    elif error_code == 6:  # ERR_CODE_ILLEGAL_ARG
        print("Invalid path format")
    else:
        print(f"Command failed: {result.payload}")

# Connection issues
try:
    await meshcore.commands.get_contacts()
except Exception as e:
    print(f"Connection error: {e}")
```