"""
Genere les 3 blocs CSS de tokens (:root, :root[data-theme=violet],
:root[data-theme=light]) a partir de _themes_dump.json (valeurs REELLEMENT
calculees par le JS source, cf. extract_claude_design.cjs) + des alias
LEGACY necessaires a la retro-compatibilite des tests (--gold, --muted2, etc.
cf. tests/test_webui.py qui regexe --bg/--panel/--muted2 en HEX plat dans
:root{}).

Script de DEV (scratch, pas livre dans l'app). Imprime les 3 blocs sur
stdout -- copies/verifies ensuite a la main dans trading/webui.py (le
generateur produit les VALEURS, la structure/l'ordre des selecteurs reste une
decision humaine relue).
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
THEMES = json.loads((BASE / "docs" / "design" / "from_claude_design" / "_themes_dump.json").read_text(encoding="utf-8"))

# --muted2 par theme (>=4.5:1 sur --bg ET --panel, verifie par
# scripts/_contrast_check.py). Ambre = valeur EXISTANTE (contrat teste),
# violet/light = meme methode (blend muted->txt a t=0.14).
MUTED2 = {
    "dark": "#8b97a6",   # existant, teste par tests/test_webui.py (NE PAS CHANGER)
    "violet": "#a59fc1",
    "light": "#4b5662",
}

# Alias LEGACY -> cle design (pour ne rien casser des selecteurs existants
# .brand/.tab/.pill/etc qui consomment --gold/--gold-bright/--gold-soft/
# --bg-deep/--line-gold).
LEGACY_ALIASES = {
    "gold": "--accent",
    "gold-bright": "--accentBright",
    "gold-soft": "--accentSoft",
    "bg-deep": "--code",
    "line-gold": "--lineAccent",
}

# Ordre + noms kebab des tokens "design" a exposer tels quels (nouveaux noms,
# utilises par les CSS de composants portes du design).
DESIGN_TOKENS = [
    "--code", "--panel2", "--panelGrad", "--lineAccent", "--accent",
    "--accentBright", "--accentSoft", "--accentInk", "--onAccent", "--accentText",
    "--logoGlow", "--logoInk", "--pillFill", "--warnFill", "--warnBig",
    "--accentFill", "--warn", "--onDanger", "--accent2", "--accent2Soft",
    "--downSoft", "--upSoft", "--navBg", "--feesGrad", "--feesLine",
    "--shadow", "--glow", "--track",
]


def kebab(name):
    out = []
    for c in name:
        if c.isupper():
            out.append("-" + c.lower())
        else:
            out.append(c)
    return "".join(out)


def render_block(selector, theme_key, include_base_legacy):
    T = dict(THEMES[theme_key])
    # panel2 = premier stop de panelGrad (design ne l'expose pas comme token
    # separe, mais le CSS legacy --panel2 en a besoin) -- extrait a la main
    # par theme (valeurs vues dans _themes_dump.json).
    panel2 = {"violet": "#1a1734", "dark": "#1b212b", "light": "#ffffff"}[theme_key]
    lines = [selector + "{"]
    if include_base_legacy:
        lines.append(f"  --bg:{T['--bg']}; --bg-deep:{T['--code']}; --panel:{T['--panel']}; --panel2:{panel2};")
        lines.append(f"  --line:{T['--line']}; --line-gold:{T['--lineAccent']};")
        lines.append(f"  --txt:{T['--txt']}; --muted:{T['--muted']}; --muted2:{MUTED2[theme_key]};")
        lines.append(f"  --gold:{T['--accent']}; --gold-bright:{T['--accentBright']}; --gold-soft:{T['--accentSoft']};")
        lines.append(f"  --up:{T['--up']}; --down:{T['--down']}; --blue:{T['--blue']};")
        lines.append('  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;')
        lines.append('  --mono:ui-monospace,"SF Mono",Consolas,"Liberation Mono",Menlo,monospace;')
        lines.append('  --sans:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;')
    else:
        lines.append(f"  --bg:{T['--bg']}; --bg-deep:{T['--code']}; --panel:{T['--panel']}; --panel2:{panel2};")
        lines.append(f"  --line:{T['--line']}; --line-gold:{T['--lineAccent']};")
        lines.append(f"  --txt:{T['--txt']}; --muted:{T['--muted']}; --muted2:{MUTED2[theme_key]};")
        lines.append(f"  --gold:{T['--accent']}; --gold-bright:{T['--accentBright']}; --gold-soft:{T['--accentSoft']};")
        lines.append(f"  --up:{T['--up']}; --down:{T['--down']}; --blue:{T['--blue']};")
    for tok in DESIGN_TOKENS:
        if tok in ("--code", "--lineAccent", "--accent", "--accentBright", "--accentSoft", "--downSoft", "--upSoft"):
            continue  # deja exposes via l'alias legacy ci-dessus
        val = T.get(tok)
        if val is None:
            continue
        lines.append(f"  {kebab(tok)}:{val};")
    lines.append(f"  --page-bg:{T['background']};")
    lines.append("}")
    return "\n".join(lines)


print(render_block(":root", "dark", True))
print()
print(render_block(':root[data-theme="violet"]', "violet", False))
print()
print(render_block(':root[data-theme="light"]', "light", False))
