from adapters.registry import get_adapter_registry
from settings import get_settings
from worker import UnifiedWorker


def main() -> None:
    settings = get_settings()
    adapter_registry = get_adapter_registry()
    worker = UnifiedWorker(settings, adapter_registry)
    worker.run_forever()


if __name__ == "__main__":
    main()
