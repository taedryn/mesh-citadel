# citadel/workflows/__init__.py

from citadel.workflows import registry
from citadel.workflows import validate_users

# any new workflows must be imported above to be registered

# Expose the registry
all_workflows = registry.all_workflows
get_workflow = registry.get
