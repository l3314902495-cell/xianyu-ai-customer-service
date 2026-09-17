class GlobalAIControl:
    """Process-local emergency barrier checked immediately before external sends."""

    def __init__(self) -> None:
        self._stopped = False

    @property
    def stopped(self) -> bool:
        return self._stopped

    def set_enabled(self, enabled: bool) -> None:
        self._stopped = not enabled

    def stop(self) -> None:
        self._stopped = True

    def resume(self) -> None:
        self._stopped = False


global_ai_control = GlobalAIControl()
