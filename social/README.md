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
python3 social/serve.py                        # http://127.0.0.1:8787
```

`--platforms x,bluesky,reddit,discord` picks which to write (that list is the default);
`--force` overwrites drafts that already exist for the run.

Review → **Approve** → **Post it** → copy, paste, mark posted. **Send back** parks a draft
with a note. **Edit** rewrites the body against a live per-platform character count.

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
| `serve.py` | loopback-only server, reads/writes `drafts/`, serves `ui/` |
| `gen_drafts.py` | run summary → one draft per platform |
| `platforms.json` | per-platform limits, compose URL, walkthrough steps |
| `ui/` | dashboard (no build step, no dependencies) |
| `drafts/` | one JSON per draft — **gitignored**, this repo is public |

## Boundaries

- Binds `127.0.0.1` only. It can rewrite drafts and read repo files; it is not for the LAN.
- The media endpoint refuses any path that resolves outside the repo.
- **This must never move under `site/`** — that directory is the Cloudflare Worker's public
  asset root, so anything in it ships to pokebench.tv.
- YouTube is deliberately absent: long-form publishing is the `pokebench-publish-run` skill's job.
