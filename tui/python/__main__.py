"""Entry point: python -m tui.python"""
from tui.python.app import SorediumApp


def main() -> None:
    app = SorediumApp()
    app.run()


if __name__ == "__main__":
    main()
