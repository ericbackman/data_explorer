# shotfield

Every field-goal attempt of one NBA game, rendered as a mini player rising and
shooting at the exact spot the shot was taken. Made shots gold, misses slate, so
the field that accumulates **is** the shot chart.

Consumes the [`blenderkit`](../../../blender-kit/) brick for rigs, materials, GPU
handling and the render harness. Everything here is the basketball part: the
court, the shot archetypes, and the ball.

## Run it

```bash
# 1. export (Windows, where nba.db lives)
python -m nba.shotfield.export_shots --player "Kobe Bryant" --pts 81 -o /tmp/kobe81.json

# 2. ship data + scene to homebase
scp /tmp/kobe81.json homebase:/tmp/shotfield/game.json
scp nba/shotfield/scene.py homebase:/tmp/shotfield/

# 3. verify geometry and coverage BEFORE spending a render
ssh homebase '/opt/blender/blender --background --factory-startup \
    --python /tmp/shotfield/scene.py -- check'

# 4. render detached (~26 min for 321 frames on the 1050 Ti)
ssh homebase 'nohup /opt/blender-kit/bin/render.sh \
    /tmp/shotfield/scene.py /tmp/shotfield > /tmp/shotfield/run.log 2>&1 </dev/null & disown'
```

Output lands in `/tmp/shotfield/`: `out.mp4`, `sheet.png`, and `frames/`.

## What the data actually supports

Three signals with **three different coverages**, kept separate in
[`archetypes.py`](archetypes.py) so a render never implies more than the data says.

| Signal | Source | Coverage |
|---|---|---|
| `archetype` | `sub_type` | every shot |
| `motion` | `sub_type` prefix | label only; a plain jump shot reports `no_label` |
| `entry` | assist in `description` | **made shots only** |

**Archetype** picks the body motion: jumper, layup, dunk, hook, tip. Where a
sub_type matches two families (`Tip Layup Shot`, `Putback Dunk Shot`) the finish
wins.

**Motion** is the direction the shooter moved into the shot, as far as the label
says. `Driving`/`Cutting`/`Running` move toward the rim; `Step Back`/`Fadeaway`/
`Turnaround` drift away. A plain `Jump Shot` returns `no_label` rather than
"stationary", because the shooter may well have moved and the data does not say.

**Entry** is catch versus self-created, from whether an assist is recorded.
⚠ Assists exist **only on made shots**, so every miss is `unknown` and animates
neutrally. Treating a miss as unassisted would invent a self-created shot for
every miss in the game.

## The label-era trap

The NBA did not record these sub_types from the start:

| Label | First recorded |
|---|---|
| Jump Shot, Driving Layup | 1996-11-01 |
| Fadeaway | 2001-10-30 |
| Step Back | 2007-10-30 |
| Pullup | 2007-10-31 |

Kobe's 81 is **2006-01-22**, so it contains zero pull-ups and zero step-backs.
Not because he did not shoot any, but because nobody logged it yet. Render a 2006
game and a 2024 game with the same code and the modern one looks richer for
reasons that have nothing to do with the players.

`archetypes.missing_labels(date)` returns the gap and the `check` pass prints it.
Do not silently ship a render whose flatness is a coverage artifact.

## Verified against the box score

`export_shots.py` cross-checks the play-by-play attempt count against
`player_game.fga` and warns on a mismatch, because an incomplete PBP feed would
quietly drop shots from the render. Kobe's 81: 46 PBP attempts against 46 box
FGA, 28 makes against 28 box FGM.

## Tests

```bash
python -m pytest nba/shotfield/tests/ -q     # 36 tests, pure, no Blender needed
```

The classifier is deliberately free of `bpy` and sqlite so the shot-type dispatch
is testable in milliseconds rather than inside a 26-minute render.
