# MeshForge fork of `meshing-around`

This is the MeshForge **T2 fork** of [`SpudGunMan/meshing-around`](https://github.com/SpudGunMan/meshing-around).
It exists so the fleet's gateway-arc bot customizations live in version control
with one source of truth — not as unversioned, box-divergent dirty working trees.

> Created 2026-06-21 under the upstream-app ownership policy
> (`meshforge/.claude/plans/upstream_app_ownership_policy_2026_06_21.md`,
> decisions §7; tier **T2**). Companion to the RNS/LXMF protocol forks.

## Branch model

| Branch | Tracks | Purpose |
|---|---|---|
| `main` | upstream `SpudGunMan/meshing-around` `main` | clean mirror — never carries our edits |
| **`meshforge`** | our work, based on a chosen upstream SHA | **the deployed branch** — base + the union of our edits |

`meshforge` is currently based on **`fde22f75ea` (v1.9.9.8)** — the newer of the
two versions the fleet was running, so the load-bearing `.32` patch applies
natively and the VolcanoAI box bumps v1.9.9.5 → v1.9.9.8.

**Deploy the `meshforge` branch only.** `main` is for tracking upstream.

## What we carry (the union — see the `meshforge` commit for provenance)

These were two **diverged** unversioned patch-sets running on the fleet,
reconciled here into one:

| Edit | Origin | What it does |
|---|---|---|
| `_meshforge_reply_is_dup()` | `.32` | Dual-bridge reply dedup. Both bridge paths kept for redundancy (~55% combined delivery, measured 2026-05-26); reply once. Window `MESHFORGE_REPLY_DEDUP_S` (default 30s). |
| Delivery ACK/NAK logging | `.32` | Logs `ROUTING_APP` outcome for the bot's own `wantAck` replies. Observability only. |
| Bridge routing-tag stripping | `.32` | Strips leading `[RNS:..]`/`[Mesh:..]`/`[chN:..]` so bridged commands parse. **The bridge breaks without it.** |
| `ignoreDMs` | VolcanoAI | Config-overridable; ignore direct messages when set. |
| `antiSpam` config-overridable | VolcanoAI | **Supersedes** `.32`'s hardcoded `antiSpam=False`. Default stays `True`; set `antiSpam = False` in `config.ini`. |

**Config ≠ code.** Per-deployment values (`config.ini`, keys, channels,
`antiSpam`/`ignoreDMs` settings) stay out of this repo.

## Deploying to a box

```bash
cd <meshing-around checkout>
git remote set-url origin https://github.com/Nursedude/meshing-around.git
git fetch origin
git checkout meshforge
git pull --ff-only
# restart the bot service for the box (mesh_bot / pong_bot)
```

Until a box is switched over, its edits are preserved in
[`Nursedude/fleet-overlays`](https://github.com/Nursedude/fleet-overlays)
(`meshing-around/`) — the rescue capture this fork supersedes.

## Adopting a future upstream release (governance)

Same discipline as the RNS/LXMF forks:

```bash
git checkout meshforge
git fetch upstream
git merge <upstream-tag-or-sha>     # resolve conflicts in our 3 touched files
python3 -m py_compile mesh_bot.py pong_bot.py modules/settings.py
# canary one box, then roll the fleet
```

Re-base deliberately (pin-bump + canary), never a surprise floating-`main` pull.
Keep `main` mirroring upstream so the merge base is always clean.

## Why fork (T2) instead of an overlay (T3)

The bot was already a **de-facto fork**: +70 lines of load-bearing gateway-arc
logic on `.32`, a different set on VolcanoAI, two different upstream versions.
A re-applied-patch overlay carried most of that reconciliation pain without the
clean-tree / one-source-of-truth / CI benefits. So we own it.
