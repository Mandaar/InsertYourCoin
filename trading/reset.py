"""
Hygiene de mesure : remise a zero du paper trading SANS rien detruire.

Pourquoi : le P&L affiche par le paper est cumule depuis le tout premier
demarrage. Tant qu'on ne peut pas repartir proprement, un changement de
configuration reste noye dans l'heritage de la precedente et aucun A/B n'est
lisible. Remettre a zero ne cree evidemment aucun gain : ca rend la MESURE
lisible, rien de plus.

Regle absolue (conservation) : on ARCHIVE, on n'ecrase JAMAIS. Les fichiers
existants sont RENOMMES avec un horodatage ; si un nom d'archive est deja pris,
on suffixe (-2, -3, ...) au lieu de l'ecraser. Aucune donnee n'est supprimee.

Fonctions PURES cote decision (`archive_name`) + effets de bord isoles
(`archive_file`, `reset_paper`), testables sans reseau via tmp_path.
"""
import datetime as dt
import json
from pathlib import Path

import config
from .paper_trader import fresh_state

# Horodatage sur des caracteres valides pour un nom de fichier Windows ET Unix
# (pas de ':' -- interdit sous Windows).
STAMP_FORMAT = "%Y-%m-%dT%H-%M-%S"


def stamp(when=None) -> str:
    """Horodatage d'archive ('2026-09-01T14-30-00'). `when` = datetime injectable."""
    return (when or dt.datetime.now()).strftime(STAMP_FORMAT)


def archive_name(path, when=None, taken=None) -> Path:
    """
    Nom d'archive pour `path` : `<base>.<horodatage><suffixe>`
    (ex. `paper_state.json` -> `paper_state.2026-09-01T14-30-00.json`).

    PURE : ne touche pas au disque. `taken` = predicat "ce nom est deja pris"
    (par defaut : le fichier existe). Tant que le nom est pris, on ajoute
    `-2`, `-3`, ... : une archive existante n'est JAMAIS ecrasee.
    """
    p = Path(path)
    taken = taken if taken is not None else (lambda q: Path(q).exists())
    base = p.with_suffix("")          # chemin sans l'extension
    ext = p.suffix                    # '.json' / '.csv' (peut etre vide)
    s = stamp(when)
    candidate = Path(f"{base}.{s}{ext}")
    n = 1
    while taken(candidate):
        n += 1
        candidate = Path(f"{base}.{s}-{n}{ext}")
    return candidate


def archive_file(path, when=None):
    """
    Renomme `path` vers son nom d'archive. Retourne le chemin d'archive, ou None
    si le fichier n'existait pas (rien a archiver, ce n'est pas une erreur).
    """
    p = Path(path)
    if not p.exists():
        return None
    target = archive_name(p, when=when)
    p.rename(target)                  # RENAME : le contenu n'est jamais reecrit
    return target


def reset_paper(state_file="paper_state.json", stats_file="paper_stats.csv",
                initial_capital=None, when=None) -> dict:
    """
    Archive l'etat et le CSV de stats du paper, puis ecrit un etat NEUF a
    `initial_capital` (defaut config.INITIAL_CAPITAL).

    L'etat neuf est ecrit sur le disque IMMEDIATEMENT (et non laisse en memoire) :
    la remise a zero est ainsi acquise et observable meme si la boucle de paper
    qui suit echoue (reseau, arret immediat).

    Retourne : {"archived": [(source, archive), ...], "state_file": ...,
                "initial_capital": ...}. `archived` ne contient que les fichiers
    qui EXISTAIENT.
    """
    cap = config.INITIAL_CAPITAL if initial_capital is None else float(initial_capital)
    when = when or dt.datetime.now()
    archived = []
    for src in (state_file, stats_file):
        dest = archive_file(src, when=when)
        if dest is not None:
            archived.append((Path(src), dest))
    state_path = Path(state_file)
    # `fresh_state` vient de paper_trader : UNE seule definition du schema d'etat
    # neuf, partagee avec le premier demarrage (pas de schema parallele).
    state_path.write_text(json.dumps(fresh_state(cap), indent=2))
    return {"archived": archived, "state_file": state_path, "initial_capital": cap}


def format_reset(res: dict) -> str:
    """Rendu texte du resultat d'un reset (ce qui a ete archive, ou rien)."""
    L = ["Remise a zero du paper trading (aucune donnee supprimee) :"]
    if res["archived"]:
        for src, dest in res["archived"]:
            L.append(f"  archive : {src}  ->  {dest}")
    else:
        L.append("  (aucun fichier existant a archiver)")
    L.append(f"  etat neuf : {res['state_file']} a {res['initial_capital']:,.2f}")
    return "\n".join(L)
