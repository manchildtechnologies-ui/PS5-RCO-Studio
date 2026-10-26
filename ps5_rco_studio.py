"""Portable Windows GUI entry point."""
import argparse
from studio.app import launch


def main():
    parser = argparse.ArgumentParser(description='PS5 RCO Studio — offline resource editor')
    parser.add_argument('file', nargs='?')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--self-test', action='store_true', help='Run offline GUI acceptance against the initial PUI sample')
    mode.add_argument('--alias-test', action='store_true', help='Run shared-range GUI acceptance against the supplied sample')
    parser.add_argument('--out', help='New acceptance report directory')
    args = parser.parse_args()
    if args.alias_test:
        if not args.file or not args.out: parser.error('--alias-test requires file and --out')
        from studio.alias_smoke import run
        return run(args.file, args.out)
    if args.self_test:
        if not args.file or not args.out: parser.error('--self-test requires file and --out')
        from studio.smoke import run
        return run(args.file, args.out)
    launch(args.file)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
