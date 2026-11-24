import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import ai_secure


RACINE = Path(__file__).resolve().parent


class TestDemarrage(unittest.TestCase):
    def setUp(self):
        temporaire = tempfile.TemporaryDirectory(prefix="ai-secure-demarrage-")
        self.addCleanup(temporaire.cleanup)
        self.dossier = Path(temporaire.name).resolve()

    def lancer(self, *arguments, entree=None):
        return subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(RACINE / "garde_ia.py"), *arguments],
            cwd=self.dossier, input=entree, capture_output=True, encoding="utf-8", timeout=10,
        )

    def test_demo_par_defaut_hors_du_depot(self):
        resultat = self.lancer()
        self.assertEqual(resultat.returncode, 0, resultat.stderr)
        self.assertIn('"motif": "mission_suspendue"', resultat.stdout.splitlines()[-1])
        self.assertEqual(list(self.dossier.iterdir()), [])

    def test_init_copie_les_deux_modeles_et_preserve_une_personnalisation(self):
        resultat = self.lancer("--init")
        self.assertEqual(resultat.returncode, 0, resultat.stderr)
        destination = self.dossier / "mission.json"
        self.assertEqual(destination.read_bytes(), (RACINE / "mission.exemple.json").read_bytes())
        destination.write_bytes(b'{"actions":{},"termes_bloques":[]}')
        resultat = self.lancer("--init")
        self.assertEqual(resultat.returncode, 2)
        self.assertEqual(ai_secure.charger_politique(destination), {"actions": {}, "termes_bloques": []})

        resultat = self.lancer("--init", "travail.json", "--racine-travail", ".")
        self.assertEqual(resultat.returncode, 0, resultat.stderr)
        self.assertEqual((self.dossier / "travail.json").read_bytes(), (RACINE / "mission.travail.exemple.json").read_bytes())

    def test_hote_utilise_la_politique_integree(self):
        evenements = [
            {"type": "appel", "proposition": {"action": "ecrire_note", "parametres": {"note": note, "texte": "Essai"}}}
            for note in ("mission", "autre")
        ]
        resultat = self.lancer("--hote", entree="\n".join(map(json.dumps, evenements)))
        self.assertEqual(resultat.returncode, 0, resultat.stderr)
        decisions = [json.loads(ligne) for ligne in resultat.stdout.splitlines()]
        self.assertEqual(decisions, [{"statut": "autorisee", "resultat": "mission"}, {"statut": "bloquee", "motif": "hors_mission"}])

    def test_branchement_fichier_depuis_le_sdk(self):
        garde = ai_secure.creer_garde_travail(
            racine_travail=self.dossier, demande_utilisateur="Crée un programme dans ce fichier.", fichier_actif="calcul.py",
        )
        for nom, statut in (("calcul.py", "autorisee"), ("voisin.py", "bloquee")):
            decision = garde.executer({"action": "ecrire_fichier", "parametres": {"chemin": nom, "contenu": "print(2 + 2)\n"}})
            self.assertEqual(decision["statut"], statut)
        self.assertEqual((self.dossier / "calcul.py").read_text(encoding="utf-8"), "print(2 + 2)\n")
        self.assertFalse((self.dossier / "voisin.py").exists())

    def test_entree_du_paquet_protegee(self):
        garde = ai_secure.creer_garde_notes()
        entree = Path(ai_secure.__file__).with_name("__main__.py")
        resultat = garde.executer({"action": "supprimer_fichier", "parametres": {"chemin": str(entree)}})
        self.assertEqual(resultat["motif"], "sabotage_detecte")
        self.assertTrue(garde.attendre_arret())


if __name__ == "__main__":
    unittest.main()
