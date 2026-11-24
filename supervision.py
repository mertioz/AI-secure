"""Suivi des travaux d’une mission et rapport d’interruption."""

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread, Timer
from time import monotonic


@dataclass(frozen=True)
class ContexteReseau:
    """Le programme hôte fournit le besoin et l’état réel de la connexion."""

    internet_necessaire: bool
    est_en_ligne: Callable[[], bool]


@dataclass(frozen=True)
class TravailEnCours:
    """Un travail démarré par l’hôte, avec son arrêt et son résultat."""

    attendre: Callable[[], object]
    arreter: Callable[[], bool]


@dataclass(frozen=True)
class OutilSupervise:
    """La fonction de démarrage rend la main dès que le travail est suivi."""

    demarrer: Callable[..., TravailEnCours]


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Ordre:
    identifiant: int
    action: str
    parametres: dict[str, str]
    recu_le: str
    statut: str = "recu"
    motif: str | None = None
    programme_pour: str | None = None
    commence_le: str | None = None
    fini_le: str | None = None
    code_retour: int | None = None
    minuterie: Timer | None = None
    travail: TravailEnCours | None = None

    def finir(self, statut: str, motif: str | None = None) -> None:
        self.statut = statut
        self.motif = motif
        self.fini_le = maintenant()

    def rapport(self) -> dict[str, object]:
        return {
            "id": self.identifiant, "action": self.action, "parametres": self.parametres.copy(),
            "statut": self.statut, "motif": self.motif, "recu_le": self.recu_le,
            "programme_pour": self.programme_pour, "commence_le": self.commence_le, "fini_le": self.fini_le,
            "code_retour": self.code_retour,
        }


class SuiviMission:
    """Le verrou de la garde synchronise le journal avec l’admission des appels."""

    CIBLES = {
        "chemin", "path", "source", "destination", "src", "dst", "ancien_chemin", "nouveau_chemin",
        "note", "profil", "cible", "dossier", "old_path", "new_path",
    }

    def __init__(self, verrou, arreter_agent: Callable[[], bool] | None, rapport: Path | str | None):
        self.verrou = verrou
        self.arreter_agent = arreter_agent
        self.chemin_rapport = Path(rapport).resolve() if rapport is not None else None
        self.ordres: list[Ordre] = []
        self.etat_agent = "actif" if arreter_agent is not None else "non_raccorde"
        self.arret_acheve = Event()
        self.erreur_rapport = False

    def inscrire(self, proposition: object) -> Ordre:
        appel = proposition if isinstance(proposition, dict) else {}
        action = appel.get("action")
        parametres = appel.get("parametres")
        cibles = {
            cle: valeur[:512] for cle, valeur in parametres.items()
            if cle in self.CIBLES and isinstance(valeur, str)
        } if isinstance(parametres, dict) else {}
        ordre = Ordre(len(self.ordres) + 1, action[:128] if isinstance(action, str) else "inconnue", cibles, maintenant())
        self.ordres.append(ordre)
        return ordre

    def annuler_programmation(self, motif: str) -> None:
        for ordre in self.ordres:
            if ordre.statut == "programmee":
                if ordre.minuterie is not None:
                    ordre.minuterie.cancel()
                ordre.finir("annulee", motif)

    def rapport(self, etat: dict[str, object]) -> dict[str, object]:
        return {
            "mission": etat.copy(), "agent": self.etat_agent,
            "rapport_enregistre": self.chemin_rapport is not None and self.arret_acheve.is_set() and not self.erreur_rapport,
            "ordres": [ordre.rapport() for ordre in self.ordres],
        }

    def interrompre(self, etat: dict[str, object]) -> None:
        """Annule les départs et demande l’arrêt des travaux en parallèle."""
        self.annuler_programmation("arret_mission")
        demandes = []
        if self.arreter_agent is not None:
            self.etat_agent = "arret_demande"
            demandes.append((None, self.arreter_agent))
        for ordre in self.ordres:
            if ordre.statut == "en_cours":
                if ordre.travail is None:
                    ordre.statut = "arret_non_confirme"
                    ordre.motif = "outil_sans_arret_raccorde"
                else:
                    ordre.statut = "arret_demande"
                    demandes.append((ordre, ordre.travail.arreter))
        Thread(target=self._achever_arret, args=(etat.copy(), demandes), daemon=True).start()

    def _achever_arret(self, etat: dict[str, object], demandes: list) -> None:
        resultats = Queue()

        def annuler(index, arreter):
            try:
                confirmation = arreter() is True
            except Exception:
                confirmation = False
            resultats.put((index, confirmation))

        confirmations = {}
        try:
            for index, (_, arreter) in enumerate(demandes):
                Thread(target=annuler, args=(index, arreter), daemon=True).start()
            limite = monotonic() + 3
            while len(confirmations) < len(demandes):
                try:
                    index, resultat = resultats.get(timeout=max(0, limite - monotonic()))
                except Empty:
                    break
                confirmations[index] = resultat
            with self.verrou:
                for index, (ordre, _) in enumerate(demandes):
                    confirme = confirmations.get(index, False)
                    if ordre is None:
                        self.etat_agent = "interrompu" if confirme else "arret_non_confirme"
                    elif ordre.statut == "arret_demande":
                        if confirme:
                            ordre.finir("interrompue", "arret_mission")
                        else:
                            ordre.statut = "arret_non_confirme"
                            ordre.motif = "arret_non_confirme"
                rapport = self.rapport(etat)
            if self.chemin_rapport is not None:
                rapport["rapport_enregistre"] = True
                self._ecrire_rapport(rapport)
        except OSError:
            with self.verrou:
                self.erreur_rapport = True
        finally:
            self.arret_acheve.set()

    def _ecrire_rapport(self, rapport: dict[str, object]) -> None:
        chemin = self.chemin_rapport
        chemin.parent.mkdir(parents=True, exist_ok=True)
        temporaire = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=chemin.parent, delete=False) as flux:
                temporaire = Path(flux.name)
                json.dump(rapport, flux, ensure_ascii=False, indent=2)
                flux.write("\n")
            os.replace(temporaire, chemin)
        finally:
            if temporaire is not None:
                temporaire.unlink(missing_ok=True)
