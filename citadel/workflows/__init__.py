# citadel/workflows/__init__.py

from citadel.workflows import registry
from citadel.workflows import login
from citadel.workflows import register_user
from citadel.workflows import validate_users
from citadel.workflows import enter_message

# any new workflows must be imported above to be registered

# Expose the registry
all_workflows = registry.all_workflows
get_workflow = registry.get
