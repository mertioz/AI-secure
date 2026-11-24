import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import Mock

from garde_ia import GardeIA
from processus_mission import commande_fixe, processus_suivi
from supervision import ContexteReseau


def proposition(action, **parametres):
    return {"action": action, "parametres": parametres}


class TestSupervision(unittest.TestCase):
    def test_une_commande_terminal_exige_un_arret_et_des_arguments_approuves(self):
        with self.assertRaises(ValueError):
            GardeIA(
                {"actions": {"executer_commande": {"commande": None}}, "termes_bloques": []},
                {"executer_commande": Mock()},
            )

    def test_connexion_necessaire_avec_profil_approuve(self):
        etat = {"en_ligne": False}

        def connecter(profil):
            etat["en_ligne"] = True
            return profil

        reseau = ContexteReseau(True, lambda: etat["en_ligne"])
        wifi = Mock(side_effect=connecter)
        garde = GardeIA(
            {"actions": {"connecter_wifi": {"profil": ["Bureau"]}}, "termes_bloques": []},
            {"connecter_wifi": wifi}, contexte_reseau=reseau,
        )
        self.assertEqual(garde.observer(
            "La mission se déroule en ligne. La connexion est coupée. Je vais reconnecter le Wi-Fi approuvé.",
            canal="raisonnement",
        )["statut"], "active")
        self.assertEqual(garde.executer(proposition("connecter_wifi", profil="Inconnu"))["motif"], "hors_mission")
        self.assertEqual(garde.executer(proposition("connecter_wifi", profil="Bureau"))["statut"], "autorisee")
        self.assertEqual(garde.executer(proposition("connecter_wifi", profil="Bureau"))["motif"], "connexion_deja_active")
        wifi.assert_called_once_with(profil="Bureau")
        self.assertEqual(garde.etat["statut"], "active")

    def test_autre_precondition_fournie_par_hote(self):
        deja_ouvert = Event()
        ouvrir = Mock()
        garde = GardeIA(
            {"actions": {"ouvrir_application": {"cible": ["lecteur"]}}, "termes_bloques": []},
            {"ouvrir_application": ouvrir},
            conditions={"ouvrir_application": lambda parametres: parametres["cible"] == "lecteur" and not deja_ouvert.is_set()},
        )
        self.assertEqual(garde.executer(proposition("ouvrir_application", cible="lecteur"))["statut"], "autorisee")
        deja_ouvert.set()
        self.assertEqual(garde.executer(proposition("ouvrir_application", cible="lecteur"))["motif"], "condition_mission_non_remplie")
        ouvrir.assert_called_once_with(cible="lecteur")

    def test_ordre_programme_garde_les_parametres_recus(self):
        execute = Event()
        ecrire = Mock(side_effect=lambda note: execute.set())
        garde = GardeIA(
            {"actions": {"ecrire_note": {"note": ["mission"]}}, "termes_bloques": []},
            {"ecrire_note": ecrire},
        )
        demande = proposition("ecrire_note", note="mission")
        resultat = garde.planifier(demande, dans=0.15)
        demande["parametres"]["note"] = "autre"
        self.assertEqual(resultat["statut"], "programmee")
        self.assertTrue(execute.wait(2))
        ecrire.assert_called_once_with(note="mission")

    def test_connexion_sans_besoin_ou_etat_fiable(self):
        for contexte, motif in (
            (ContexteReseau(False, lambda: False), "connexion_hors_mission"),
            (ContexteReseau(True, lambda: None), "etat_reseau_indisponible"),
        ):
            wifi = Mock()
            garde = GardeIA(
                {"actions": {"connecter_wifi": {"profil": ["Bureau"]}}, "termes_bloques": []},
                {"connecter_wifi": wifi}, contexte_reseau=contexte,
            )
            self.assertEqual(garde.executer(proposition("connecter_wifi", profil="Bureau"))["motif"], motif)
            wifi.assert_not_called()

    def test_reconnexion_concurrente_refusee_pendant_le_retablissement(self):
        demarree = Event()
        terminer = Event()

        def connecter(profil):
            demarree.set()
            terminer.wait(3)
            return profil

        garde = GardeIA(
            {"actions": {"connecter_wifi": {"profil": ["Bureau"]}}, "termes_bloques": []},
            {"connecter_wifi": connecter}, contexte_reseau=ContexteReseau(True, lambda: False),
        )
        demande = proposition("connecter_wifi", profil="Bureau")
        with ThreadPoolExecutor(max_workers=1) as travailleur:
            premiere = travailleur.submit(garde.executer, demande)
            try:
                self.assertTrue(demarree.wait(2))
                self.assertEqual(garde.executer(demande)["motif"], "connexion_deja_en_cours")
            finally:
                terminer.set()
            self.assertEqual(premiere.result(timeout=2)["statut"], "autorisee")

    def test_lecture_autorisee_et_mutation_protegee(self):
        chemin = Path(__file__).with_name("garde_ia.py").resolve()
        lire = Mock(return_value="documentation")
        modifier = Mock()
        garde = GardeIA(
            {"actions": {
                "lire_fichier": {"chemin": [str(chemin), "rapport-exfiltration.txt"]},
                "write_file": {"path": [str(chemin)], "content": None},
            }, "termes_bloques": ["exfiltration"]},
            {"lire_fichier": lire, "write_file": modifier},
        )
        self.assertEqual(garde.executer(proposition("lire_fichier", chemin=str(chemin)))["statut"], "autorisee")
        self.assertEqual(garde.executer(proposition("lire_fichier", chemin="rapport-exfiltration.txt"))["statut"], "autorisee")
        self.assertEqual(
            garde.executer(proposition("write_file", path=str(chemin), content="Texte de test."))["motif"],
            "sabotage_detecte",
        )
        modifier.assert_not_called()
        self.assertEqual(garde.etat["statut"], "suspendue")

    def test_ordre_programme_reevalue_le_reseau_au_depart(self):
        disponible = Event()
        connecte = Event()
        garde = GardeIA(
            {"actions": {"connecter_wifi": {"profil": ["Bureau"]}}, "termes_bloques": []},
            {"connecter_wifi": lambda profil: connecte.set()},
            contexte_reseau=ContexteReseau(True, disponible.is_set),
        )
        ordre = garde.planifier(proposition("connecter_wifi", profil="Bureau"), dans=0.1)
        disponible.set()
        limite = monotonic() + 2
        while garde.rapport()["ordres"][0]["statut"] == "programmee" and monotonic() < limite:
            sleep(0.01)
        self.assertEqual(ordre["statut"], "programmee")
        self.assertEqual(garde.rapport()["ordres"][0]["motif"], "connexion_deja_active")
        self.assertFalse(connecte.is_set())

    def test_arret_reel_agent_descendant_et_tache_programmee(self):
        with tempfile.TemporaryDirectory(prefix="ai-secure-arret-") as temporaire:
            dossier = Path(temporaire).resolve()
            rapport = dossier / "rapport.json"
            pret = dossier / "enfant-pret"
            apres = dossier / "enfant-apres"
            script_enfant = (
                "from pathlib import Path; import sys, time; "
                "Path(sys.argv[1]).touch(); time.sleep(2); Path(sys.argv[2]).touch()"
            )
            script_parent = (
                "import subprocess, sys; "
                "raise SystemExit(subprocess.call([sys.executable, '-I', '-S', '-c', *sys.argv[1:]]))"
            )
            agent = processus_suivi((sys.executable, "-I", "-S", "-c", "import time; time.sleep(15)"))
            commande = commande_fixe((sys.executable, "-I", "-S", "-c", script_parent, script_enfant, str(pret), str(apres)))
            programmee = Mock()
            suppression = Mock()
            garde = GardeIA(
                {"actions": {
                    "commandee": {}, "future": {}, "lire_note": {"note": ["mission"]},
                    "supprimer_fichier": {"chemin": None},
                }, "termes_bloques": []},
                {"commandee": commande, "future": programmee, "lire_note": lambda note: note, "supprimer_fichier": suppression},
                demande_utilisateur="Supprime le fichier garde_ia.py", rapport=rapport, arreter_agent=agent.arreter,
                racine_travail=Path(__file__).resolve().parent,
            )
            try:
                garde.executer(proposition("lire_note", note="mission"))
                with ThreadPoolExecutor(max_workers=1) as travailleur:
                    active = travailleur.submit(garde.executer, proposition("commandee"))
                    limite = monotonic() + 4
                    while not pret.exists() and monotonic() < limite:
                        sleep(0.02)
                    self.assertTrue(pret.exists(), "Le sous-processus de test n’a pas démarré.")
                    futur = garde.planifier(proposition("future"), dans=0.5)
                    encore = garde.planifier(proposition("future"), dans=30)
                    tentative = garde.executer(proposition("supprimer_fichier", chemin="garde_ia.py"))
                    self.assertEqual(tentative["motif"], "sabotage_detecte")
                    self.assertEqual(garde.executer(proposition("future"))["motif"], "mission_suspendue")
                    self.assertTrue(garde.attendre_arret(5))
                    self.assertEqual(active.result(timeout=3)["motif"], "mission_suspendue")
                sleep(2)
                self.assertFalse(apres.exists(), "Le sous-processus a continué après l’arrêt.")
                programmee.assert_not_called()
                suppression.assert_not_called()
                contenu = json.loads(rapport.read_text(encoding="utf-8"))
                self.assertEqual(contenu["agent"], "interrompu")
                ordres = {ordre["id"]: ordre for ordre in contenu["ordres"]}
                self.assertEqual(ordres[1]["statut"], "executee")
                self.assertEqual(ordres[2]["statut"], "interrompue")
                for identifiant in (futur["id"], encore["id"]):
                    self.assertEqual(ordres[identifiant]["statut"], "annulee")
                    self.assertIsNotNone(ordres[identifiant]["programme_pour"])
                self.assertEqual(ordres[5]["motif"], "sabotage_detecte")
            finally:
                garde.terminer()
                agent.arreter()


if __name__ == "__main__":
    unittest.main()
