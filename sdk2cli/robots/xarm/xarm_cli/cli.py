"""UFACTORY xArm CLI."""
from __future__ import annotations
import argparse, sys, os
from pathlib import Path
from robot_cli_core.base_client import SafetyError
from robot_cli_core.daemon import get_executor
from robot_cli_core.formatter import Formatter
from robot_cli_core.cli_builder import build_base_parser, add_joint_commands, add_daemon_commands

MANIFEST = Path(__file__).resolve().parent.parent / "manifest.txt"
SOCKET = "/tmp/xarm.sock"

def _client():
    from xarm_cli.client import get_client
    return get_client(os.environ.get("XARM_BACKEND", "mock"))

def _exec(args): return get_executor(Path(args.socket), _client)
def _fmt(args): return Formatter(args.format)
def _fail(m, c=1): sys.stderr.write(f"xarm: {m}\n"); return c
def _do(args, cmd, **kw):
    ex = _exec(args)
    try: return ex.call(cmd, **kw)
    finally: ex.close()
def _simple(cmd):
    def handler(a):
        kw = {k: v for k, v in vars(a).items() if k not in ("func","command","socket","backend","format") and v is not None}
        _fmt(a).emit(_do(a, cmd, **kw)); return 0
    return handler

def _csv_floats(s):
    """Parse a comma-separated string of floats."""
    return [float(x.strip()) for x in s.split(",")]


def _build_parser():
    p = build_base_parser("xarm", MANIFEST, SOCKET)
    sub = p.add_subparsers(dest="command"); sub.required = True

    # ── State / Enable / Disable ────────────────────────────────────
    sub.add_parser("get-state", add_help=False).set_defaults(func=_simple("get_state"))

    ss = sub.add_parser("set-state", add_help=False)
    ss.add_argument("state", type=int, choices=[0, 3, 4], help="0=enable, 3=pause, 4=stop")
    ss.set_defaults(func=_simple("set_state"))

    sm = sub.add_parser("set-mode", add_help=False)
    sm.add_argument("mode", type=int, help="0=position, 1=servo, 2=joint_vel, 4=cart_vel")
    sm.set_defaults(func=_simple("set_mode"))

    sub.add_parser("enable", add_help=False).set_defaults(func=_simple("enable"))

    # ── Safety ──────────────────────────────────────────────────────
    sub.add_parser("emergency-stop", add_help=False).set_defaults(func=_simple("emergency_stop"))
    sub.add_parser("clean-error", add_help=False).set_defaults(func=_simple("clean_error"))
    sub.add_parser("clean-warn", add_help=False).set_defaults(func=_simple("clean_warn"))

    # ── Motion ──────────────────────────────────────────────────────
    mj = sub.add_parser("move-joint", add_help=False)
    mj.add_argument("--angles", type=_csv_floats, required=True, help="7 comma-separated angles (deg)")
    mj.set_defaults(func=_simple("move_joint"))

    ml = sub.add_parser("move-line", add_help=False)
    ml.add_argument("--pose", type=_csv_floats, required=True, help="x,y,z,roll,pitch,yaw (mm,rad)")
    ml.set_defaults(func=_simple("move_line"))

    ma = sub.add_parser("move-arc-line", add_help=False)
    ma.add_argument("--pose", type=_csv_floats, required=True, help="x,y,z,roll,pitch,yaw (mm,rad)")
    ma.set_defaults(func=_simple("move_arc_line"))

    sub.add_parser("move-circle", add_help=False).set_defaults(func=_simple("move_circle"))
    sub.add_parser("move-gohome", add_help=False).set_defaults(func=_simple("move_gohome"))

    # ── Servo control ───────────────────────────────────────────────
    sa = sub.add_parser("set-servo-angle", add_help=False)
    sa.add_argument("--servo-id", type=int, required=True, help="servo index 1-7")
    sa.add_argument("--angle", type=float, required=True, help="target angle (deg)")
    sa.set_defaults(func=lambda a: (_fmt(a).emit(_do(a, "set_servo_angle", servo_id=a.servo_id, angle=a.angle)), 0)[1])

    sc = sub.add_parser("set-servo-cartesian", add_help=False)
    sc.add_argument("--pose", type=_csv_floats, required=True, help="x,y,z,roll,pitch,yaw")
    sc.set_defaults(func=_simple("set_servo_cartesian"))

    # ── Velocity control ────────────────────────────────────────────
    vjv = sub.add_parser("vc-set-joint-velocity", add_help=False)
    vjv.add_argument("--speeds", type=_csv_floats, required=True, help="7 comma-separated speeds (deg/s)")
    vjv.set_defaults(func=_simple("vc_set_joint_velocity"))

    vcv = sub.add_parser("vc-set-cartesian-velocity", add_help=False)
    vcv.add_argument("--speeds", type=_csv_floats, required=True, help="6 speeds: vx,vy,vz,wx,wy,wz")
    vcv.set_defaults(func=_simple("vc_set_cartesian_velocity"))

    # ── Position queries ────────────────────────────────────────────
    sub.add_parser("get-position", add_help=False).set_defaults(func=_simple("get_position"))
    sub.add_parser("get-servo-angle", add_help=False).set_defaults(func=_simple("get_servo_angle"))

    # ── TCP config ──────────────────────────────────────────────────
    tl = sub.add_parser("set-tcp-load", add_help=False)
    tl.add_argument("--weight", type=float, required=True, help="payload weight (kg)")
    tl.add_argument("--center", type=_csv_floats, default=None, help="center of gravity x,y,z (mm)")
    tl.set_defaults(func=_simple("set_tcp_load"))

    to = sub.add_parser("set-tcp-offset", add_help=False)
    to.add_argument("--offset", type=_csv_floats, required=True, help="x,y,z,roll,pitch,yaw")
    to.set_defaults(func=_simple("set_tcp_offset"))

    cs = sub.add_parser("set-collision-sensitivity", add_help=False)
    cs.add_argument("--level", type=int, required=True, help="0-5, 0=off")
    cs.set_defaults(func=_simple("set_collision_sensitivity"))

    # ── Gripper ─────────────────────────────────────────────────────
    grip = sub.add_parser("gripper", add_help=False)
    gsub = grip.add_subparsers(dest="gripper_cmd"); gsub.required = True

    ge = gsub.add_parser("enable", add_help=False)
    ge.add_argument("--on", type=int, choices=[0, 1], default=1, help="1=enable, 0=disable")
    ge.set_defaults(func=lambda a: (_fmt(a).emit(_do(a, "gripper.enable", on=bool(a.on))), 0)[1])

    gp = gsub.add_parser("position", add_help=False)
    gp.add_argument("--pos", type=float, required=True, help="0-850, 0=closed 850=open")
    gp.set_defaults(func=lambda a: (_fmt(a).emit(_do(a, "gripper.position", pos=a.pos)), 0)[1])

    gs = gsub.add_parser("speed", add_help=False)
    gs.add_argument("--speed", type=float, required=True, help="gripper speed (r/min)")
    gs.set_defaults(func=lambda a: (_fmt(a).emit(_do(a, "gripper.speed", speed=a.speed)), 0)[1])

    gsub.add_parser("get", add_help=False).set_defaults(func=_simple("gripper.get"))

    # ── I/O ─────────────────────────────────────────────────────────
    tgpio = sub.add_parser("tgpio", add_help=False)
    tsub = tgpio.add_subparsers(dest="tgpio_cmd"); tsub.required = True

    tsd = tsub.add_parser("set-digital", add_help=False)
    tsd.add_argument("--ionum", type=int, required=True, help="IO number 0 or 1")
    tsd.add_argument("--value", type=int, required=True, choices=[0, 1])
    tsd.set_defaults(func=lambda a: (_fmt(a).emit(_do(a, "tgpio.set_digital", ionum=a.ionum, value=a.value)), 0)[1])

    tsub.add_parser("get-digital", add_help=False).set_defaults(func=_simple("tgpio.get_digital"))

    # ── Joint (shared from core) ────────────────────────────────────
    add_joint_commands(sub, _exec)

    # ── Daemon + bench (shared from core) ───────────────────────────
    add_daemon_commands(sub, _client)
    sub.add_parser("manifest", add_help=False).set_defaults(func=lambda a: (sys.stdout.write(MANIFEST.read_text()), 0)[1])

    return p


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try: return args.func(args)
    except KeyboardInterrupt: return 130
    except SafetyError as e: return _fail(f"safety: {e}", 2)
