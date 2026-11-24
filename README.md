# Garde IA v0.1.1

Garde IA vérifie le raisonnement visible et les paramètres d’un appel avant de transmettre l’action à un outil autorisé pour la mission.

## Essayer la démo

Depuis ce dossier, avec Python 3.10 ou plus récent.

```powershell
python .\garde_ia.py --demo
```

La démo écrit et relit une note en mémoire. Elle refuse une tentative de neutraliser les contrôles, un plan qui désigne une autre cible et un appel sans raisonnement. Elle approuve ensuite une suppression simulée à la cible demandée par l’utilisateur.

## Vérifier le raisonnement

Chaque appel doit fournir un objet `raisonnement` avec trois champs.

- `texte` contient le raisonnement associé à l’appel que le modèle rend accessible, ou son résumé. Il accepte jusqu’à 16 384 caractères.
- `action` indique l’action annoncée dans le plan du modèle.
- `cibles` donne les valeurs annoncées pour les paramètres à valeurs imposées par la mission et, pour une suppression, pour `chemin`. Utilisez `{}` si l’appel comporte uniquement du texte libre.

La garde bloque un raisonnement manquant ou un plan incohérent avec l’appel. Elle cherche des formulations qui indiquent une tentative de désactiver la garde, d’ignorer ses règles ou de masquer une intention. Le champ `intention` reste accepté comme texte supplémentaire et passe par les mêmes contrôles de contenu.

Le programme peut analyser le raisonnement que son moteur lui transmet. Ce texte peut être incomplet ou inventé. Le filtre peut manquer certaines reformulations ou signaler une citation. La garde impose les permissions de la mission à l’appel réel dans tous les cas.

## Définir une mission

Dans `mission.exemple.json`, `actions` donne les outils autorisés et leurs paramètres obligatoires. Une liste impose des valeurs exactes. `null` accepte un texte libre de 4 096 caractères maximum, par exemple le corps d’un brouillon. Utilisez des valeurs exactes pour les identifiants de ressources. `termes_bloques` contient les mots et expressions à repérer. La recherche tient compte des mots entiers et ignore les différences d’accents, de casse et de ponctuation entre les mots.

Le mode `--mission` lit une proposition JSON UTF-8 par ligne, jusqu’à 128 Kio par ligne, et produit une décision JSON par ligne. La lecture et l’écriture partagent les notes de la session en cours.

```powershell
@'
{"action":"ecrire_note","parametres":{"note":"mission","texte":"Compte rendu termine."},"raisonnement":{"action":"ecrire_note","cibles":{"note":"mission"},"texte":"Mettre a jour la note."}}
{"action":"lire_note","parametres":{"note":"mission"},"raisonnement":{"action":"lire_note","cibles":{"note":"mission"},"texte":"Relire le compte rendu."}}
'@ | python .\garde_ia.py --mission .\mission.exemple.json
```

Une décision `bloquee` donne le motif du refus et, le cas échéant, les termes repérés. Une décision `autorisee` contient le résultat de l’outil. Le statut `erreur` indique qu’un outil a été appelé puis a échoué.

## Autoriser une suppression

Le programme hôte transmet la demande originale avec `demande_utilisateur` en Python ou `--demande` dans le terminal. Une demande directe au singulier, comme `Supprime le fichier « brouillons/ancien.txt »` ou `Peux-tu supprimer le dossier « brouillons/archives » ?`, autorise une seule exécution au chemin indiqué. Le type et le chemin proposés doivent correspondre. Les chemins sont relatifs au dossier de travail de l’outil. Les séparateurs `/` et `\` sont équivalents et la casse doit correspondre. Une demande négative, vague ou portant sur plusieurs éléments est refusée.

Dans la mission, les actions `supprimer_fichier` et `supprimer_dossier` prennent chacune un seul paramètre `chemin` de règle `null`. La valeur est contrôlée à partir de la demande originale. Les deux outils du terminal simulent la suppression et indiquent le chemin approuvé.

```powershell
@'
{"action":"supprimer_fichier","parametres":{"chemin":"brouillons/autre.txt"},"raisonnement":{"action":"supprimer_fichier","cibles":{"chemin":"brouillons/autre.txt"},"texte":"Supprimer le fichier selectionne."}}
{"action":"supprimer_fichier","parametres":{"chemin":"brouillons/ancien.txt"},"raisonnement":{"action":"supprimer_fichier","cibles":{"chemin":"brouillons/ancien.txt"},"texte":"Supprimer le fichier demande."}}
'@ | python .\garde_ia.py --mission .\mission.exemple.json --demande 'Supprime le fichier "brouillons/ancien.txt".'
```

## Brancher un agent

Le programme hôte construit `GardeIA(politique, outils, demande_utilisateur=demande_originale)` avec ses propres fonctions. Il associe à chaque appel le texte de raisonnement et le plan fournis par le modèle pour cet appel, puis soumet la proposition complète à `garde.executer(proposition)`. Il prend `demande_originale` dans le message de l’utilisateur et conserve l’accès aux outils réels. Pour filtrer les réponses visibles, il soumet leur texte à une action comme `repondre`, puis affiche le résultat autorisé.

Le modèle agit exclusivement par cette interface. Pour une suppression réelle, chaque fonction doit recevoir le chemin approuvé comme argument littéral et vérifier sur le système de fichiers le type de l’élément ainsi que la cible résolue dans la racine de travail. Les liens et les jonctions font partie de cette vérification. L’autorisation est consommée dès que la garde transmet l’appel à la fonction de suppression.

## Vérifier le blocage

```powershell
python -B -m unittest -v
```
