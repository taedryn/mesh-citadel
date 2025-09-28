# tests/test_help_command.py

import pytest
import pytest_asyncio
import tempfile
import os
from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.session.manager import SessionManager
from citadel.user.user import User
from citadel.commands.processor import CommandProcessor
from citadel.commands.builtins import HelpCommand, MenuCommand
from citadel.commands.registry import registry
from citadel.commands.base import CommandCategory
from citadel.commands.responses import CommandResponse
from citadel.auth.permissions import PermissionLevel


@pytest.fixture
def config():
    path = tempfile.NamedTemporaryFile(delete=False)
    local_config = Config()
    local_config.database['db_path'] = path.name
    yield local_config
    os.unlink(path.name)


@pytest_asyncio.fixture
async def setup_user_and_session(config):
    db = DatabaseManager(config)
    await db.start()
    await initialize_database(db, config)
    session_mgr = SessionManager(config, db)

    # Create test user
    await User.create(config, db, 'testuser', 'hash', 'salt', 'Test User')
    user = User(db, 'testuser')
    await user.load()
    await user.set_permission_level(PermissionLevel.USER)

    # Create session
    session_id = await session_mgr.create_session('testuser')

    yield db, session_mgr, session_id, user

    await db.shutdown()


def test_help_command_method_sharing():
    """Test that HelpCommand and MenuCommand share the same implementation."""
    assert hasattr(HelpCommand, 'run')
    assert hasattr(MenuCommand, 'run')
    assert HelpCommand.run == MenuCommand.run
    assert HelpCommand._build_category_menu == MenuCommand._build_category_menu
    assert HelpCommand._show_command_help == MenuCommand._show_command_help


def test_help_commands_are_implemented():
    """Test that both help commands are detected as implemented."""
    assert HelpCommand.is_implemented()
    assert MenuCommand.is_implemented()


def test_command_categorization():
    """Test that commands are properly categorized."""
    all_commands = registry.available()

    # Count by category
    categories = {}
    implemented = {}

    for cmd_class in all_commands.values():
        cat = cmd_class.category
        categories[cat] = categories.get(cat, 0) + 1
        if cmd_class.is_implemented():
            implemented[cat] = implemented.get(cat, 0) + 1

    # Verify we have commands in each expected category
    assert CommandCategory.COMMON in categories
    assert CommandCategory.UNCOMMON in categories
    assert CommandCategory.UNUSUAL in categories
    assert CommandCategory.AIDE in categories
    assert CommandCategory.SYSOP in categories

    # Verify we have some implemented commands
    assert implemented.get(CommandCategory.COMMON, 0) > 0
    print(f"\nCommand distribution:")
    for cat in CommandCategory:
        total = categories.get(cat, 0)
        impl = implemented.get(cat, 0)
        print(f"  {cat.name}: {impl}/{total} implemented")


def test_common_commands_detection():
    """Test detection of implemented common commands."""
    all_commands = registry.available()

    common_implemented = []
    for cmd_class in all_commands.values():
        if cmd_class.category == CommandCategory.COMMON and cmd_class.is_implemented():
            common_implemented.append((cmd_class.code, cmd_class.short_text))

    # Sort by command code
    common_implemented.sort()

    print(f"\nImplemented COMMON commands:")
    for code, short_text in common_implemented:
        print(f"  {code} - {short_text}")

    # We should have at least a few implemented common commands
    assert len(common_implemented) >= 4  # G, E, N, Q, H at minimum


@pytest.mark.asyncio
async def test_help_menu_generation(setup_user_and_session):
    """Test dynamic help menu generation."""
    db, session_mgr, session_id, user = setup_user_and_session
    config = Config()
    processor = CommandProcessor(config, db, session_mgr)

    # Create help command
    help_cmd = HelpCommand(username='testuser', args={})

    # Process the command
    response = await processor.process(session_id, help_cmd)

    assert isinstance(response, CommandResponse)
    assert response.success
    assert response.code == "help_menu"
    assert "Common Commands:" in response.text
    assert response.payload["category"] == "common"
    assert response.payload["has_more"] is True

    print(f"\nGenerated help menu:")
    print(response.text)


@pytest.mark.asyncio
async def test_specific_command_help(setup_user_and_session):
    """Test detailed help for specific commands."""
    db, session_mgr, session_id, user = setup_user_and_session
    config = Config()
    processor = CommandProcessor(config, db, session_mgr)

    # Test help for a specific implemented command
    help_cmd = HelpCommand(username='testuser', args={"command": "G"})
    response = await processor.process(session_id, help_cmd)

    assert isinstance(response, CommandResponse)
    assert response.success
    assert response.code == "command_help"
    assert "G - " in response.text
    assert "Go to the next room" in response.text

    print(f"\nDetailed help for 'G' command:")
    print(response.text)


@pytest.mark.asyncio
async def test_unimplemented_command_help(setup_user_and_session):
    """Test help for unimplemented commands."""
    db, session_mgr, session_id, user = setup_user_and_session
    config = Config()
    processor = CommandProcessor(config, db, session_mgr)

    # Test help for an unimplemented command
    help_cmd = HelpCommand(username='testuser', args={"command": "D"})
    response = await processor.process(session_id, help_cmd)

    assert isinstance(response, CommandResponse)
    assert response.success
    assert response.code == "command_help"
    assert "D - " in response.text
    assert "(Not yet implemented)" in response.text

    print(f"\nHelp for unimplemented 'D' command:")
    print(response.text)


@pytest.mark.asyncio
async def test_unknown_command_help(setup_user_and_session):
    """Test help for unknown commands."""
    db, session_mgr, session_id, user = setup_user_and_session
    config = Config()
    processor = CommandProcessor(config, db, session_mgr)

    # Test help for unknown command
    help_cmd = HelpCommand(username='testuser', args={"command": "Z"})
    response = await processor.process(session_id, help_cmd)

    assert isinstance(response, CommandResponse)
    assert not response.success
    assert response.code == "unknown_command"
    assert "Unknown command: Z" in response.text


@pytest.mark.asyncio
async def test_menu_command_works_same_as_help(setup_user_and_session):
    """Test that MenuCommand (?) works identically to HelpCommand (H)."""
    db, session_mgr, session_id, user = setup_user_and_session
    config = Config()
    processor = CommandProcessor(config, db, session_mgr)

    # Test both commands with same args
    help_cmd = HelpCommand(username='testuser', args={})
    menu_cmd = MenuCommand(username='testuser', args={})

    help_response = await processor.process(session_id, help_cmd)
    menu_response = await processor.process(session_id, menu_cmd)

    # Should produce identical results
    assert help_response.success == menu_response.success
    assert help_response.code == menu_response.code
    assert help_response.text == menu_response.text
    assert help_response.payload == menu_response.payload
