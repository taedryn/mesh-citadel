# citadel/workflows/registry.py

_registry: dict[str, "Workflow"] = {}

def register(workflow_cls):
    """Decorator to register a workflow class by its kind."""
    instance = workflow_cls()
    _registry[instance.kind] = instance
    return workflow_cls

def get(kind: str):
    return _registry.get(kind)

def all_workflows():
    return _registry

