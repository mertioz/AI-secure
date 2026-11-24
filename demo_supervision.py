"""Exerce la décision Wi-Fi et l’arrêt d’urgence sur des travaux de test."""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from garde_ia import GardeIA
from processus_mission import processus_suivi
from supervision import ContexteReseau, OutilSupervise


def appel(action: str, **parametres: str) -> dict:
    return {"action": action, "parametres": parametres}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rapport", type=Path, default=Path("banc-resultats") / "supervision" / "rapport.json")
    options = parser.parse_args()
    trace = options.rapport.resolve()
    programme = Path(__file__).resolve().parent / "garde_ia.py"
    en_ligne = False
    demarre = Event()
    programme_execute = Event()
    attente = (sys.executable, "-I", "-S", "-c", "import time; time.sleep(12)")
    agent_de_test = processus_suivi(attente)

    def connecter(profil: str) -> dict:
        nonlocal en_ligne
        en_ligne = True
        return {"profil": profil, "simulee": True}

    def lancer_verification():
        travail = processus_suivi(attente)
        demarre.set()
        return travail

    garde = GardeIA(
        {"actions": {
            "connecter_wifi": {"profil": ["Profil-Test"]}, "verifier": {}, "publier": {},
        }, "termes_bloques": []},
        {"connecter_wifi": connecter, "verifier": OutilSupervise(lancer_verification), "publier": programme_execute.set},
        contexte_reseau=ContexteReseau(True, lambda: en_ligne), arreter_agent=agent_de_test.arreter,
        rapport=trace,
    )
    try:
        connexion = garde.executer(appel("connecter_wifi", profil="Profil-Test"))
        if connexion["statut"] != "autorisee" or not en_ligne:
            raise RuntimeError("La reconnexion nécessaire a été refusée.")
        with ThreadPoolExecutor(max_workers=1) as travailleur:
            verification = travailleur.submit(garde.executer, appel("verifier"))
            if not demarre.wait(4):
                raise RuntimeError("Le processus de test a échoué au démarrage.")
            publication = garde.planifier(appel("publier"), dans=1.5)
            if publication["statut"] != "programmee":
                raise RuntimeError("La commande de test a échoué à la programmation.")
            resultat = garde.executer(appel("supprimer_fichier", chemin=str(programme)))
            if resultat.get("motif") != "sabotage_detecte" or not garde.attendre_arret(5):
                raise RuntimeError("L’arrêt d’urgence a échoué.")
            verification.result(timeout=3)
        rapport = json.loads(trace.read_text(encoding="utf-8"))
        etats = {ordre["action"]: ordre["statut"] for ordre in rapport["ordres"]}
        attendus = {
            "connecter_wifi": "executee", "verifier": "interrompue",
            "publier": "annulee", "supprimer_fichier": "refusee",
        }
        if etats != attendus or rapport["agent"] != "interrompu" or programme_execute.wait(1.5):
            raise RuntimeError("Le rapport indique un arrêt incomplet.")
        if not programme.is_file():
            raise RuntimeError("Le code de la garde a été affecté.")
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps({"rapport": str(trace), "agent": rapport["agent"], "ordres": etats}, ensure_ascii=False, indent=2))
    finally:
        garde.terminer()
        agent_de_test.arreter()


if __name__ == "__main__":
    main()
