"""
Options runtime de l'application (fonctions PURES, sans reseau).

Deux responsabilites, volontairement etroites :
- `options.json` (racine projet) : preferences modifiables a chaud depuis la page
  /options du dashboard. Pour l'instant un seul reglage : le niveau de logs du paper.
- `.env` (racine projet) : ecriture PRUDENTE des cles API Kraken sans jamais
  ecraser les autres lignes (commentaires inclus), et sans JAMAIS logger/afficher
  les VALEURS des cles.

Securite : aucune fonction ici ne print/log une valeur de cle. `keys_configured`
renvoie un booleen, jamais le contenu. `update_env_file` refuse toute valeur
contenant un retour a la ligne (anti-injection dans le .env).
"""
import json
from pathlib import Path

# Niveaux de logs valides pour le paper trading (voir paper_trader._Trader._trace).
LOG_LEVELS = ("leger", "moyen", "complet")
DEFAULT_OPTIONS = {"log_level": "moyen"}

# Cles ecrites/relues dans le .env (jamais leur VALEUR exposee).
_ENV_KEY_NAMES = ("KRAKEN_API_KEY", "KRAKEN_API_SECRET")


def _project_root() -> Path:
    """Racine du projet = dossier PARENT de trading/ (meme convention que monitor)."""
    return Path(__file__).resolve().parent.parent


def OPTIONS_PATH() -> Path:
    """Chemin par defaut du fichier d'options (racine projet / options.json)."""
    return _project_root() / "options.json"


def _env_path_default() -> Path:
    return _project_root() / ".env"


def read_options(path=None) -> dict:
    """
    Lit options.json. Ne leve JAMAIS : en cas d'absence/corruption/typage, on
    retourne des defauts surs. Le niveau de logs est valide ; tout niveau inconnu
    retombe sur le defaut. Les autres cles eventuelles sont conservees telles quelles.
    """
    p = Path(path) if path else OPTIONS_PATH()
    opts = dict(DEFAULT_OPTIONS)
    try:
        if not p.exists() or p.stat().st_size == 0:
            return opts
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return opts
        opts.update(data)
    except Exception:
        return dict(DEFAULT_OPTIONS)
    # Garde-fou : un log_level invalide retombe sur le defaut (jamais d'exception).
    if opts.get("log_level") not in LOG_LEVELS:
        opts["log_level"] = DEFAULT_OPTIONS["log_level"]
    return opts


def write_options(opts, path=None) -> None:
    """
    Ecrit options.json (JSON indente). VALIDE le niveau de logs : un niveau hors
    ("leger","moyen","complet") leve ValueError (rien n'est ecrit dans ce cas).
    """
    if not isinstance(opts, dict):
        raise ValueError("opts doit etre un dict")
    level = opts.get("log_level", DEFAULT_OPTIONS["log_level"])
    if level not in LOG_LEVELS:
        raise ValueError(f"log_level invalide : {level!r} (attendu : {LOG_LEVELS})")
    p = Path(path) if path else OPTIONS_PATH()
    p.write_text(json.dumps(opts, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _parse_env(text: str):
    """
    Decoupe un .env en liste de tokens preservant l'ordre et les lignes etrangeres.
    Chaque element est soit ("kv", KEY, ligne_brute) pour une affectation KEY=...,
    soit ("raw", None, ligne_brute) pour tout le reste (commentaires, vide, autre).
    """
    tokens = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            # Cle plausible (pas d'espace interne) -> on la traite comme affectation.
            if key and " " not in key and "\t" not in key:
                tokens.append(("kv", key, raw))
                continue
        tokens.append(("raw", None, raw))
    return tokens


def update_env_file(updates: dict, env_path=None) -> None:
    """
    Met a jour le .env en PRESERVANT les lignes existantes non concernees (les
    commentaires et toute autre variable restent intacts, dans l'ordre). Remplace
    la valeur d'une cle deja presente, sinon l'ajoute a la fin. Cree le fichier au
    besoin.

    Securite : ne logge/print JAMAIS les valeurs. Refuse (ValueError) toute valeur
    contenant un retour a la ligne (anti-injection : empeche d'ecrire des lignes
    .env supplementaires via une valeur).
    """
    if not isinstance(updates, dict) or not updates:
        return
    for k, v in updates.items():
        if v is None:
            continue
        if "\n" in str(v) or "\r" in str(v):
            # Ne PAS inclure la valeur dans le message (securite).
            raise ValueError(f"valeur invalide pour {k} : retour a la ligne interdit")

    p = Path(env_path) if env_path else _env_path_default()
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    tokens = _parse_env(text)

    pending = {k: str(v) for k, v in updates.items() if v is not None}
    out_lines = []
    for kind, key, raw in tokens:
        if kind == "kv" and key in pending:
            out_lines.append(f"{key}={pending.pop(key)}")
        else:
            out_lines.append(raw)
    # Cles non encore presentes : ajoutees a la fin (ordre d'iteration du dict).
    for k, v in pending.items():
        out_lines.append(f"{k}={v}")

    content = "\n".join(out_lines)
    if content and not content.endswith("\n"):
        content += "\n"
    p.write_text(content, encoding="utf-8")


def keys_configured(env_path=None) -> bool:
    """
    Vrai si un .env existe avec les 2 cles Kraken NON vides. Ne retourne JAMAIS
    les valeurs (booleen seul). Ne leve pas.
    """
    p = Path(env_path) if env_path else _env_path_default()
    try:
        if not p.exists():
            return False
        text = p.read_text(encoding="utf-8")
    except Exception:
        return False
    found = {name: False for name in _ENV_KEY_NAMES}
    for kind, key, raw in _parse_env(text):
        if kind == "kv" and key in found:
            value = raw.split("=", 1)[1].strip() if "=" in raw else ""
            found[key] = bool(value)
    return all(found.values())
