from typing import Callable


class STTProvider:
    def __init__(self):
        self._callback = None

    def set_callback(self, callback: Callable[[str], None]):
        self._callback = callback

    def listen_loop(self):
        """Blocking loop that runs in a thread. Calls callback with transcriptions."""
        raise NotImplementedError

    def stop_listening(self):
        raise NotImplementedError
