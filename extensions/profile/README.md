# Blunderbook Profile

A [Blunderbook](../../README.md) extension: your ratings on Lichess and Chess.com.

It asks a site only when you tell it to. Nothing is fetched when Blunderbook starts, when a
page opens, or on a timer.

## Turn it on

```sh
blunderbook ext install profile
```

It uses the usernames you already have under `[lichess]` and `[chesscom]` in config.toml.
Chess.com also needs `contact` there, as `blunderbook sync` does.

## Commands

- `blunderbook profile refresh [lichess|chesscom|all]` asks each site for your ratings now
  and keeps the answer in `profile.db`, next to your database. Asking again on the same day
  replaces that day's answer.
- `blunderbook profile show` prints what was fetched last, and your rating in your newest
  synced game of each site and speed. It asks no site.

## What goes online

Only `refresh`. It sends your username to the site it belongs to: to Lichess
(`/api/user/{username}` and `/api/user/{username}/perf/{perf}`), with no token, and to
Chess.com (`/pub/player/{username}/stats`), with your `contact` in the User-Agent, as
Chess.com asks. Nothing else is sent, and nothing is sent anywhere else.

## What you see

Per kind of play (bullet, blitz, rapid, classical, daily, puzzles): the rating, how far it
moved since the fetch before, your highest, and your wins, losses and draws, where the site
gives them. A `?` marks a rating the site still calls provisional.

- Chess.com has no classical rating.
- Chess.com gives only your highest puzzle rating, not the current one.
