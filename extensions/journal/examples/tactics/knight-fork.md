# Knight fork

Tactic · you play White. #tactics

A knight attacks squares that can't attack it back along lines, so a check from a knight that also hits another piece wins that piece. Look for squares that touch the king and a rook or queen at once.

```fen
r3k3/8/8/3N4/8/8/4PPP1/4K3 w - - 0 1
White to move.
```

```pgn
[White "?"] [Black "?"] [SetUp "1"] [FEN "r3k3/8/8/3N4/8/8/4PPP1/4K3 w - - 0 1"]
1. Nc7+
{Checks the king and attacks the rook. The king moves, and the rook falls: you are a knight and three pawns up.}
1... Kd7 2. Nxa8 *
```

**Try it:** find the move in each position, then check the answer.

- From the start: Find the knight move that wins the rook. Answer: 1. Nc7+.
