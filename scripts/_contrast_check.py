"""
Verification de contraste WCAG AA (formule officielle de luminance relative)
pour les 3 themes extraits de Claude Design. Script de DEV (scratch), pas
livre dans l'app -- sert a choisir --muted2 par theme et a produire le
tableau ratio x theme demande par le brief.

Usage : .venv/Scripts/python.exe scripts/_contrast_check.py
"""
import json
from pathlib import Path

THEMES_PATH = Path(__file__).resolve().parent.parent / "docs" / "design" / "from_claude_design" / "_themes_dump.json"


def luminance(hexcolor):
    hexcolor = hexcolor.lstrip("#")
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))

    def lin(c):
        cs = c / 255
        return cs / 12.92 if cs <= 0.03928 else ((cs + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(c1, c2):
    l1, l2 = luminance(c1), luminance(c2)
    l1, l2 = max(l1, l2), min(l1, l2)
    return (l1 + 0.05) / (l2 + 0.05)


def mix(hex_a, hex_b, t):
    """Interpole lineairement (RVB) entre hex_a (t=0) et hex_b (t=1)."""
    a = [int(hex_a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(hex_b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    out = [round(a[i] + (b[i] - a[i]) * t) for i in range(3)]
    return "#" + "".join(f"{v:02x}" for v in out)


def find_muted2(bg, panel, txt, muted):
    """Cherche un ton entre `muted` et `txt` qui atteigne >=4.5:1 sur bg ET panel
    (le pire des deux cas), en gardant la teinte proche de `muted` (lisible,
    discret) plutot que de sauter directement a `txt`."""
    best = None
    for i in range(0, 101):
        t = i / 100.0
        candidate = mix(muted, txt, t)
        r_bg = contrast(candidate, bg)
        r_panel = contrast(candidate, panel)
        if r_bg >= 4.5 and r_panel >= 4.5:
            best = (candidate, r_bg, r_panel, t)
            break
    return best


def main():
    themes = json.loads(THEMES_PATH.read_text(encoding="utf-8"))
    report = {}
    for name, T in themes.items():
        bg, panel, txt, muted = T["--bg"], T["--panel"], T["--txt"], T["--muted"]
        accent, down, up = T["--accent"], T["--down"], T["--up"]
        m2 = find_muted2(bg, panel, txt, muted)
        report[name] = {
            "bg": bg, "panel": panel, "txt": txt, "muted": muted,
            "ratio_txt_bg": contrast(txt, bg),
            "ratio_txt_panel": contrast(txt, panel),
            "ratio_muted_bg": contrast(muted, bg),
            "ratio_muted_panel": contrast(muted, panel),
            "ratio_accent_bg": contrast(accent, bg),
            "ratio_down_bg": contrast(down, bg),
            "ratio_up_bg": contrast(up, bg),
            "muted2": m2,
        }
    for name, r in report.items():
        print(f"--- {name} ---")
        for k, v in r.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.2f}")
            else:
                print(f"  {k}: {v}")
    Path(__file__).with_name("_contrast_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
