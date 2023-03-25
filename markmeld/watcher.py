import logging
from pathlib import Path
from typing import Union
from watchdog.observers import Observer
from watchdog.events import LoggingEventHandler, DirModifiedEvent, FileModifiedEvent

from .melder import Target
from .melder import MarkdownMelder

_LOGGER = logging.getLogger(__name__)


class MarkmeldWatchDog(Observer):
    """
    Watchdog observer to watch for file changes.
    """

    def __init__(
        self,
        path: str,
        cfg: dict,
        target: str,
        print_only: bool = False,
        vardump: bool = False,
    ):
        super().__init__()
        _LOGGER.info(f"Watching {path} for changes...")
        self._mm = MarkdownMelder(cfg)
        self.target = Target(cfg, target)
        self.path = path
        self.print_only = print_only
        self.vardump = vardump

        # init the ignore files list (just the output files)
        if "output_file" in self.target.root_cfg["targets"][target]:
            ignore_file_name = Path(
                self.target.root_cfg["targets"][target]["output_file"]
            ).name
            self.ignore_files = [ignore_file_name]
        else:
            self.ignore_files = []

        self.event_handler = LoggingEventHandler()
        self.event_handler.on_modified = self.on_modified
        self.schedule(self.event_handler, path, recursive=True)

    def on_modified(self, event: Union[DirModifiedEvent, FileModifiedEvent]):
        """
        Check for file or directory modification and then rerun the melder.
        """
        p = Path(event.src_path)

        # dont rebuild if the modified file or directory is the output file
        # otherwise this causes an infinite loop
        if p.name in self.ignore_files:
            return

        _LOGGER.info(f"File modified: {event.src_path}")
        self._mm.build_target(
            self.target.target_name, print_only=self.print_only, vardump=self.vardump
        )
