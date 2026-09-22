# Social Command — local draft review

Drafts one social post per platform from a finished run, shows each one styled as the post
it will become, and walks a **manual** publish: copy the body, open the platform's compose
page, paste, then record the URL.

**Nothing here auto-posts and nothing here holds a platform credential.** X dropped its free
tier in February 2026 and now bills posts per call (roughly $0.20 each once a link is in the
body), and Threads / Instagram / TikTok / LinkedIn all gate write access behind app review.
Manual posting skips all of it.

## Use it

```bash
python3 social/gen_drafts.py <RUN_ID>          # write drafts from a run's summary.json
python3 social/make_media.py <RUN_ID>          # 1080x1080 still from the run's last frame
python3 social/make_clip.py <RUN_ID> --turn N --video seg.mp4   # 1080x1920 clip of one turn
python3 social/gen_drafts.py --kind intro --platforms reddit   # "what is PokeBench", no run
python3 social/serve.py                        # http://127.0.0.1:8787
```

`--platforms x,bluesky,reddit,discord` picks which to write (that list is the default, so
`instagram` and `tiktok` are only written when you name them); `--force` overwrites drafts
that already exist for the run.

```bash
python3 social/post_result.py <RUN_ID>         # announce one run in Discord #results
python3 social/post_result.py --all -n         # what is not announced yet, sends nothing
```

`post_result.py` is the run announcement, not a draft: #results is a log of every run the
board carries, one message each, oldest first. `results-posted.json` records what already
went out, so a second call is a no-op instead of a duplicate, and that file is **tracked** for
the same reason `schedule.json` is. A fresh clone that forgot would repost the whole board.

Review → **Approve** → **Post it** → copy, paste, mark posted. **Send back** parks a draft
with a note. **Edit** rewrites the body against a live per-platform character count.

## Two kinds of post

`--kind recap` (the default) writes up one run. It assumes the reader already knows what the
benchmark is, which is fine on a feed that has seen the last twelve and useless on a subreddit
that has seen none — "GPT-6 Astra beat Brock in 246 turns" is a number with no scale attached.
`--kind intro` writes the rules and the spread of the whole board instead, takes no run id, and
is the one to lead with on a new audience.

## Media

Instagram will not accept a text-only post and TikTok needs a video, so for those two an empty
`media` list is not a smaller post, it is an impossible one.

`make_media.py <RUN_ID>` writes `square.png` (1080x1080, the run's last frame over the board's
canvas). `make_clip.py <RUN_ID> --turn N --video <segment>` writes the vertical: the board's
chrome around real gameplay, with the turn counter, the model, and **that turn's own plan text**
quoted underneath. Both land in `social/media/<RUN_ID>/` and `gen_drafts.py` attaches them the
next time it writes a draft for that run, so build the media first or re-run with `--force`.

A whole-run timelapse of the per-turn frames was tried and dropped. 250 unreadable stills with
no turn counter, no model name and no reasoning is not the same artefact as one readable moment,
and it is the reasoning that makes a clip worth watching.

The chrome is an HTML template rendered by headless Chromium out of `~/.cache/ms-playwright`,
which is how the original `c01-brock-falls` clip was made -- it pulls IBM Plex Mono from Google
Fonts rather than needing it installed. The video is composited into the hole at (40, 386),
1000x900, and the source is cropped `640:576:36:88` out of a 1280x720 recording of `/stream`.

**Finding the segment.** `offset = <frame mtime> - <recording start in the filename>`, with the
frames under `runs/<run-id>/frames/turn-NNNN.png` on the server. Verify one offset against the
overlay's own TURN counter before trusting the rest: the overlay clock and the file position
disagree by tens of seconds, in both directions on different runs. Cut the segment on the box
that holds the recording (the Unraid host has no ffmpeg; a throwaway container off the recorder
image does), then copy just the segment down.

## Release schedule

The **Video schedule** view in the sidebar answers one question: what day does the next video go
out. It is seeded from `schedule.json` with every upload to date, and the server refuses a
*planned* date that already has a video on it — Sep 18 2026 shipped five uploads and four of them
drew 1 view or fewer, and Sep 20 put a genuine Brock win next to the record-setter and it drew 3.

Published entries are exempt from that rule. They are a record of what happened, and the seeded
history breaks it five times over; validating it would make the file unloadable rather than make
the past any different. Clearing a published entry's date is refused for the same reason.

## What it will not do

`gen_drafts.py` refuses a run that `site/build_runs.py` would drop (legacy prompt version,
or a run that ended in anything but `budget` / `beat_brock`) — if it is not fit to publish
on the board it gets no posts. Every number in a draft is read from `summary.json` or
computed from the same board the site publishes. A run that went nowhere gets a draft
saying so; nothing is spun.

Link-card previews show the destination domain, not a title. The platform fetches the real
title and image from the URL at post time, and guessing it here would show you something
you are not going to get.

## Counting

X bills a link at 23 characters no matter its length (t.co), so the X count is the body with
every URL folded to 23. Bluesky counts **graphemes**, not UTF-16 units, so an emoji is 1.
Both are reflected in the card footer and the editor.

## Layout

| path | what |
|---|---|
| `serve.py` | loopback-only server, reads/writes `drafts/` + `schedule.json`, serves `ui/` |
| `post_result.py` | one board run → an embed in Discord #results, once |
| `results-posted.json` | which runs have been announced — **tracked**, see above |
| `gen_drafts.py` | run summary → one draft per platform, or a board-wide intro |
| `make_media.py` | run's last frame → `square.png` (1080x1080) |
| `make_clip.py` | one turn + a recording segment → `clip-turn-NNNN.mp4` (1080x1920) |
| `platforms.json` | per-platform limits, compose URL, walkthrough steps |
| `schedule.json` | video release dates — **tracked**, see below |
| `ui/` | dashboard (no build step, no dependencies) |
| `drafts/` | one JSON per draft — **gitignored**, this repo is public |
| `media/` | generated post assets, gitignored (rebuildable from the run) |

`schedule.json` is tracked while `drafts/` is not, on purpose. A draft is unpublished copy
plus review notes; a schedule entry is a date, and the published half of it is already
public on the YouTube channel. Ignoring it would mean the upload history dies on a fresh
clone, which is a worse trade than a public repo revealing that a video is planned.

## Boundaries

- Binds `127.0.0.1` only. It can rewrite drafts and read repo files; it is not for the LAN.
- The media endpoint refuses any path that resolves outside the repo.
- **This must never move under `site/`** — that directory is the Cloudflare Worker's public
  asset root, so anything in it ships to pokebench.tv.
- YouTube *publishing* is still the `pokebench-publish-run` skill's job — this dashboard does
  not upload a video and holds no Google credential. What it owns is release **timing**, which
  belonged to nothing before and is why five videos went out on one day.
