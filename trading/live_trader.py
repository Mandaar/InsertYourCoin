"""
Trading EN REEL sur Kraken.

⚠️  Argent reel. A n'utiliser qu'APRES validation en backtest puis en paper trading.

Garde-fous (definis dans config.py) :
  - dry_run = True par defaut : aucun ordre envoye tant que --execute n'est pas passe.
  - MAX_TRADE_VALUE_USD / MAX_POSITION_VALUE_USD : plafonds montant et exposition.
  - MIN_TRADE_INTERVAL_SEC : delai minimum entre deux ordres.
  - Stop-loss / take-profit / trailing stop verifies a chaque cycle.
  - Dimensionnement par volatilite optionnel, TOUJOURS borne par les plafonds ci-dessus.
  - Toutes les actions journalisees dans live_trades.log.

Persistance/reprise (Lot 8B, docs/design/LOT8B_LIVE_CONTENEUR_SPEC.md S1) :
  - `live_state.json` ne stocke QUE les ancres de risque que Kraken ne redonne pas
    (entry_price/peak/entry_ts/entry_cost/last_trade_ts). JAMAIS de cle, de solde
    ni de cash -- ca vient de Kraken en direct (_base_balance/_quote_balance).
  - Ecriture ATOMIQUE (fichier .tmp + os.replace).
  - `reconcile()` est appelee EXPLICITEMENT par l'appelant (superviseur/CLI), APRES
    la construction et AVANT `run()` -- jamais dans __init__ (elle fait un appel
    reseau et doit rester un pas delibere, pas un effet de bord du constructeur).
    L'EXCHANGE FAIT FOI (M2) : la table de verite a 4 cas est en S1.4 de la spec.
"""
import json
import os
import time
from pathlib import Path

import config
from .paper_trader import _Trader, now

LOG_FILE = Path("live_trades.log")
STATE_FILE = Path("live_state.json")  # defaut relatif ; en conteneur working_dir=/data (spec S1.2)


def _log(line: str):
    stamp = f"[{now()}] {line}"
    print(stamp)
    with LOG_FILE.open("a") as f:
        f.write(stamp + "\n")


class LiveTrader(_Trader):
    def __init__(self, exchange, strategy, symbol=None, timeframe=None,
                 stop_loss=None, take_profit=None, trailing_stop=None,
                 position_sizing=None, target_vol=None, vol_window=None,
                 max_fraction=None, dry_run=True, poll_seconds=None,
                 stats_file="live_stats.csv", state_file=None,
                 order_type=None, limit_timeout=None):
        super().__init__(exchange, strategy, symbol, timeframe, stop_loss,
                         take_profit, trailing_stop, position_sizing, target_vol,
                         vol_window, max_fraction, poll_seconds, stats_file,
                         log_file=LOG_FILE, order_type=order_type,
                         limit_timeout=limit_timeout)
        self.dry_run = dry_run
        # `state_file` resolu au call-time contre le module STATE_FILE (comme LOG_FILE
        # ci-dessus) pour rester monkeypatchable par les tests sans polluer le depot.
        self.state_file = Path(state_file) if state_file is not None else STATE_FILE
        self.entry_price = None
        self.peak = None  # plus haut atteint depuis l'entree, suivi EN MEMOIRE + persiste
        self.entry_ts = None
        self.entry_cost = None  # budget engage a l'entree (suivi pnl/duree par trade)
        self.last_trade_ts = 0.0
        mode = "DRY-RUN (aucun ordre envoye)" if dry_run else "REEL (ordres envoyes !)"
        _log(f"LiveTrader initialise en mode {mode}")

    # ------------------------------------------------------------------- #
    #  Persistance (Lot 8B S1.2/S1.3) -- AUCUNE cle, AUCUN solde, AUCUN cash. #
    # ------------------------------------------------------------------- #
    def _load_raw_state(self):
        """Lit l'etat persiste brut (dict) SANS muter self. None si absent/illisible
        (un fichier corrompu est traite comme un etat absent, jamais comme un crash --
        M9 : signale, pas masque)."""
        if not self.state_file.exists():
            return None
        try:
            return json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, OSError) as e:
            _log(f"ATTENTION : etat persiste illisible ({self.state_file}) : {e} -- "
                 "traite comme absent (reconciliation prudente).")
            return None

    def _save_state(self):
        """Ecriture ATOMIQUE (fichier .tmp + os.replace, L7/E2 -- le volume peut
        tronquer une ecriture longue). Schema fige (spec S1.2) : seulement les
        ancres de risque que Kraken ne redonne pas."""
        payload = {
            "version": 1,
            "mode": "dry" if self.dry_run else "reel",
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy": getattr(self.strategy, "name", str(self.strategy)),
            "invested": self.entry_price is not None,
            "entry_price": self.entry_price,
            "peak": self.peak,
            "entry_ts": self.entry_ts,
            "entry_cost": self.entry_cost,
            "last_trade_ts": self.last_trade_ts,
            "updated_ts": time.time(),
        }
        tmp_path = Path(str(self.state_file) + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2))
        os.replace(tmp_path, self.state_file)

    def reconcile(self):
        """
        Reconciliation de demarrage (spec S1.4) : a appeler APRES construction,
        AVANT run(). Lit l'etat persiste, interroge Kraken UNE fois (fetch_balance
        via _base_balance + fetch_price), applique la table de verite a 4 cas --
        L'EXCHANGE FAIT FOI, jamais l'etat persiste. Ne passe JAMAIS d'ordre (ni
        achat ni vente) : purement defensif. Persiste le resultat et le retourne.
        """
        price = self.exchange.fetch_price(self.symbol)
        base_amount = self._base_balance()  # 1 lecture reutilisee (meme critere que _is_invested)
        kraken_invested = base_amount * price > 1.0  # seuil IDENTIQUE a _is_invested (V12, pas de seuil parallele)
        raw = self._load_raw_state()
        state_invested = bool(raw) and raw.get("entry_price") is not None
        prior_last_trade_ts = (raw or {}).get("last_trade_ts") or 0.0
        # last_trade_ts SURVIT dans les 4 cas : sinon un restart contourne le
        # cooldown MIN_TRADE_INTERVAL_SEC (spec S1.2, danger nomme explicitement).
        self.last_trade_ts = prior_last_trade_ts

        if kraken_invested and state_invested:
            # REPRISE NORMALE : Kraken investi + etat investi -> restaurer depuis l'etat.
            self.entry_price = raw.get("entry_price")
            self.peak = raw.get("peak") if raw.get("peak") is not None else self.entry_price
            self.entry_ts = raw.get("entry_ts")
            self.entry_cost = raw.get("entry_cost")
            _log(f"RECONCILE : reprise normale (investi) -- entry={self.entry_price}, peak={self.peak}")
        elif kraken_invested and not state_invested:
            # DIVERGENCE -- ADOPTION DEFENSIVE : position orpheline (Kraken investi,
            # etat flat/absent) -> on ancre stop/trailing a "maintenant" (JAMAIS de
            # liquidation, JAMAIS de rachat -- une vente de protection seulement).
            self.entry_price = price
            self.peak = price
            self.entry_ts = time.time()
            self.entry_cost = base_amount * price
            _log("RECONCILE ATTENTION : position Kraken detectee SANS etat de risque "
                 f"connu -- ADOPTION DEFENSIVE : stop/trailing ancres au prix courant "
                 f"{price:.2f} (PnL affiche sera approximatif).")
        elif not kraken_invested and state_invested:
            # DIVERGENCE -- RETOUR A PLAT : position fermee pendant l'arret (vente
            # manuelle ou autre) -> on efface l'etat, on ne rachete JAMAIS sur du perime.
            self.entry_price = None
            self.peak = None
            self.entry_ts = None
            self.entry_cost = None
            _log("RECONCILE ATTENTION : etat persiste investi mais Kraken est FLAT -- "
                 "retour a plat (aucun rachat sur un etat perime).")
        else:
            # REPRISE NORMALE PLATE : rien a restaurer.
            self.entry_price = None
            self.peak = None
            self.entry_ts = None
            self.entry_cost = None
            _log("RECONCILE : reprise normale (flat) -- rien a restaurer.")

        self._save_state()
        return {"kraken_invested": kraken_invested, "state_invested": state_invested}

    def _base_balance(self):
        return self.exchange.fetch_balance().get(self.base, 0.0)

    def _quote_balance(self):
        return self.exchange.fetch_balance().get(self.quote, 0.0)

    def _is_invested(self, price):
        return self._base_balance() * price > 1.0  # >1$ d'actif = investi

    def _entry_price(self):
        return self.entry_price

    def _peak(self):
        return self.peak

    def _set_peak(self, value):
        if self.peak != value:
            self.peak = value
            self._save_state()

    def _cash(self):
        return self._quote_balance()

    def _units(self):
        return self._base_balance()

    # ------------------------------------------------------------------- #
    #  Execution des ordres (marche = taker, limite postOnly = maker)      #
    # ------------------------------------------------------------------- #
    @staticmethod
    def _filled_of(order) -> float:
        """Quantite REELLEMENT remplie lue sur l'ordre (0.0 si absente/illisible)."""
        try:
            return float((order or {}).get("filled") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _place_limit(self, side: str, amount: float, price: float) -> float:
        """
        Place un ordre LIMITE postOnly et attend un remplissage pendant un temps
        BORNE (`self.limit_timeout`, defaut config.LIMIT_ORDER_TIMEOUT_SEC = 60 s,
        toujours <= poll_seconds). Retourne la quantite REELLEMENT remplie.

        Politique de non-remplissage, explicite (un ordre maker peut ne JAMAIS
        etre rempli) :
          - rejet a l'envoi (postOnly : l'ordre aurait croise le carnet, donc
            aurait ete facture en TAKER) -> 0.0, on ne prend PAS la position et le
            cycle suivant re-decide avec un prix frais ;
          - delai ecoule sans remplissage complet -> ANNULATION, puis relecture de
            l'ordre pour connaitre le remplissage REEL (un remplissage PARTIEL a
            pu se produire avant l'annulation) ;
          - le retour fait foi pour la position : `filled`, jamais `amount`. Aucune
            position fantome ne peut donc etre inscrite dans l'etat.
        """
        placer = (self.exchange.create_limit_buy if side == "buy"
                  else self.exchange.create_limit_sell)
        try:
            order = placer(self.symbol, amount, price)
        except Exception as e:
            _log(f"Ordre LIMITE {side} refuse a l'envoi ({type(e).__name__}: {e}) -- "
                 "rien d'execute, le cycle suivant re-decidera.")
            return 0.0

        order_id = (order or {}).get("id")
        filled = self._filled_of(order)
        deadline = time.time() + self.limit_timeout
        # Boucle "au moins une relecture" : meme avec un delai nul on interroge
        # l'ordre UNE fois avant de conclure -- sinon on annulerait un ordre
        # peut-etre deja rempli (et on inscrirait une position fausse).
        while filled < amount:
            time.sleep(max(0.0, min(config.LIMIT_ORDER_POLL_SEC,
                                    deadline - time.time())))
            try:
                order = self.exchange.fetch_order(order_id, self.symbol)
            except Exception as e:
                _log(f"Lecture de l'ordre {order_id} impossible ({type(e).__name__}: {e}) "
                     "-- on tente l'annulation.")
                break
            filled = self._filled_of(order)
            if str((order or {}).get("status") or "").lower() in (
                    "closed", "canceled", "cancelled", "rejected", "expired"):
                break
            if time.time() >= deadline:
                break

        if filled < amount:
            # Delai ecoule (ou ordre deja termine partiellement) : on annule et on
            # RELIT le remplissage reel -- ne jamais supposer 0 apres annulation.
            try:
                self.exchange.cancel_order(order_id, self.symbol)
                final = self.exchange.fetch_order(order_id, self.symbol)
                filled = max(filled, self._filled_of(final))
            except Exception as e:
                _log(f"Annulation/relecture de l'ordre {order_id} en echec "
                     f"({type(e).__name__}: {e}) -- remplissage retenu : {filled:.8f}.")
            if filled <= 0:
                _log(f"Ordre LIMITE {side} NON REMPLI en {self.limit_timeout:.0f}s -> annule. "
                     "Aucune position prise ; re-decision au cycle suivant.")
            else:
                _log(f"Ordre LIMITE {side} PARTIELLEMENT rempli : {filled:.8f} / "
                     f"{amount:.8f} -> reste annule. La position suit le rempli REEL.")
        return filled

    def _cooldown_ok(self):
        if time.time() - self.last_trade_ts < config.MIN_TRADE_INTERVAL_SEC:
            _log("Ordre ignore : delai minimum entre trades non ecoule (garde-fou).")
            return False
        return True

    def _rebalance(self, desired, price, reason, fraction=1.0):
        invested = self._is_invested(price)

        if desired == 1 and not invested:                       # ACHAT
            if not self._cooldown_ok():
                return None
            if fraction <= 0:
                _log("Achat ignore : fraction de sizing nulle (volatilite trop elevee).")
                return None
            # Sizing par volatilite, puis plafonds (garde-fous) : le plus serre gagne.
            budget = min(self._quote_balance() * fraction, config.MAX_TRADE_VALUE_USD)
            room = config.MAX_POSITION_VALUE_USD - self._base_balance() * price
            budget = max(0.0, min(budget, room))
            if budget < 1.0:
                _log("Achat ignore : budget sous le plafond/minimum (garde-fou).")
                return None
            amount = budget / price
            if self.dry_run:
                _log(f"[DRY-RUN] ACHAT prevu : {amount:.5f} {self.base} (~{budget:.2f} {self.quote}) @ {price:.2f}")
            elif self.order_type == "limit":
                filled = self._place_limit("buy", amount, price)
                if filled <= 0:
                    return None          # aucun remplissage -> AUCUNE position inscrite
                amount = filled          # remplissage partiel : la position = le REMPLI
                budget = filled * price
                _log(f"ACHAT LIMITE EXECUTE : {amount:.5f} {self.base} @ {price:.2f} "
                     f"(~{budget:.2f} {self.quote})")
                self.last_trade_ts = time.time()
            else:
                order = self.exchange.create_market_buy(self.symbol, amount)
                _log(f"ACHAT EXECUTE : {amount:.5f} {self.base} @ ~{price:.2f} | id={order.get('id')}")
                self.last_trade_ts = time.time()
            self.entry_price = price
            self.peak = price
            self.entry_ts = time.time()
            self.entry_cost = budget
            self._save_state()
            return {"action": "buy", "pnl": 0.0, "fee_paid": budget * self.fee, "hold_secs": ""}

        elif desired == 0 and invested:                         # VENTE
            if not self._cooldown_ok():
                return None
            amount = self._base_balance()
            hold = time.time() - (self.entry_ts or time.time())
            tag = f" [{reason}]" if reason else ""
            sold = amount            # quantite REELLEMENT vendue (= amount hors limite)
            if self.dry_run:
                _log(f"[DRY-RUN] VENTE prevue{tag} : {amount:.5f} {self.base} @ {price:.2f}")
            elif self.order_type == "limit":
                sold = self._place_limit("sell", amount, price)
                if sold <= 0:
                    # DANGER PROPRE AU MAKER, dit explicitement : une sortie de
                    # risque (stop/trailing/objectif) qui ne trouve pas de
                    # contrepartie NE PROTEGE PAS. On garde les ancres de risque
                    # intactes et on re-essaiera au cycle suivant.
                    _log(f"ATTENTION : VENTE LIMITE{tag} NON REMPLIE -- la position "
                         "reste OUVERTE et non protegee ; nouvelle tentative au "
                         "cycle suivant (passer en --order-type market pour sortir "
                         "au marche).")
                    return None
                _log(f"VENTE LIMITE EXECUTEE{tag} : {sold:.5f} {self.base} @ {price:.2f}")
                self.last_trade_ts = time.time()
            else:
                order = self.exchange.create_market_sell(self.symbol, amount)
                _log(f"VENTE EXECUTEE{tag} : {amount:.5f} {self.base} @ ~{price:.2f} | id={order.get('id')}")
                self.last_trade_ts = time.time()
            # PnL APPROXIMATIF en live : on ignore les fills/slippage reels (inconnus
            # ici), on suppose une vente au prix observe, frais Kraken deduits. En
            # remplissage PARTIEL, le cout d'entree est impute AU PRORATA du vendu.
            part = (sold / amount) if amount else 1.0
            entry_cost = self.entry_cost or 0.0
            proceeds = sold * price
            fee_sell = proceeds * self.fee
            pnl = proceeds * (1 - self.fee) - entry_cost * part
            if part < 1.0:
                # Reste une position ouverte : on CONSERVE les ancres de risque
                # (entry_price/peak/entry_ts) pour que stop et trailing continuent
                # de la couvrir, et on ne garde que la part de cout non soldee.
                self.entry_cost = entry_cost * (1 - part)
                _log(f"Position PARTIELLEMENT soldee ({part*100:.0f}%) -- le reste "
                     "demeure ouvert, stop/trailing toujours actifs dessus.")
            else:
                self.entry_price = None
                self.peak = None
                self.entry_ts = None
                self.entry_cost = None
            self._save_state()
            return {"action": "sell", "pnl": pnl, "fee_paid": fee_sell,
                    "hold_secs": hold, "reason": reason}
        return None

    def _log_status(self, price):
        try:
            val = self._base_balance() * price
            _log(f"prix {price:.2f} | {self.base} ~{val:.2f} {self.quote} | cash {self._quote_balance():.2f} {self.quote}")
        except Exception as e:
            _log(f"Lecture du solde impossible : {e}")
