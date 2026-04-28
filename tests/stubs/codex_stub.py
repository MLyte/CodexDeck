from __future__ import annotations

import argparse
import sys
import time


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["success", "fail", "sleep", "spam"], default="success")
    parser.add_argument("--lines", type=int, default=200)
    parser.add_argument("--delay", type=float, default=0.01)
    parser.add_argument("todo", nargs="?")
    args = parser.parse_args(argv)

    print(f"codex_stub mode={args.mode} todo={args.todo}", flush=True)
    if args.mode == "success":
        print("stub success", flush=True)
        return 0
    if args.mode == "fail":
        print("[ERROR] stub fail", flush=True)
        return 1
    if args.mode == "sleep":
        try:
            while True:
                print("stub sleeping", flush=True)
                time.sleep(args.delay)
        except KeyboardInterrupt:
            return 130
    if args.mode == "spam":
        for index in range(args.lines):
            print(f"spam line {index:04d}", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
