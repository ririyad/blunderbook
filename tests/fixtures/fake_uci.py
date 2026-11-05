"""A tiny UCI responder for tests.

    python fake_uci.py [--name "Stockfish 17.1"] [--silent] [--exit]
                       [--score "cp 30,cp 10"] [--crash-on-go N] [--log FILE]

--silent         reads commands but never answers (to test timeouts); exits on end of input
--exit           quits at once without saying anything (not a UCI engine)
--score LIST     scores for MultiPV lines 1, 2, ... from the side to move ("cp 30",
                 "mate -2"); the last one repeats. Default "cp 0".
--crash-on-go N  exits without a word on the Nth "go" (counting from 1)
--log FILE       appends every command it receives to FILE

"go" answers one line per MultiPV slot: line k plays the k-th legal move in UCI order,
with a one-move PV, and "bestmove" is the first. Positions are read with python-chess,
which the test interpreter has. It declares Threads, Hash and MultiPV like Stockfish.
"""

import sys

import chess


def board_from(tokens: list[str]) -> chess.Board:
    if tokens[1] == "startpos":
        board, rest = chess.Board(), tokens[2:]
    else:
        board, rest = chess.Board(" ".join(tokens[2:8])), tokens[8:]
    if rest and rest[0] == "moves":
        for uci in rest[1:]:
            board.push_uci(uci)
    return board


def main(argv: list[str]) -> None:
    def arg(flag: str, default: str) -> str:
        return argv[argv.index(flag) + 1] if flag in argv else default

    if "--exit" in argv:
        return
    name = arg("--name", "Stockfish 17.1")
    silent = "--silent" in argv
    scores = [s.strip() for s in arg("--score", "cp 0").split(",")]
    crash_on = int(arg("--crash-on-go", "0"))
    log = arg("--log", "")

    board = chess.Board()
    multipv = 1
    goes = 0
    for line in sys.stdin:
        command = line.strip()
        if log:
            with open(log, "a", encoding="utf-8") as f:
                f.write(command + "\n")
        if silent:
            continue
        tokens = command.split()
        if not tokens:
            continue
        if tokens[0] == "uci":
            print(f"id name {name}")
            print("id author Blunderbook tests")
            print("option name Threads type spin default 1 min 1 max 1024")
            print("option name Hash type spin default 16 min 1 max 33554432")
            print("option name MultiPV type spin default 1 min 1 max 256")
            print("uciok", flush=True)
        elif tokens[0] == "isready":
            print("readyok", flush=True)
        elif tokens[:3] == ["setoption", "name", "MultiPV"]:
            multipv = int(tokens[4])
        elif tokens[0] == "position":
            board = board_from(tokens)
        elif tokens[0] == "go":
            goes += 1
            if goes == crash_on:
                sys.exit(3)
            depth = tokens[tokens.index("depth") + 1] if "depth" in tokens else "1"
            moves = sorted(board.legal_moves, key=lambda m: m.uci())
            for k, move in enumerate(moves[:multipv], start=1):
                score = scores[min(k, len(scores)) - 1]
                print(f"info depth {depth} multipv {k} score {score} nodes 1 pv {move.uci()}")
            best = moves[0].uci() if moves else "(none)"
            print(f"bestmove {best}", flush=True)
        elif tokens[0] == "quit":
            return


if __name__ == "__main__":
    main(sys.argv[1:])
