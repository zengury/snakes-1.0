"""AGIBOT A2 CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/agibot-a2.sock"

def _client():
    from agibot_a2_cli.client import get_client
    return get_client(os.environ.get("AGIBOT_A2_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"agibot-a2: {m}\n"); return c
def _do(args, cmd, **kw):
    ex = _exec(args)
    try: return ex.call(cmd, **kw)
    finally: ex.close()

def _simple(cmd):
    def h(a):
        kw = {k: v for k, v in vars(a).items()
              if k not in ("func","command","socket","backend","format","sub","sub2") and v is not None}
        try: _fmt(a).emit(_do(a, cmd, **kw))
        except SafetyError as e: return _fail(f"safety: {e}", 2)
        return 0
    return h

def _build_parser():
    p = build_base_parser("agibot-a2", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # action
    act = sub.add_parser("action", add_help=False)
    asub = act.add_subparsers(dest="sub"); asub.required = True
    a_set = asub.add_parser("set", add_help=False)
    a_set.add_argument("mode", choices=["locomotion","arm-servo","arm-planning","whole-body"])
    a_set.set_defaults(func=_simple("action.set"))
    asub.add_parser("get", add_help=False).set_defaults(func=_simple("action.get"))
    asub.add_parser("list", add_help=False).set_defaults(func=_simple("action.list"))

    # walk
    walk = sub.add_parser("walk", add_help=False)
    wsub = walk.add_subparsers(dest="sub")
    walk.add_argument("--forward", type=float, default=0.0)
    walk.add_argument("--lateral", type=float, default=0.0)
    walk.add_argument("--angular", type=float, default=0.0)
    walk.add_argument("--mode", default="default", choices=["default","navigation"])
    walk.set_defaults(func=_simple("walk"))
    wsub.add_parser("stop", add_help=False).set_defaults(func=_simple("walk.stop"))

    # gait
    gait = sub.add_parser("gait", add_help=False)
    gsub = gait.add_subparsers(dest="sub"); gsub.required = True
    gs = gsub.add_parser("set", add_help=False)
    gs.add_argument("type", choices=["stance","walk","smart-walk","terrain","run","jump","hop"])
    gs.set_defaults(func=_simple("gait.set"))
    gsub.add_parser("get", add_help=False).set_defaults(func=_simple("gait.get"))

    sub.add_parser("stand", add_help=False).set_defaults(func=_simple("stand"))

    # arm
    arm = sub.add_parser("arm", add_help=False)
    armsub = arm.add_subparsers(dest="sub"); armsub.required = True
    ajs = armsub.add_parser("joint-set", add_help=False)
    ajs.add_argument("--positions", required=True, help="14 comma-sep values in rad")
    ajs.set_defaults(func=lambda a: (_fmt(a).emit(_do(a, "arm.joint-set",
        positions=[float(x) for x in a.positions.split(",")])), 0)[1])
    armsub.add_parser("joint-get", add_help=False).set_defaults(func=_simple("arm.joint-get"))
    armsub.add_parser("home", add_help=False).set_defaults(func=_simple("arm.home"))
    amj = armsub.add_parser("move-joint", add_help=False)
    amj.add_argument("--group", required=True, choices=["left","right","both"])
    amj.add_argument("--angles", required=True)
    amj.set_defaults(func=_simple("arm.move-joint"))
    for c in ("move-linear", "plan"):
        sp = armsub.add_parser(c, add_help=False)
        sp.add_argument("--side", required=True, choices=["left","right"])
        for f in ("x","y","z"): sp.add_argument(f"--{f}", type=float, required=True)
        for f in ("qx","qy","qz"): sp.add_argument(f"--{f}", type=float, default=0.0)
        sp.add_argument("--qw", type=float, default=1.0)
        sp.set_defaults(func=_simple(f"arm.{c}"))
    ai = armsub.add_parser("interact", add_help=False)
    ai.add_argument("type", choices=["handshake","fistbump","free"])
    ai.add_argument("--side", default="left", choices=["left","right"])
    ai.set_defaults(func=_simple("arm.interact"))
    armsub.add_parser("tcp-get", add_help=False).set_defaults(func=_simple("arm.tcp-get"))
    afk = armsub.add_parser("fk", add_help=False)
    afk.add_argument("--angles", required=True); afk.add_argument("--side", default="left")
    afk.set_defaults(func=_simple("arm.fk"))
    aik = armsub.add_parser("ik", add_help=False)
    for f in ("x","y","z"): aik.add_argument(f"--{f}", type=float, required=True)
    for f in ("qx","qy","qz"): aik.add_argument(f"--{f}", type=float, default=0.0)
    aik.add_argument("--qw", type=float, default=1.0)
    aik.add_argument("--side", default="left")
    aik.set_defaults(func=_simple("arm.ik"))

    # hand
    hand = sub.add_parser("hand", add_help=False)
    hsub = hand.add_subparsers(dest="sub"); hsub.required = True
    hs = hsub.add_parser("set", add_help=False)
    hs.add_argument("--side", required=True, choices=["left","right"])
    for f in ("thumb0","thumb1","index","middle","ring","pinky"): hs.add_argument(f"--{f}", type=int, default=0)
    hs.set_defaults(func=_simple("hand.set"))
    hg = hsub.add_parser("get", add_help=False)
    hg.add_argument("--side", default="both", choices=["left","right","both"])
    hg.set_defaults(func=_simple("hand.get"))
    ho = hsub.add_parser("open", add_help=False)
    ho.add_argument("--side", default="both", choices=["left","right","both"])
    ho.set_defaults(func=_simple("hand.open"))
    hc = hsub.add_parser("close", add_help=False)
    hc.add_argument("--side", default="both", choices=["left","right","both"])
    hc.add_argument("--force", type=int, default=2000)
    hc.set_defaults(func=_simple("hand.close"))
    hge = hsub.add_parser("gesture", add_help=False)
    hge.add_argument("name", choices=["pinch","grip","point","thumbs-up","fist","open"])
    hge.add_argument("--side", default="both", choices=["left","right","both"])
    hge.set_defaults(func=_simple("hand.gesture"))

    # head
    head = sub.add_parser("head", add_help=False)
    hdsub = head.add_subparsers(dest="sub"); hdsub.required = True
    hds = hdsub.add_parser("set", add_help=False)
    hds.add_argument("--yaw", type=float, default=0.0); hds.add_argument("--pitch", type=float, default=0.0)
    hds.set_defaults(func=_simple("head.set"))
    hdsub.add_parser("get", add_help=False).set_defaults(func=_simple("head.get"))
    hdsub.add_parser("shake", add_help=False).set_defaults(func=_simple("head.shake"))
    hdsub.add_parser("nod", add_help=False).set_defaults(func=_simple("head.nod"))

    # waist
    waist = sub.add_parser("waist", add_help=False)
    wasub = waist.add_subparsers(dest="sub"); wasub.required = True
    was = wasub.add_parser("set", add_help=False)
    was.add_argument("--z", type=float); was.add_argument("--roll", type=float)
    was.add_argument("--pitch", type=float); was.add_argument("--yaw", type=float)
    was.set_defaults(func=_simple("waist.set"))
    wasub.add_parser("get", add_help=False).set_defaults(func=_simple("waist.get"))
    wal = wasub.add_parser("lift", add_help=False)
    wal.add_argument("z", type=float)
    wal.set_defaults(func=_simple("waist.lift"))

    # joint (shared)
    add_joint_commands(sub, _exec)
    jp = sub.add_parser("joint-params", add_help=False)
    jp.set_defaults(func=_simple("joint.params"))

    # imu
    imu = sub.add_parser("imu", add_help=False)
    isub = imu.add_subparsers(dest="sub"); isub.required = True
    ig = isub.add_parser("get", add_help=False)
    ig.add_argument("--stream", action="store_true"); ig.add_argument("--hz", type=int, default=50)
    ig.set_defaults(func=lambda a: _imu_stream(a) if a.stream else (_fmt(a).emit(_do(a, "imu.get")), 0)[1])

    # camera
    cam = sub.add_parser("camera", add_help=False)
    csub = cam.add_subparsers(dest="sub"); csub.required = True
    csub.add_parser("list", add_help=False).set_defaults(func=_simple("camera.list"))
    cg = csub.add_parser("get", add_help=False)
    cg.add_argument("source", choices=["head-rgb","head-depth","hip-rgb","hip-depth","chest-left","chest-right","interactive"])
    cg.add_argument("--output", default=None)
    cg.set_defaults(func=_simple("camera.get"))

    # lidar
    sub.add_parser("lidar", add_help=False).add_subparsers(dest="sub").add_parser("get", add_help=False).set_defaults(func=_simple("lidar.get"))

    # dance
    dance = sub.add_parser("dance", add_help=False)
    dsub = dance.add_subparsers(dest="sub"); dsub.required = True
    dsub.add_parser("list", add_help=False).set_defaults(func=_simple("dance.list"))
    dp = dsub.add_parser("play", add_help=False); dp.add_argument("name"); dp.set_defaults(func=_simple("dance.play"))
    dsub.add_parser("stop", add_help=False).set_defaults(func=_simple("dance.stop"))

    # safety
    sub.add_parser("safe-stop", add_help=False).set_defaults(func=_simple("safe-stop"))
    coll = sub.add_parser("collision", add_help=False)
    cosub = coll.add_subparsers(dest="sub"); cosub.required = True
    cosub.add_parser("detect", add_help=False).set_defaults(func=_simple("collision.detect"))
    cp = cosub.add_parser("predict", add_help=False)
    cp.add_argument("--side", required=True); cp.add_argument("--x", type=float, required=True)
    cp.add_argument("--y", type=float, required=True); cp.add_argument("--z", type=float, required=True)
    cp.set_defaults(func=_simple("collision.predict"))

    # daemon + bench (shared)
    add_daemon_commands(sub, _client)
    sub.add_parser("manifest", add_help=False).set_defaults(
        func=lambda a: (sys.stdout.write(MANIFEST.read_text()), 0)[1])
    return p

def _imu_stream(args):
    import time
    ex = _exec(args); fmt = _fmt(args)
    try:
        period = 1.0 / max(1, args.hz)
        while True:
            fmt.emit(ex.call("imu.get")); time.sleep(period)
    except KeyboardInterrupt:
        return 0
    finally:
        ex.close()

def main(argv=None):
    args = _build_parser().parse_args(argv)
    try: return args.func(args)
    except KeyboardInterrupt: return 130
    except SafetyError as e: return _fail(f"safety: {e}", 2)
