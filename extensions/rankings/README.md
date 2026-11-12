# Blunderbook Rankings

A Blunderbook extension: the FIDE, Lichess and Chess.com top lists. It's a separate package
(CLAUDE.md §15). Nothing here goes into your Log.

Status: done (M16 of the roadmap). A tab with an Update button, and two commands,
`update` and `status`.

## Install and turn on

```sh
blunderbook ext install rankings   # installs it and turns it on
```

## The tab

Restart `blunderbook serve` after turning it on. **Rankings** has a sub-tab for each source:

- **FIDE:** the world's top 100, or a federation's top 50, in Open, Women, Juniors (20 or
  younger this year) or Girls, for standard, rapid or blitz. Each player's title, federation,
  rating, games this period and birth year, from FIDE's latest list.
- **Lichess:** the top 100 in bullet, blitz, rapid, classical and UltraBullet.
- **Chess.com:** the top 50 in rapid, blitz, bullet and daily.

Both sites' boards show the site's own recent change. A name opens the player's profile on
that site, in a new tab. The filters stay in the address (`#rankings/fide?speed=blitz&fed=NOR`),
so a reload or a bookmark keeps them.

**Update** downloads that source's latest lists, only what changed, and shows what it's doing.
When it's done, it says what changed ("FIDE: already up to date (November 2026 lists).") and
redraws the list. The tab also says when a newer FIDE list is probably out, and when the last
update failed. Stopping `serve` stops an update; the lists you had are kept.

## Update on the command line

```sh
blunderbook rankings update            # all three
blunderbook rankings update fide       # FIDE's standard, rapid and blitz lists, about 35 MB
blunderbook rankings update lichess    # the top 100 in bullet, blitz, rapid, classical, UltraBullet
blunderbook rankings update chesscom   # the top 50 in rapid, blitz, bullet and daily
blunderbook rankings status            # when each was downloaded, and any failure
```

```
FIDE November 2026: standard, rapid and blitz lists updated.
Lichess: 5 leaderboards updated.
Chess.com: 4 leaderboards updated.
```

- **It goes online only when you press Update or run `update`.** Nothing checks or
  downloads on its own. To update every month without thinking about it, schedule
  `blunderbook rankings update` (Windows Task Scheduler, or cron): FIDE's new lists come out
  around the 1st.
- **Only what changed is downloaded.** FIDE publishes new lists once a month, around the
  1st. Running `update` again before then says "already up to date". Chess.com's answer
  works the same way; Lichess's five small answers are fetched each time.
- **One request at a time**, as the sites ask. If a site asks to slow down, it waits (a
  minute, or longer if the site says so) and tries once more.
- **One source failing doesn't stop the others.** Its lists stay as they were, and
  `status` shows why.
- **Only the top players are kept**, so the database stays small in your backups: active
  players only, the world top 100 and each federation's top 50 in Open, Women, Juniors and
  Girls, from the latest list only. An update that saves a new list deletes the one before,
  so there's no change since last month. That's about 18,000 players a list, and
  rankings.db stays about 5 MB.
- **Only its newest backup is kept** (`rankings-….db`, about 4.5 MB), whatever `keep` says
  in config.toml: the lists can always be downloaded again. Your own database keeps its 14.
- **A failed update keeps the lists you had.** Ctrl+C keeps the sources already done and
  changes nothing in the one being updated.
- **Chess.com asks for contact details** in each request. Set `contact` under `[chesscom]`
  in config.toml (an email address or web page) and it's sent to Chess.com only.

## The data

The lists come from [FIDE](https://ratings.fide.com/download_lists.phtml),
[Lichess](https://lichess.org/api) and
[Chess.com](https://www.chess.com/news/view/published-data-api). They're for your own use on
your own computer: Blunderbook doesn't republish them.
