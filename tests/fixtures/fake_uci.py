"""A tiny UCI responder for tests.

    python fake_uci.py [--name "Stockfish 17.1"] [--silent] [--exit]

--silent  reads commands but never answers (to test timeouts); exits on end of input
--exit    quits at once without saying anything (not a UCI engine)
"""

import sys


def main(argv: list[str]) -> None:
    name = "Stockfish 17.1"
    silent = "--silent" in argv
    if "--exit" in argv:
        return
    if "--name" in argv:
        name = argv[argv.index("--name") + 1]
    for line in sys.stdin:
        command = line.strip()
        if silent:
            continue
        if command == "uci":
            print(f"id name {name}")
            print("id author Blunderbook tests")
            print("uciok", flush=True)
        elif command == "isready":
            print("readyok", flush=True)
        elif command == "quit":
            return


if __name__ == "__main__":
    main(sys.argv[1:])
