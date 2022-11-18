from .melder import MarkdownMelder
from .cli import main
from .utilities import load_config_file

__all__ = ["MarkdownMelder", "load_config_file"]

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Program canceled by user.")
        sys.exit(1)
