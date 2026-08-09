# InsertYourCoin -- image de deploiement (paper trading + monitoring web).
#
# Une SEULE image, utilisee par les 3 services du docker-compose.yml
# (paper / monitor) avec des commandes differentes -- cf. docker-compose.yml.
# Le service `proxy` (Caddy) utilise une image officielle separee.
#
# Python 3.14 : version testee localement (venv .venv, 599 tests verts,
# 2026-08-09) -- requirements.txt documente truststore comme compatible
# 3.11 a 3.14. On reproduit l'environnement teste plutot que d'en deviner
# un autre (E7 : pas de degradation silencieuse de ce qui a ete valide).
FROM python:3.14-slim

# --- Utilisateur non-root ----------------------------------------------------
# uid/gid 1000 : convention courante (1er utilisateur non-root sur la plupart
# des distributions Debian/Ubuntu), pas de raison specifique au-dela de la
# lisibilite si l'operateur doit un jour aligner un uid hote.
RUN groupadd -g 1000 iyc && useradd -m -u 1000 -g iyc -s /usr/sbin/nologin iyc

WORKDIR /app

# --- Dependances --------------------------------------------------------------
# Couche separee du code applicatif : le cache Docker ne re-telecharge les
# paquets que si requirements.txt change, pas a chaque modification de code.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# --- Code applicatif ----------------------------------------------------------
# Copie SELECTIVE (pas de `COPY . .`) : jamais le venv/.git/tests/docs/assets
# hote, meme si le .dockerignore les couvre deja (defense en profondeur --
# une COPY explicite ne peut pas emporter un fichier sensible par erreur).
COPY main.py config.py lancer.py ./
COPY trading/ ./trading/

# --- Repertoire de donnees persistantes ---------------------------------------
# Mount point du VOLUME NOMME Docker (docker-compose.yml : iyc_data:/data).
# Pre-cree + chowne ICI (et pas via un ENTRYPOINT/chown au demarrage) : Docker
# initialise un volume nomme VIDE en copiant le contenu -- ET les droits --
# du chemin correspondant dans l'image, au premier conteneur qui le monte.
# Resultat : /data appartient a `iyc` des le premier `docker compose up`,
# sans script d'entrypoint ni gosu/su-exec. A VERIFIER sur la cible reelle
# (mecanisme Docker documente, non testable sans daemon Docker sur cette
# machine -- cf. rapport de fin de mission).
RUN mkdir -p /data && chown -R iyc:iyc /app /data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER iyc

# Pas d'ENTRYPOINT/CMD par defaut : chaque service du docker-compose.yml
# fournit sa propre commande (`paper` ou `monitor`). Une commande par
# defaut ici inviterait a lancer le conteneur sans argument reflechi --
# on prefere que ce soit toujours explicite dans le compose (source de
# verite unique des parametres de deploiement).
