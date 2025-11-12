"""
Tests for BBS Listener Error Handling

Focuses on testing the enhanced error categorization and recovery behavior
implemented in the SessionCoordinator's BBS listener.
"""
import pytest
import pytest_asyncio
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from citadel.transport.engines.meshcore.session_coordinator import SessionCoordinator
from citadel.transport.packets import ToUser


@pytest.fixture
def mock_coordinator_components():
    """Create mocked components for SessionCoordinator testing."""
    config = Mock()
    config.transport = {"meshcore": {"inter_packet_delay": 0.01}}  # Fast for testing

    session_mgr = Mock()
    create_monitored_task_func = Mock(side_effect=lambda coro, name: asyncio.create_task(coro))

    coordinator = SessionCoordinator(config, session_mgr, create_monitored_task_func)
    coordinator._send_to_node_func = AsyncMock(return_value=True)
    coordinator._disconnect_func = AsyncMock()

    return coordinator, session_mgr


@pytest.mark.asyncio
async def test_network_error_continues_with_retry_delay(mock_coordinator_components):
    """Test that network errors cause 2s delay and continue processing."""
    coordinator, session_mgr = mock_coordinator_components
    session_id = "test_session"

    # Mock session state
    mock_state = Mock()
    mock_state.node_id = "test_node"
    mock_state.username = "test_user"
    mock_state.msg_queue = asyncio.Queue()
    session_mgr.get_session_state.return_value = mock_state

    # Put messages in queue
    await mock_state.msg_queue.put(ToUser(session_id=session_id, text="Message 1"))
    await mock_state.msg_queue.put(ToUser(session_id=session_id, text="Message 2"))

    # First call raises ConnectionError, second succeeds
    coordinator._send_to_node_func.side_effect = [
        ConnectionError("Network temporarily down"),
        True  # Second message succeeds
    ]

    # Start listener and capture timing
    start_time = asyncio.get_event_loop().time()

    # Create the listener coroutine directly for testing
    async def run_listener_briefly():
        await coordinator.start_bbs_listener(session_id)
        listener_task = coordinator.listeners[session_id]

        # Let it process both messages
        await asyncio.sleep(2.5)  # Wait for retry delay + processing

        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

    await run_listener_briefly()
    end_time = asyncio.get_event_loop().time()

    # Should have taken at least 2 seconds due to network error retry delay
    assert (end_time - start_time) >= 2.0

    # Should have called send twice (fail + retry)
    assert coordinator._send_to_node_func.call_count == 2


@pytest.mark.asyncio
async def test_data_error_skips_message_continues(mock_coordinator_components):
    """Test that data errors during send operations are handled gracefully."""
    coordinator, session_mgr = mock_coordinator_components
    session_id = "test_session"

    # Mock session state
    mock_state = Mock()
    mock_state.node_id = "test_node"
    mock_state.username = "test_user"
    mock_state.msg_queue = asyncio.Queue()
    session_mgr.get_session_state.return_value = mock_state

    # Put valid ToUser messages in queue
    await mock_state.msg_queue.put(ToUser(session_id=session_id, text="Message 1"))
    await mock_state.msg_queue.put(ToUser(session_id=session_id, text="Message 2"))

    # First send raises TypeError (data error), second succeeds
    coordinator._send_to_node_func.side_effect = [
        TypeError("Invalid message format"),  # Data error - should be skipped
        True  # Second message succeeds
    ]

    # Start listener
    await coordinator.start_bbs_listener(session_id)
    listener_task = coordinator.listeners[session_id]

    # Give time for both message processing attempts
    await asyncio.sleep(0.1)

    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    # Should have called send twice - first fails with TypeError, second succeeds
    assert coordinator._send_to_node_func.call_count == 2


@pytest.mark.asyncio
async def test_memory_error_terminates_listener(mock_coordinator_components):
    """Test that MemoryError causes listener to terminate cleanly."""
    coordinator, session_mgr = mock_coordinator_components
    session_id = "test_session"

    # Mock session state check to raise MemoryError
    session_mgr.get_session_state.side_effect = MemoryError("System out of memory")

    # Start listener
    await coordinator.start_bbs_listener(session_id)
    listener_task = coordinator.listeners[session_id]

    # Give time for error to occur and listener to terminate
    await asyncio.sleep(0.1)

    # Task should have completed (not still running)
    assert listener_task.done()

    # Should not have attempted any sends due to early memory error
    assert coordinator._send_to_node_func.call_count == 0


@pytest.mark.asyncio
async def test_send_failure_triggers_disconnect(mock_coordinator_components):
    """Test that send failures call disconnect callback."""
    coordinator, session_mgr = mock_coordinator_components
    session_id = "test_session"

    # Mock session state
    mock_state = Mock()
    mock_state.node_id = "test_node"
    mock_state.username = "test_user"
    mock_state.msg_queue = asyncio.Queue()
    session_mgr.get_session_state.return_value = mock_state

    # Put message in queue
    test_msg = ToUser(session_id=session_id, text="Test message")
    await mock_state.msg_queue.put(test_msg)

    # Configure send to fail
    coordinator._send_to_node_func.return_value = False

    # Start listener
    await coordinator.start_bbs_listener(session_id)
    listener_task = coordinator.listeners[session_id]

    # Give time for message processing and failure
    await asyncio.sleep(0.1)

    # Should have called disconnect due to send failure
    coordinator._disconnect_func.assert_called_once_with(session_id, reading_msg=False)

    # Task should be done after disconnect
    assert listener_task.done()


@pytest.mark.asyncio
async def test_session_expiry_terminates_cleanly(mock_coordinator_components):
    """Test that expired sessions cause clean termination."""
    coordinator, session_mgr = mock_coordinator_components
    session_id = "test_session"

    # Mock session as expired (returns None)
    session_mgr.get_session_state.return_value = None

    # Start listener
    await coordinator.start_bbs_listener(session_id)
    listener_task = coordinator.listeners[session_id]

    # Give time for expiry check and termination
    await asyncio.sleep(0.05)

    # Should have terminated cleanly
    assert listener_task.done()

    # Should not have attempted sends or disconnects
    assert coordinator._send_to_node_func.call_count == 0
    assert coordinator._disconnect_func.call_count == 0


@pytest.mark.asyncio
async def test_inter_packet_delay_respected(mock_coordinator_components):
    """Test that configured inter_packet_delay is honored."""
    coordinator, session_mgr = mock_coordinator_components
    session_id = "test_session"

    # Set specific delay
    coordinator.mc_config = {"inter_packet_delay": 0.1}

    # Mock session state
    mock_state = Mock()
    mock_state.node_id = "test_node"
    mock_state.username = "test_user"
    mock_state.msg_queue = asyncio.Queue()
    session_mgr.get_session_state.return_value = mock_state

    # Put message in queue
    await mock_state.msg_queue.put(ToUser(session_id=session_id, text="Test message"))

    coordinator._send_to_node_func.return_value = True

    start_time = asyncio.get_event_loop().time()

    # Start listener
    await coordinator.start_bbs_listener(session_id)
    listener_task = coordinator.listeners[session_id]

    # Wait for message processing
    await asyncio.sleep(0.15)

    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    end_time = asyncio.get_event_loop().time()

    # Should have taken at least the inter_packet_delay
    assert (end_time - start_time) >= 0.1
    assert coordinator._send_to_node_func.call_count == 1


@pytest.mark.asyncio
async def test_error_recovery_sends_user_notification(mock_coordinator_components):
    """Test that unexpected errors send notification to user."""
    coordinator, session_mgr = mock_coordinator_components
    session_id = "test_session"

    # Mock session state
    mock_state = Mock()
    mock_state.node_id = "test_node"
    mock_state.username = "test_user"
    mock_state.msg_queue = asyncio.Queue()

    # First call returns good state, second call for error handling returns good state
    session_mgr.get_session_state.return_value = mock_state

    # Put message in queue
    await mock_state.msg_queue.put(ToUser(session_id=session_id, text="Test message"))

    # First send fails with unexpected error, error notification send succeeds
    coordinator._send_to_node_func.side_effect = [
        RuntimeError("Unexpected failure"),
        True  # Error notification succeeds
    ]

    # Start listener
    await coordinator.start_bbs_listener(session_id)
    listener_task = coordinator.listeners[session_id]

    # Give time for error and recovery
    await asyncio.sleep(1.2)  # Wait for error + 1s delay + processing

    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    # Should have called send twice: original message (failed) + error notification
    assert coordinator._send_to_node_func.call_count == 2

    # Second call should be the error notification
    error_call_args = coordinator._send_to_node_func.call_args_list[1]
    assert "System error occurred" in error_call_args[0][2]  # Third argument is the message