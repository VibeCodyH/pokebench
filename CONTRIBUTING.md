# Contributing a run

Anyone can put a run on the board. If you have the hardware for a local model, or credits for an API
model, run it and send me the receipts. It gets scored exactly like mine: furthest milestone, fewest
turns to reach it.

## What counts

- **A vision-capable model.** The harness sends a screenshot every turn, so text-only models are out
  ([BENCHMARK-SPEC.md](BENCHMARK-SPEC.md) §0).
- **The harness as it is on `main`.** Don't edit the prompt, the action list, or the turn loop. The
  summary records the commit (`harness_git_sha`), the prompt version and hash, and a hash of the
  harness files (`harness_files_sha`), so a changed harness shows up. Adding a `models.yaml` row
  doesn't change that hash.
- **A finished run.** It either beat Brock or used all 1,000 turns, so `termination_reason` in
  `summary.json` is `beat_brock` or `budget`. Smoke tests, Ctrl-C'd runs, and runs killed by a provider
  outage stay off the board.
- **The default settings.** `think: high`, 1,000 turns. If your model only fits with less than 64K of
  context, that's fine. `num_ctx` is recorded in the summary and shows on the card.

## Run it

1. Set up the repo and your ROM the way [README.md](README.md#run-this-yourself) describes.
2. If your model isn't in `models.yaml`, add a row. Copy an existing row with the same `provider`.
   Local models get `0.0` for both rates. For an API model, use the provider's published per-million
   prices and put the source in a comment. If you can't find a rate, leave it `null`.
3. Start the run:

   ```bash
   ./run.sh <model-key>
   ```

Ollama is the only local server the harness talks to right now. Serving through vLLM or a llama.cpp
server needs a new adapter in `providers.py` first.

## Submit it

Open a pull request that adds:

- `runs/<run-id>/summary.json`
- `runs/<run-id>/log.jsonl`
- your `models.yaml` row, if you added one

Don't edit either file by hand. They're the receipts. `frames/` is gitignored, so leave it out.

In the PR description, include:

- your hardware (GPU and VRAM)
- how the model was served (Ollama version, quant)
- how you want to be credited, or that you'd rather not be

If a pull request is more than you want to deal with, open an issue and attach the two files zipped.

## Recordings

Not required, but I'd love them. A run with video is a run people actually watch.

- Record `http://localhost:8765/stream`. It's a fixed 1280x720 canvas built for capture, and OBS or any
  screen recorder works. `recorder/` is my setup (headless Chromium into FFmpeg with NVENC, so NVIDIA
  only).
- Record the whole run, start to finish, uncut.
- Link the video in your PR. If it goes up on the [PokéBench YouTube channel](https://youtube.com/@pokebenchtv),
  the upload credits you by whatever name you give. If you don't want your name on it, say so and it
  won't be.

## After you submit

I check the summary's hashes against the commit it names, then merge. Once it's merged, the run shows up
on [pokebench.tv](https://pokebench.tv).
