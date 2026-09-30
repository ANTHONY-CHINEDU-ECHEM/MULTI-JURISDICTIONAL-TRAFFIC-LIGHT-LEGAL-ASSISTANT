"""Entry point: python run.py <command> [key=value ...]. Run python run.py help for the command list."""

from trafficlegal.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
