"""Script entry point for the temp humidity plotter."""

from __future__ import annotations

import logging

from temp_humidity_plotter_core.app import main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        logging.basicConfig(
            level=logging.ERROR,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        logging.getLogger(__name__).error("%s", exc)
        raise SystemExit(1) from None
    except Exception:
        logging.basicConfig(
            level=logging.ERROR,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
        logging.getLogger(__name__).exception("Script failed.")
        raise
