"""AGIBOT X2 CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/agibot-x2.sock"

def _client():
    from agibot_x2_cli.client import get_client
    return get_client(os.environ.get("AGIBOT_X2_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"agibot-x2: {m}\n"); return c
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
    p = build_base_parser("agibot-x2", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # action
    act = sub.add_parser("action", add_help=False)
    asub = act.add_subparsers(dest="sub"); asub.required = True
    a_set = asub.add_parser("set", add_help=False); a_set.add_argument("mode"); a_set.set_defaults(func=_simple("action.set"))
    asub.add_parser("get", add_help=False).set_defaults(func=_simple("action.get"))
    asub.add_parser("list", add_help=False).set_defaults(func=_simple("action.list"))

    # input source
    inp = sub.add_parser("input", add_help=False)
    isub = inp.add_subparsers(dest="sub"); isub.required = True
    ia = isub.add_parser("add", add_help=False); ia.add_argument("name"); ia.add_argument("--priority", type=int, default=40); ia.add_argument("--timeout", type=int, default=1000); ia.set_defaults(func=_simple("input.add"))
    ie = isub.add_parser("enable", add_help=False); ie.add_argument("name"); ie.set_defaults(func=_simple("input.enable"))
    id_ = isub.add_parser("disable", add_help=False); id_.add_argument("name"); id_.set_defaults(func=_simple("input.disable"))
    idel = isub.add_parser("delete", add_help=False); idel.add_argument("name"); idel.set_defaults(func=_simple("input.delete"))
    isub.add_parser("get", add_help=False).set_defaults(func=_simple("input.get"))

    # walk
    walk = sub.add_parser("walk", add_help=False)
    wsub = walk.add_subparsers(dest="sub")
    walk.add_argument("--forward", type=float, default=0.0); walk.add_argument("--lateral", type=float, default=0.0); walk.add_argument("--angular", type=float, default=0.0)
    walk.set_defaults(func=_simple("walk"))
    wsub.add_parser("stop", add_help=False).set_defaults(func=_simple("walk.stop"))

    # arm
    arm = sub.add_parser("arm", add_help=False)
    armsub = arm.add_subparsers(dest="sub"); armsub.required = True
    a_s = armsub.add_parser("set", add_help=False); a_s.add_argument("--positions", required=True); a_s.set_defaults(func=_simple("arm.set"))
    armsub.add_parser("get", add_help=False).set_defaults(func=_simple("arm.get"))
    armsub.add_parser("home", add_help=False).set_defaults(func=_simple("arm.home"))

    # waist
    waist = sub.add_parser("waist", add_help=False)
    wasub = waist.add_subparsers(dest="sub"); wasub.required = True
    wa_s = wasub.add_parser("set", add_help=False)
    wa_s.add_argument("--yaw", type=float); wa_s.add_argument("--pitch", type=float); wa_s.add_argument("--roll", type=float)
    wa_s.set_defaults(func=_simple("waist.set"))
    wasub.add_parser("get", add_help=False).set_defaults(func=_simple("waist.get"))

    # head
    head = sub.add_parser("head", add_help=False)
    hdsub = head.add_subparsers(dest="sub"); hdsub.required = True
    h_s = hdsub.add_parser("set", add_help=False); h_s.add_argument("--yaw", type=float, default=0.0); h_s.add_argument("--pitch", type=float, default=0.0); h_s.set_defaults(func=_simple("head.set"))
    hdsub.add_parser("get", add_help=False).set_defaults(func=_simple("head.get"))

    # leg
    leg = sub.add_parser("leg", add_help=False)
    lsub = leg.add_subparsers(dest="sub"); lsub.required = True
    l_s = lsub.add_parser("set", add_help=False); l_s.add_argument("--positions", required=True); l_s.set_defaults(func=_simple("leg.set"))
    lsub.add_parser("get", add_help=False).set_defaults(func=_simple("leg.get"))

    # hand
    hand = sub.add_parser("hand", add_help=False)
    hsub = hand.add_subparsers(dest="sub"); hsub.required = True
    hsub.add_parser("type", add_help=False).set_defaults(func=_simple("hand.type"))
    h_s = hsub.add_parser("set", add_help=False); h_s.add_argument("--side", required=True, choices=["left","right"]); h_s.add_argument("--positions", required=True); h_s.set_defaults(func=_simple("hand.set"))
    hg = hsub.add_parser("get", add_help=False); hg.add_argument("--side", default="both"); hg.set_defaults(func=_simple("hand.get"))
    ho = hsub.add_parser("open", add_help=False); ho.add_argument("--side", default="both"); ho.set_defaults(func=_simple("hand.open"))
    hc = hsub.add_parser("close", add_help=False); hc.add_argument("--side", default="both"); hc.set_defaults(func=_simple("hand.close"))

    # motion presets
    motion = sub.add_parser("motion", add_help=False)
    msub = motion.add_subparsers(dest="sub"); msub.required = True
    mp = msub.add_parser("play", add_help=False); mp.add_argument("id", type=int); mp.add_argument("--area", default="full", choices=["left","right","both","full"]); mp.set_defaults(func=_simple("motion.play"))
    msub.add_parser("list", add_help=False).set_defaults(func=_simple("motion.list"))

    # sensors
    imu = sub.add_parser("imu", add_help=False)
    imusub = imu.add_subparsers(dest="sub"); imusub.required = True
    ig = imusub.add_parser("get", add_help=False); ig.add_argument("--source", default="chest", choices=["chest","torso"]); ig.add_argument("--stream", action="store_true"); ig.add_argument("--hz", type=int, default=50)
    ig.set_defaults(func=lambda a: _imu_stream(a) if a.stream else (_fmt(a).emit(_do(a, "imu.get", source=a.source)), 0)[1])

    cam = sub.add_parser("camera", add_help=False)
    csub = cam.add_subparsers(dest="sub"); csub.required = True
    csub.add_parser("list", add_help=False).set_defaults(func=_simple("camera.list"))
    cg = csub.add_parser("get", add_help=False); cg.add_argument("source"); cg.add_argument("--output"); cg.set_defaults(func=_simple("camera.get"))

    sub.add_parser("lidar", add_help=False).set_defaults(func=_simple("lidar.get"))
    tch = sub.add_parser("touch", add_help=False)
    tch.add_argument("--stream", action="store_true"); tch.set_defaults(func=_simple("touch.get"))
    sub.add_parser("battery", add_help=False).set_defaults(func=_simple("battery.status"))

    # interaction
    tts = sub.add_parser("tts", add_help=False)
    ttssub = tts.add_subparsers(dest="sub"); ttssub.required = True
    tp = ttssub.add_parser("play", add_help=False); tp.add_argument("text"); tp.add_argument("--priority", default="mid"); tp.set_defaults(func=_simple("tts.play"))

    audio = sub.add_parser("audio", add_help=False)
    ausub = audio.add_subparsers(dest="sub"); ausub.required = True
    vol = ausub.add_parser("volume", add_help=False)
    vsub = vol.add_subparsers(dest="sub2"); vsub.required = True
    vsub.add_parser("get", add_help=False).set_defaults(func=_simple("audio.volume.get"))
    vs = vsub.add_parser("set", add_help=False); vs.add_argument("level", type=int); vs.set_defaults(func=_simple("audio.volume.set"))
    mute = ausub.add_parser("mute", add_help=False)
    musub = mute.add_subparsers(dest="sub2"); musub.required = True
    musub.add_parser("get", add_help=False).set_defaults(func=_simple("audio.mute.get"))
    ms = musub.add_parser("set", add_help=False); ms.add_argument("on", type=lambda x: x.lower() in ("true","1","yes")); ms.set_defaults(func=_simple("audio.mute.set"))

    face = sub.add_parser("face", add_help=False)
    fsub = face.add_subparsers(dest="sub"); fsub.required = True
    fe = fsub.add_parser("emoji", add_help=False); fe.add_argument("name"); fe.set_defaults(func=_simple("face.emoji"))
    fv = fsub.add_parser("video", add_help=False); fv.add_argument("path"); fv.set_defaults(func=_simple("face.video"))

    led = sub.add_parser("led", add_help=False)
    lsub2 = led.add_subparsers(dest="sub"); lsub2.required = True
    ls = lsub2.add_parser("set", add_help=False)
    ls.add_argument("--r", type=int, default=0); ls.add_argument("--g", type=int, default=0); ls.add_argument("--b", type=int, default=0)
    ls.add_argument("--mode", default="static", choices=["static","breathing","flash"])
    ls.set_defaults(func=_simple("led.set"))

    # joint (shared) + all-state
    add_joint_commands(sub, _exec)
    sub.add_parser("joint-all-state", add_help=False).set_defaults(func=_simple("joint.all-state"))

    # daemon + bench (shared)
    add_daemon_commands(sub, _client)
    sub.add_parser("manifest", add_help=False).set_defaults(func=lambda a: (sys.stdout.write(MANIFEST.read_text()), 0)[1])
    return p

def _imu_stream(args):
    import time
    ex = _exec(args); fmt = _fmt(args)
    try:
        period = 1.0 / max(1, args.hz)
        while True:
            fmt.emit(ex.call("imu.get", source=args.source)); time.sleep(period)
    except KeyboardInterrupt:
        return 0
    finally:
        ex.close()

def main(argv=None):
    args = _build_parser().parse_args(argv)
    try: return args.func(args)
    except KeyboardInterrupt: return 130
    except SafetyError as e: return _fail(f"safety: {e}", 2)
