"""Find which PIDs are actually rendering audio right now.

Run while on a Teams call with audio playing. Enumerates every pycaw
audio session, tracks State transitions, and walks the parent process
chain. Any session whose State == Active during the sample window
is producing audio to the endpoint at that instant.

Use: python scripts/find_call_audio_pid.py
"""
import time
import psutil
from pycaw.pycaw import AudioUtilities


STATE_NAMES = {0: "Inactive", 1: "Active", 2: "Expired"}


def parent_chain(pid, max_depth=8):
    names = []
    try:
        p = psutil.Process(pid)
        for _ in range(max_depth):
            parent = p.parent()
            if parent is None:
                break
            try:
                names.append(f"{parent.name()}({parent.pid})")
            except Exception:
                break
            p = parent
    except Exception:
        pass
    return " -> ".join(names) if names else "(no parents)"


def display_name(session):
    try:
        return session.DisplayName or ""
    except Exception:
        return ""


def snapshot():
    rows = []
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception as e:
        print(f"GetAllSessions failed: {e}")
        return rows

    for session in sessions:
        if session.Process is None:
            continue
        pid = session.Process.pid
        try:
            name = session.Process.name()
        except Exception:
            name = "?"
        state = getattr(session, "State", -1)
        rows.append((pid, name, state, display_name(session)))
    return rows


def main():
    print("Sampling pycaw sessions every 500 ms for 12 seconds.")
    print("Play/talk in the Teams call while this runs.\n")

    pid_info = {}  # pid -> {name, display, active_count, states_seen}

    samples = 24
    for _ in range(samples):
        for pid, name, state, disp in snapshot():
            if pid not in pid_info:
                pid_info[pid] = {
                    "name": name,
                    "display": disp,
                    "active_count": 0,
                    "states_seen": set(),
                }
            info = pid_info[pid]
            info["states_seen"].add(state)
            if state == 1:
                info["active_count"] += 1
            if disp and not info["display"]:
                info["display"] = disp
        time.sleep(0.5)

    print(
        f"{'PID':>8}  {'Process':<28}  "
        f"{'Active/N':<10}  {'States':<22}  "
        f"{'DisplayName':<30}  Parents"
    )
    print("-" * 140)
    by_active = sorted(
        pid_info.keys(),
        key=lambda p: pid_info[p]["active_count"],
        reverse=True,
    )
    for pid in by_active:
        info = pid_info[pid]
        states_str = ",".join(STATE_NAMES.get(s, str(s)) for s in sorted(info["states_seen"]))
        ratio = f"{info['active_count']}/{samples}"
        disp = info["display"][:30]
        print(
            f"{pid:>8}  {info['name']:<28}  "
            f"{ratio:<10}  {states_str:<22}  "
            f"{disp:<30}  {parent_chain(pid)}"
        )

    print()
    print("Look at rows with Active/N > 0 during the call.")
    print("Those PIDs are the actual call audio renderers —")
    print("any that aren't ms-teams or an ms-teams descendant are what")
    print("per-app capture is missing.")


if __name__ == "__main__":
    main()
