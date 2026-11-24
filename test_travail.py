import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from garde_ia import GardeIA, creer_garde_travail
from travail import PorteeTravail, TAILLE_CONTENU_MAX, portee_depuis_demande


def appel(action: str, **parametres: str) -> dict:
    return {"action": action, "parametres": parametres}


class TestTravail(unittest.TestCase):
    def setUp(self):
        temporaire = tempfile.TemporaryDirectory(prefix="ai-secure-travail-")
        self.addCleanup(temporaire.cleanup)
        self.espace = Path(temporaire.name).resolve()
        self.racine = self.espace / "travail"
        self.racine.mkdir()
        self.politique = json.loads(Path(__file__).with_name("mission.travail.exemple.json").read_text(encoding="utf-8"))

    def garde(self, demande: str, **selection):
        return creer_garde_travail(
            self.politique, racine_travail=self.racine, portee_travail=portee_depuis_demande(demande, **selection),
        )

    def test_creation_dans_ce_fichier_et_contenu_code(self):
        garde = self.garde("Créer moi un programme dans ce fichier.", fichier_actif="calcul.py")
        programme = "# Exemple de filtrage du terme exfiltrer.\n" * 150 + "def total(a, b):\n    return a + b\n"
        resultat = garde.executer(appel("ecrire_fichier", chemin="./calcul.py", contenu=programme))
        self.assertEqual(resultat["statut"], "autorisee")
        fichier = self.racine / "calcul.py"
        self.assertEqual(fichier.read_bytes(), programme.encode("utf-8"))
        ast.parse(programme)
        resultat = garde.executer(appel("ecrire_fichier", chemin="autre.py", contenu="Autre texte"))
        self.assertEqual(resultat["motif"], "hors_perimetre_travail")
        self.assertFalse((self.racine / "autre.py").exists())

    def test_reparation_d_un_projet_et_ajout_d_un_test(self):
        projet = self.racine / "programme"
        projet.mkdir()
        source = projet / "calcul.py"
        source.write_text("def aire(x, y):\n    return x + y\n", encoding="utf-8")
        garde = self.garde("Répare moi ce programme.", projet_actif=projet)
        self.assertEqual(garde.executer(appel("lire_fichier", chemin="programme/calcul.py"))["statut"], "autorisee")
        nouveau = "def aire(x, y):\n    return x * y\n"
        self.assertEqual(garde.executer(appel("ecrire_fichier", chemin="programme/calcul.py", contenu=nouveau))["statut"], "autorisee")
        self.assertEqual(garde.executer(appel("ecrire_fichier", chemin="programme/tests/test_calcul.py", contenu="def test_aire():\n    assert 2 * 3 == 6\n"))["statut"], "autorisee")
        self.assertEqual(source.read_bytes(), nouveau.encode("utf-8"))
        self.assertTrue((projet / "tests" / "test_calcul.py").is_file())
        refus = garde.executer(appel("ecrire_fichier", chemin="programme/../autre.py", contenu="Texte"))
        self.assertEqual(refus["motif"], "hors_perimetre_travail")

    def test_lecture_d_un_document_sans_ecriture(self):
        fichier = self.racine / "Document du projet.md"
        fichier.write_text("État initial", encoding="utf-8")
        garde = self.garde('Relis le document « Document du projet.md ».')
        self.assertEqual(garde.executer(appel("lire_fichier", chemin=fichier.name))["resultat"], "État initial")
        self.assertEqual(garde.executer(appel("ecrire_fichier", chemin=fichier.name, contenu="Autre"))["motif"], "hors_perimetre_travail")
        garde = self.garde('Améliore le document « Document du projet.md ».')
        self.assertEqual(garde.executer(appel("ecrire_fichier", chemin=fichier.name, contenu="Mis à jour"))["statut"], "autorisee")
        self.assertEqual(fichier.read_text(encoding="utf-8"), "Mis à jour")
        garde = self.garde("Mets à jour le fichier suivi.md.")
        self.assertEqual(garde.executer(appel("ecrire_fichier", chemin="suivi.md", contenu="Suivi"))["statut"], "autorisee")

    def test_absence_intention_directe_ou_selection_ambigue(self):
        cas = (
            ("Ne modifie pas ce fichier.", {"fichier_actif": "cible.py"}),
            ("Si je confirme, crée un programme dans ce fichier.", {"fichier_actif": "cible.py"}),
            ("Répare ce programme.", {}),
            ("Répare ce programme sans modifier le code source.", {"projet_actif": "."}),
            ("Crée ce fichier sans l’écraser.", {"fichier_actif": "cible.py"}),
            ("Modifie le fichier « a.py » et le fichier « b.py ».", {}),
        )
        for demande, selection in cas:
            with self.subTest(demande=demande):
                garde = self.garde(demande, **selection)
                resultat = garde.executer(appel("ecrire_fichier", chemin="cible.py", contenu="Écriture"))
                self.assertEqual(resultat["motif"], "perimetre_travail_absent")

    def test_hote_peut_autoriser_un_autre_travail(self):
        sauvegarder = Mock()
        garde = GardeIA(
            {"actions": {"sauver_tableau": {"destination": {"travail": "ecriture"}, "donnees_csv": {"donnees": "contenu"}}},
             "termes_bloques": []},
            {"sauver_tableau": sauvegarder}, racine_travail=self.racine,
            portee_travail=PorteeTravail(fichiers=("inventaire.csv",), ecriture=True),
        )
        demande = appel("sauver_tableau", destination="inventaire.csv", donnees_csv="article,quantite\nCarnet,4\n")
        self.assertEqual(garde.executer(demande)["statut"], "autorisee")
        sauvegarder.assert_called_once_with(destination=str(self.racine / "inventaire.csv"), donnees_csv=demande["parametres"]["donnees_csv"])

    def test_projet_refuse_les_fichiers_techniques_de_git(self):
        garde = self.garde("Répare ce projet.", projet_actif=".")
        resultat = garde.executer(appel("ecrire_fichier", chemin=".git/config", contenu="Fichier de test"))
        self.assertEqual(resultat["motif"], "hors_perimetre_travail")
        self.assertFalse((self.racine / ".git").exists())

    def test_projet_refuse_un_lien_fichier_partage(self):
        original = self.espace / "autre-dossier.txt"
        original.write_text("Document extérieur", encoding="utf-8")
        alias = self.racine / "copie.txt"
        try:
            os.link(original, alias)
        except OSError as erreur:
            self.skipTest(f"Liens physiques indisponibles : {erreur}")
        garde = self.garde("Répare ce projet.", projet_actif=".")
        refus = garde.executer(appel("ecrire_fichier", chemin="copie.txt", contenu="Modification"))
        self.assertEqual(refus["motif"], "hors_perimetre_travail")
        self.assertEqual(original.read_text(encoding="utf-8"), "Document extérieur")

    def test_ecriture_hors_racine_et_taille_invalide(self):
        garde = self.garde("Crée un programme dans ce fichier.", fichier_actif="script.py")
        refus = garde.executer(appel("ecrire_fichier", chemin=str(self.espace / "hors-racine.py"), contenu="Texte"))
        self.assertEqual(refus["motif"], "hors_perimetre_travail")
        refus = garde.executer(appel("ecrire_fichier", chemin="script.py", contenu="a" * (TAILLE_CONTENU_MAX + 1)))
        self.assertEqual(refus["motif"], "parametres_invalides")
        self.assertFalse((self.espace / "hors-racine.py").exists())
        self.assertFalse((self.racine / "script.py").exists())

    def test_perimetre_de_travail_ne_peut_pas_autoriser_le_sabotage(self):
        protege = self.racine / "superviseur.py"
        protege.write_text("Code protégé", encoding="utf-8")
        ecrire = Mock()
        garde = GardeIA(
            {"actions": {"mettre_a_jour": {"cible": {"travail": "ecriture"}, "source": {"donnees": "contenu"}}},
             "termes_bloques": []},
            {"mettre_a_jour": ecrire}, racine_travail=self.racine, chemins_proteges=(protege,),
            portee_travail=PorteeTravail(dossiers=(".",), ecriture=True),
        )
        resultat = garde.executer(appel("mettre_a_jour", cible="superviseur.py", source="Modification"))
        self.assertEqual(resultat["motif"], "sabotage_detecte")
        self.assertEqual(garde.etat["statut"], "suspendue")
        ecrire.assert_not_called()
        self.assertTrue(garde.attendre_arret())

    def test_regle_de_contenu_exige_une_cible_de_travail(self):
        with self.assertRaises(ValueError):
            GardeIA({"actions": {"outil": {"contenu": {"donnees": "contenu"}}}, "termes_bloques": []}, {"outil": Mock()})

    def test_module_de_perimetre_est_protege_dans_le_projet_actif(self):
        ecrire = Mock()
        garde = GardeIA(
            {"actions": {"ecrire_fichier": {"chemin": {"travail": "ecriture"}, "contenu": {"donnees": "contenu"}}},
             "termes_bloques": []},
            {"ecrire_fichier": ecrire}, racine_travail=Path(__file__).resolve().parent,
            portee_travail=PorteeTravail(dossiers=(".",), ecriture=True),
        )
        resultat = garde.executer(appel("ecrire_fichier", chemin="travail.py", contenu="Modification de contrôle."))
        self.assertEqual(resultat["motif"], "sabotage_detecte")
        self.assertTrue(garde.attendre_arret())
        ecrire.assert_not_called()

    def test_un_outil_decriture_ne_peut_pas_employer_une_cible_de_lecture(self):
        with self.assertRaises(ValueError):
            GardeIA(
                {"actions": {"write_file": {"path": {"travail": "lecture"}, "content": None}}, "termes_bloques": []},
                {"write_file": Mock()}, racine_travail=self.racine,
            )


if __name__ == "__main__":
    unittest.main()
