"""Shot field: every field-goal attempt of a game, animated on a 3D court.

Run inside Blender on homebase:

    /opt/blender/blender --background --factory-startup --python scene.py -- check
    /opt/blender/blender --background --factory-startup --python scene.py -- still 120
    /opt/blender/blender --background --factory-startup --python scene.py -- anim

Consumes the `blenderkit` brick (Github/blender-kit, deployed to /opt/blender-kit)
for rigs, materials, GPU handling and the render harness. Everything here is the
basketball part: the court, the shot archetypes, and the ball.

Data in: the JSON written by `export_shots.py`. No sqlite, no network.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.environ.get("BLENDERKIT", "/opt/blender-kit"))

import bpy                                                    # noqa: E402
from mathutils import Vector                                  # noqa: E402

from blenderkit import geom, harness, mesh, rig, scene as bkscene   # noqa: E402

DATA = os.environ.get("SHOTFIELD_DATA", "/tmp/shotfield/game.json")
OUT = os.environ.get("SHOTFIELD_OUT", "/tmp/shotfield")

# ---------------------------------------------------------------- court (feet)
RIM_Z, RIM_R = 10.0, 0.75
BASELINE_Y, HALFCOURT_Y = -5.25, 41.75
COURT_HALF_W = 25.0
PAINT_HW, PAINT_Y = 8.0, 13.75
THREE_R, CORNER_X = 23.75, 22.0
LINE_W = 0.30
PSCALE = 0.85

FPS, LEAD_IN, STAGGER = 24, 16, 5
FLIGHT, DROP, TAIL = 13, 7, 34

# ---------------------------------------------------------------- archetypes
# Shooting/guide arm angles at four beats: dip, set, release, follow.
# Each entry is (r_upper, r_fore, r_hand, l_upper, l_fore, l_hand) in degrees.
# Angles COMPOSE down the chain (see blenderkit.rig): +85 upper with +95 fore is
# a forearm pointing straight up.
ARMS = {
    "jumper": ((34, 74, -22, 34, 74, -18), (78, 95, 18, 66, 88, 10),
               (148, 30, -22, 92, 36, -8), (166, 10, -68, 46, -26, -16)),
    "layup":  ((30, 60, -20, 30, 60, -16), (96, 66, -8, 58, 44, -10),
               (154, 20, -14, 68, 8, -14), (150, 16, -34, 38, -22, -12)),
    "dunk":   ((36, 70, -18, 36, 70, -16), (122, 58, -18, 100, 52, -14),
               (172, 6, -8, 138, 22, -10), (148, -18, -26, 88, -12, -14)),
    "hook":   ((28, 66, -18, 28, 66, -14), (102, 78, 2, 28, -30, -10),
               (162, 18, -30, 22, -38, -8), (148, 10, -54, 18, -42, -8)),
    "tip":    ((40, 70, -15, 40, 70, -15), (150, 24, -6, 140, 28, -6),
               (168, 6, -12, 156, 10, -10), (150, 8, -30, 138, 12, -20)),
}

# jump height at release, travel toward the rim, dip depth, ball apex
SHAPE = {
    "jumper": dict(jump=1.32, travel=0.45, dip=-0.62, apex=lambda d: 2.0 + d * 0.22),
    "layup":  dict(jump=1.10, travel=3.10, dip=-0.34, apex=lambda d: 0.85),
    "dunk":   dict(jump=1.95, travel=3.80, dip=-0.52, apex=lambda d: 0.30),
    "hook":   dict(jump=0.98, travel=0.90, dip=-0.40, apex=lambda d: 2.4),
    "tip":    dict(jump=0.78, travel=0.45, dip=-0.24, apex=lambda d: 1.1),
}
ARM_Y = {"hook": -34.0}          # the hook sweeps the arm out to the side

# beat -> frame offset from the shooter's start
BEATS = dict(appear=0, entry_a=3, entry_b=8, gather=12, dip=16,
             set=22, release=26, follow=29, hold=35, land=41, relax=55)
RELEASE_DF = BEATS["release"]


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


payload = load(DATA)
shots = payload["shots"]

bpy.ops.wm.read_factory_settings(use_empty=True)
scn = bpy.context.scene

M_MADE = mesh.material("made", (0.99, 0.72, 0.15), 0.42, 0.15, emission=0.30)
M_MISS = mesh.material("miss", (0.20, 0.13, 0.31), 0.70)
M_BALL = mesh.material("ball", (0.78, 0.30, 0.07), 0.55)
M_FLOOR = mesh.material("floor", (0.14, 0.085, 0.05), 0.35)
M_PAINT = mesh.material("paint", (0.26, 0.13, 0.07), 0.45)
M_LINE = mesh.material("line", (0.88, 0.87, 0.84), 0.45)
M_RIM = mesh.material("rim", (0.96, 0.36, 0.05), 0.30, 0.8)
M_BOARD = mesh.material("board", (0.86, 0.90, 0.96), 0.10, alpha=0.22)
M_NET = mesh.material("net", (0.90, 0.90, 0.90), 0.6)


def line(name, points, material=M_LINE, width=LINE_W, z=0.02):
    """One court line as a single mitred ribbon (never a row of boxes)."""
    verts, faces = geom.ribbon(points, width=width, z=z)
    return mesh.new_object(name, mesh.mesh_from(name, verts, faces), material)


def slab(name, size, location, material):
    bpy.ops.mesh.primitive_plane_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = (size[0], size[1], 1)
    obj.data.materials.append(material)
    return obj


def build_court():
    slab("floor", (COURT_HALF_W * 2, HALFCOURT_Y - BASELINE_Y),
         (0, (HALFCOURT_Y + BASELINE_Y) / 2, 0), M_FLOOR)
    slab("paint_fill", (PAINT_HW * 2, PAINT_Y - BASELINE_Y),
         (0, (BASELINE_Y + PAINT_Y) / 2, 0.008), M_PAINT)

    corner_y = THREE_R * math.cos(math.asin(CORNER_X / THREE_R))
    a = math.asin(CORNER_X / THREE_R)
    line("three_l", [(-CORNER_X, BASELINE_Y), (-CORNER_X, corner_y)])
    line("three_r", [(CORNER_X, BASELINE_Y), (CORNER_X, corner_y)])
    line("three_arc", geom.arc_points(THREE_R, math.pi / 2 - a, math.pi / 2 + a, 64))
    line("paint", [(-PAINT_HW, BASELINE_Y), (-PAINT_HW, PAINT_Y),
                   (PAINT_HW, PAINT_Y), (PAINT_HW, BASELINE_Y)])
    line("ft_circle", geom.arc_points(6.0, 0, 2 * math.pi, 48, 0, PAINT_Y))
    line("baseline", [(-COURT_HALF_W, BASELINE_Y), (COURT_HALF_W, BASELINE_Y)])
    line("sideline_l", [(-COURT_HALF_W, BASELINE_Y), (-COURT_HALF_W, HALFCOURT_Y)])
    line("sideline_r", [(COURT_HALF_W, BASELINE_Y), (COURT_HALF_W, HALFCOURT_Y)])
    line("halfcourt", [(-COURT_HALF_W, HALFCOURT_Y), (COURT_HALF_W, HALFCOURT_Y)])

    bpy.ops.mesh.primitive_torus_add(major_radius=RIM_R, minor_radius=0.055,
                                     location=(0, 0, RIM_Z), major_segments=32)
    bpy.context.object.data.materials.append(M_RIM)
    board = slab("backboard", (1, 1), (0, -1.25, RIM_Z + 1.25), M_BOARD)
    bpy.data.objects.remove(board, do_unlink=True)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -1.25, RIM_Z + 1.25))
    bd = bpy.context.object
    bd.scale = (6.0, 0.12, 3.5)
    bd.data.materials.append(M_BOARD)          # glass, so it never hides its own rim
    bpy.ops.mesh.primitive_cone_add(radius1=RIM_R * 0.95, radius2=0.42, depth=1.5,
                                    vertices=18, location=(0, 0, RIM_Z - 0.75))
    net = bpy.context.object
    net.rotation_euler = (math.pi, 0, 0)
    net.modifiers.new("wire", "WIREFRAME").thickness = 0.035
    net.data.materials.append(M_NET)


build_court()

SPEC = rig.HumanoidSpec()
MESHES = rig.humanoid_meshes(SPEC)
BALL_MESH = mesh.sphere_mesh("ball", 0.40, 16, 10)


def toward_hoop(x, y):
    length = math.hypot(x, y)
    return (Vector((-x, -y, 0)) / length) if length > 0.5 else Vector((0, 1, 0))


def pose_at(beat_arms, thigh, shin, arch):
    """{joint: angle} for one beat. Left and right arms are independent."""
    rua, rfa, rhn, lua, lfa, lhn = beat_arms
    arm_y = ARM_Y.get(arch, 0.0)
    return {
        "ua_r": (rua, arm_y, 0.0) if arm_y else rua,
        "fa_r": rfa, "hand_r": rhn,
        "ua_l": lua, "fa_l": lfa, "hand_l": lhn,
        "thigh_r": thigh, "shin_r": shin,
        "thigh_l": thigh - 5.0, "shin_l": shin + 2.5,
    }


def build_shooter(index, shot):
    arch = shot["archetype"]
    arms, shape = ARMS[arch], SHAPE[arch]
    material = M_MADE if shot["made"] else M_MISS
    x, y = shot["x"], shot["y"]
    direction = toward_hoop(x, y)
    # a fadeaway/turnaround drifts AWAY from the rim instead of toward it
    travel = -abs(shape["travel"]) if shot["motion"] == "away" else shape["travel"]

    figure = rig.humanoid("s%02d" % index, SPEC, MESHES, material,
                          location=(x, y, SPEC.stand_z * PSCALE),
                          facing_z=geom.facing_z(x, y), scale=PSCALE)
    t0 = LEAD_IN + index * STAGGER
    stand = (12, -50, -8, 12, -50, -8)

    # entry: only a MADE shot tells us whether it was caught or created
    entry = shot["entry"]
    if entry == "catch":
        entry_a = (58, 30, -30, 58, 30, -30)      # hands out to receive
        entry_b = (40, 52, -24, 40, 52, -22)
    elif entry == "dribble":
        entry_a = (24, -18, -30, 16, -46, -10)    # shooting hand low over the ball
        entry_b = (30, -6, -34, 16, -46, -10)
    else:
        entry_a = entry_b = stand                  # unknown: claim nothing

    frames = [
        (BEATS["appear"], 0.0, 0.00, stand, 5, -9),
        (BEATS["entry_a"], 1.0, 0.02, entry_a, 10, -18),
        (BEATS["entry_b"], 1.0, 0.06, entry_b, 14, -24),
        (BEATS["gather"], 1.0, 0.12, arms[0], 20, -36),
        (BEATS["dip"], shape["dip"], 0.20, arms[0], 34, -62),
        (BEATS["set"], shape["jump"] * 0.58, 0.55, arms[1], 16, -34),
        (BEATS["release"], shape["jump"], 0.82, arms[2], 6, -24),
        (BEATS["follow"], shape["jump"] * 0.86, 0.92, arms[3], 8, -28),
        (BEATS["hold"], shape["jump"] * 0.30, 1.00, arms[3], 10, -20),
        (BEATS["land"], -0.18, 1.00, arms[3], 20, -38),
        (BEATS["relax"], 0.00, 1.00, stand, 5, -9),
    ]
    for df, dz, travel_frac, beat_arms, thigh, shin in frames:
        if df == BEATS["dip"]:
            dz_val = shape["dip"]
        else:
            dz_val = dz
        offset = direction * (travel * travel_frac)
        figure.key_root(t0 + df,
                        location=(x + offset.x, y + offset.y,
                                  (SPEC.stand_z + dz_val) * PSCALE),
                        scale=PSCALE * (0.0 if df == BEATS["appear"] else 1.0))
        figure.pose(pose_at(beat_arms, thigh, shin, arch), frame=t0 + df)
    # pop to full size immediately after appearing
    figure.key_root(t0 + BEATS["entry_a"] - 1, scale=PSCALE)

    ball = mesh.new_object("b%02d" % index, BALL_MESH, M_BALL)
    return dict(index=index, shot=shot, figure=figure, ball=ball, t0=t0,
                hold0=t0 + BEATS["entry_a"], release=t0 + RELEASE_DF,
                arch=arch, direction=direction)


shooters = [build_shooter(i, s) for i, s in enumerate(shots)]
LAST = max(s["release"] for s in shooters) + FLIGHT + DROP
F_START, F_END = 1, LAST + TAIL

# ---- ball: read the REAL shooting hand each frame rather than re-deriving it.
for entry in shooters:
    entry["ball"].scale = (0, 0, 0)
    entry["ball"].keyframe_insert("scale", frame=entry["hold0"] - 1)
    entry["ball"].scale = (PSCALE,) * 3
    entry["ball"].keyframe_insert("scale", frame=entry["hold0"])

for frame in range(1, LAST + 2):
    active = [e for e in shooters if e["hold0"] <= frame <= e["release"]]
    if not active:
        continue
    scn.frame_set(frame)
    bpy.context.view_layer.update()
    for entry in active:
        tip, direction = entry["figure"].tip_of("hand_r", SPEC.hand * PSCALE)
        position = tip + direction * (0.40 * 0.55 * PSCALE)
        # a self-created shot bounces the ball before the gather
        if (entry["shot"]["entry"] == "dribble"
                and frame < entry["t0"] + BEATS["gather"]):
            phase = (frame - entry["hold0"]) / 3.0
            position = Vector((position.x, position.y,
                               0.40 * PSCALE + abs(math.sin(phase * math.pi)) * 2.2 * PSCALE))
        entry["ball"].location = position
        entry["ball"].keyframe_insert("location", frame=frame)
        if frame == entry["release"]:
            entry["release_pos"] = position.copy()

for entry in shooters:
    shot, ball = entry["shot"], entry["ball"]
    release_pos = entry.get("release_pos")
    if release_pos is None:
        raise RuntimeError("shot %d never recorded a release position" % entry["index"])
    distance = math.hypot(shot["x"], shot["y"])
    away = -entry["direction"]
    target = (Vector((0, 0, RIM_Z)) if shot["made"]
              else Vector((0, 0, RIM_Z + 0.28)) + away * (RIM_R + 0.22))
    apex = SHAPE[entry["arch"]]["apex"](distance)
    rf = entry["release"]

    for k, point in enumerate(geom.ballistic(release_pos, target, apex, FLIGHT), start=1):
        ball.location = point
        ball.rotation_euler = (k * 0.35, 0, k * 0.1)
        ball.keyframe_insert("location", frame=rf + k)
        ball.keyframe_insert("rotation_euler", frame=rf + k)
    for k in range(1, DROP + 1):
        u = k / float(DROP)
        if shot["made"]:
            point = Vector((0, 0, geom.lerp(RIM_Z, 0.4, u * u)))
        else:
            point = target + away * (3.4 * u) + Vector((0, 0, -(RIM_Z - 0.5) * u * u))
        ball.location = point
        ball.keyframe_insert("location", frame=rf + FLIGHT + k)
    ball.scale = (PSCALE,) * 3
    ball.keyframe_insert("scale", frame=rf + FLIGHT + DROP)
    ball.scale = (0, 0, 0)
    ball.keyframe_insert("scale", frame=rf + FLIGHT + DROP + 2)

# ---------------------------------------------------------------- look
camera, target = bkscene.track_camera((0, 0, 27), (0, 11.0, 2.0), lens=40)
for frame, angle in ((F_START, math.radians(-32)), (F_END, math.radians(24))):
    camera.location = (54.0 * math.sin(angle), 11.0 - 54.0 * math.cos(angle), 27.0)
    camera.keyframe_insert("location", frame=frame)

bkscene.area_light((16, 4, 34), energy=14000, size=22,
                   rotation=(math.radians(24), 0, math.radians(48)))
bkscene.area_light((-20, 24, 26), energy=5000, size=26,
                   rotation=(math.radians(-34), 0, math.radians(-40)),
                   color=(0.62, 0.72, 1.0))
bkscene.world_color((0.015, 0.018, 0.030))

bkscene.configure(width=960, height=720, samples=48, fps=FPS)
bkscene.use_gpu("CUDA")                 # raises rather than silently using CPU
scn.frame_start, scn.frame_end = F_START, F_END

mode, args = harness.parse_mode(harness.script_args(sys.argv))
os.makedirs(os.path.join(OUT, "frames"), exist_ok=True)

if mode == "check":
    from collections import Counter
    print("=== %s, %s (%s) ===" % (payload["player"], payload["date"], payload["final"]))
    print("shots=%d made=%d  frames=%d..%d (%.1fs)  objects=%d meshes=%d"
          % (len(shots), payload["made"], F_START, F_END,
             (F_END - F_START + 1) / float(FPS),
             len(bpy.data.objects), len(bpy.data.meshes)))
    for key in ("archetype", "motion", "entry"):
        print("  %-10s %s" % (key, dict(sorted(Counter(s[key] for s in shots).items()))))
    if payload.get("missing_labels"):
        print("  NOTE labels not recorded on this date: %s"
              % ", ".join(payload["missing_labels"]))
elif mode == "still":
    harness.render_still(int(args[0]), os.path.join(OUT, "still_%s.png" % args[0]))
else:
    harness.render_animation(F_START, F_END, os.path.join(OUT, "frames", "f_"))
