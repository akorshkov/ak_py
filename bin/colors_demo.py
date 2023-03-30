#!/usr/bin/env python
"""Print examples of various colors."""

import argparse
from ak.color import ColorFmt


def _gen_lines_of_sample_report(descr, modifiers):
    # generate lines of colors demo text
    result_len = 47  # each line will have that many printable characters

    separator = " " * result_len
    empty = ColorFmt.get_plaintext_fmt()("")
    cspace = ColorFmt.get_plaintext_fmt()(" ")

    yield f"{descr:{result_len}}"
    yield separator

    # named colors
    named_colors = [
        [(0, 'BLACK'), (1, 'RED'), (2, 'GREEN'), (3, 'YELLOW')],
        [(4, 'BLUE'), (5, 'MAGENTA'), (6, 'CYAN'), (7, 'WHITE')],
    ]

    for colors_pairs in zip(*named_colors):
        texts = []
        for color_id, color_name in colors_pairs:
            fmt = ColorFmt(color_name, **modifiers)
            t = fmt(f"{color_id:2}. {color_name}")
            t += " " * (15 - len(t))
            texts.append(t)
        text = empty.join(texts)
        yield f"{text:{result_len}}"
    yield separator

    # colors in range 16
    for base_color_id in range(8):
        texts = []
        for color_id in (base_color_id, base_color_id + 8):
            fmt = ColorFmt(color_id, **modifiers)
            t = fmt(f"COLOR {color_id:2}")
            t += " " * (15 - len(t))
            texts.append(t)
        text = empty.join(texts)
        yield f"{text:{result_len}}"
    yield separator

    # colors in range 256 corresponding to (r, g, b) pattern
    for r in range(6):
        for g in range(6):
            texts = []
            for b in range(6):
                fmt = ColorFmt((r, g, b), **modifiers)
                t = fmt(f"{r}{g}{b}={r*36 + g*6 + b + 16:03}")
                texts.append(t)
            text = cspace.join(texts)
            yield f"{text:{result_len}}"
        yield separator
    yield separator

    # colors corresponding to shades of gray
    for b in (0, 12):
        texts = []
        for i in range(12):
            color_id = 232 + b + i
            fmt = ColorFmt(color_id)
            t = fmt(str(color_id))
            texts.append(t)
        text = cspace.join(texts)
        yield f"{text:{result_len}}"

def main():
    parser = argparse.ArgumentParser(
        description="Run this script to print examples of colors")
    parser.parse_args()

    fmt_opts = [
        ('--', {}),
        ('bold', {"bold": True}),
        ('faint', {'faint': True}),
        ('both', {'bold': True, 'faint': True}),
    ]

    gens = [
        _gen_lines_of_sample_report(descr, modifiers)
        for (descr, modifiers) in fmt_opts
    ]

    for parts in zip(*gens):
        print("  ".join(parts))


if __name__ == '__main__':
    main()
