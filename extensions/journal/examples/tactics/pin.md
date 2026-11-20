# Pin to the king

Tactic · you play White. #tactics

A piece that stands between an attacker and its king can't move: it's pinned. Attack it again, with a pawn if you can, and it's lost. Here the knight on e5 is pinned by your rook, and taking it at once loses the rook to the d6 pawn.

```fen
4k3/8/3p4/4n3/8/8/5P2/4R1K1 w - - 0 1
White to move.
```

```pgn
[White "?"] [Black "?"] [SetUp "1"] [FEN "4k3/8/3p4/4n3/8/8/5P2/4R1K1 w - - 0 1"]
1. f4
{Attacks the pinned knight with a pawn. It can't move, so you win it next move.}
(1. Rxe5+??
{Takes too soon: the pawn on d6 takes back, and you've lost your rook for a knight.}
1... dxe5) *
```

**Try it:** find the move in each position, then check the answer.

- From the start: The knight on e5 is pinned. Find the move that wins it. Answer: 1. f4.
