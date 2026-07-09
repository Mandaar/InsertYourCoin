# Fichiers tiers vendorisés (`trading/static/`)

Dossier servi par la route `GET /static/<fichier>` (`trading/monitor.py` +
`trading/webui.py`). Vendorisé pour l'offline / AV-proof (aucune requête CDN
au runtime, cf. `docs/UI_UX_WEBAPP_SPEC.md` §7.3, Lot 0).

## chart.umd.min.js

- **Projet** : [Chart.js](https://www.chartjs.org/)
- **Version** : 4.4.1
- **Licence** : MIT
- **Source** : `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js`
- **Récupéré le** : 2026-07-09
- **Usage** : graphiques de `trading/dashboard.py` (courbe de capital, drawdown,
  comparaison de stratégies). Si ce fichier est absent, `dashboard.py` dégrade
  proprement (message "graphiques indisponibles hors-ligne" au lieu de casser).

Pour mettre à jour : retélécharger le même chemin avec la nouvelle version,
vérifier taille/absence de troncature, remplacer ce fichier, mettre à jour la
version ci-dessus.
