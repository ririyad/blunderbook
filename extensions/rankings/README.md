# Blunderbook Rankings

A Blunderbook extension: the FIDE, Lichess and Chess.com top lists. It's a separate package
(CLAUDE.md §15). Nothing here goes into your Log.

Status: in progress (M16 of the roadmap). 16.1 has the database and FIDE's lists on the
command line.

## Install and turn on

```sh
blunderbook ext install rankings   # installs it and turns it on
```

## Update

```sh
blunderbook rankings update fide   # FIDE's standard, rapid and blitz lists, about 35 MB
blunderbook rankings status        # when each list was downloaded
```

- **It goes online only when you run `update`.** Nothing checks or downloads on its own.
- **Only what changed is downloaded.** FIDE publishes new lists once a month, around the
  1st. Running `update` again before then says "already up to date".
- **Only the top players are kept**, so the database stays small in your backups: active
  players only, the world top 100 and each federation's top 50 in Open, Women, Juniors and
  Girls, for the newest list and the one before it.
- **A failed update keeps the lists you had.** Ctrl+C changes nothing.

## The data

The lists come from [FIDE](https://ratings.fide.com/download_lists.phtml). They're for your
own use on your own computer: Blunderbook doesn't republish them.
