import pytest

from citadel.workflows import registry
from citadel.workflows.validate_users import ValidateUsersWorkflow


def test_validate_users_workflow_registered():
    # The decorator should have registered this workflow automatically
    wf = registry.get("validate_users")
    assert wf is not None
    assert isinstance(wf, ValidateUsersWorkflow)
    assert wf.kind == "validate_users"


def test_all_workflows_contains_validate_users():
    all_wfs = registry.all_workflows()
    assert "validate_users" in all_wfs
    assert isinstance(all_wfs["validate_users"], ValidateUsersWorkflow)
