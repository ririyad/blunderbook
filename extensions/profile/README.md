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

## The tab

Restart `blunderbook serve` after turning it on. The Profile tab has a panel for each site
with your ratings, and **Refresh ratings**, which asks each site you have a username for.
Opening the tab asks no one: it shows what was kept last time. Until a site has been
fetched, its panel shows your rating in your newest synced game of each time control.

If one site can't be asked, its panel says why, the ratings you had from it are kept, and
the other site is still asked.

### Rating over time

Under the panels, a chart drawn from the games in your Log (nothing is asked of a site):
your rating in the last game of each month, a line per site, for one time control at a
time. Under it, your blunders per game that month, on its own scale.

- Only Lichess and Chess.com games with your rating, a date and a time control count. A
  rating on one site says nothing about the other, so each has its own line.
- A month you didn't play has no point and no bar; the line runs straight across it.
- Point at a month, or focus the chart and press ← → Home End, to read its numbers.
  "The numbers" has every month as a table.

## Commands

- `blunderbook profile refresh [lichess|chesscom|all]` asks each site for your ratings now
  and keeps the answer in `profile.db`, next to your database. Asking again on the same day
  replaces that day's answer.
- `blunderbook profile show` prints what was fetched last, and your rating in your newest
  synced game of each site and speed. It asks no site.

## What goes online

Only **Refresh ratings** and `refresh`. They send your username to the site it belongs to: to Lichess
(`/api/user/{username}` and `/api/user/{username}/perf/{perf}`), with no token, and to
Chess.com (`/pub/player/{username}/stats`), with your `contact` in the User-Agent, as
Chess.com asks. Nothing else is sent, and nothing is sent anywhere else.

## What you see

Per kind of play (bullet, blitz, rapid, classical, daily, puzzles): the rating, how far it
moved since the fetch before, your highest, and your wins, losses and draws, where the site
gives them. A `?` marks a rating the site still calls provisional.

- Chess.com has no classical rating.
- Chess.com gives only your highest puzzle rating, not the current one.
