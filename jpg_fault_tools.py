#!/usr/bin/env python3
"""
Utility CLI for JPEG fault tolerance tools.

Currently supports inserting a custom APPn segment.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from jpeg_fault.core.tools import insert_custom_appn, output_path_for, resolve_appn_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JPEG fault tolerance utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("insert-appn", help="Insert a custom APPn segment into a JPEG")
    p_ins.add_argument("input", help="Input JPEG file")
    p_ins.add_argument("--appn", type=int, required=True, help="APPn index (0..15)")
    p_ins.add_argument(
        "--payload-hex",
        help="Hex payload (whitespace allowed). Mutually exclusive with --payload-file.",
    )
    p_ins.add_argument(
        "--payload-file",
        help="Binary payload file. Mutually exclusive with --payload-hex.",
    )
    p_ins.add_argument(
        "--identifier",
        help="Optional identifier string to prefix the payload (ASCII).",
    )
    p_ins.add_argument("-o", "--output", help="Output JPEG path (default: <stem>_appNN.jpg)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.cmd != "insert-appn":
        return 2

    data = Path(args.input).read_bytes()
    try:
        payload = resolve_appn_payload(args.payload_hex or "", args.payload_file or "", args.identifier or "")
        out_data = insert_custom_appn(data, args.appn, payload)
    except ValueError as e:
        print(f"Error: {e}")
        return 2

    out_path = output_path_for(args.input, args.appn, args.output)
    Path(out_path).write_bytes(out_data)
    print(f"Wrote {out_path} (APP{args.appn:02d}, payload={len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
