"""Périmètre de fichiers choisi par l’utilisateur pour une mission."""

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AccesTravail(Enum):
    LECTURE = "lecture"
    ECRITURE = "ecriture"


class DonneesOutil(Enum):
    CONTENU = "contenu"


TAILLE_CONTENU_MAX = 64 * 1_024
NOMS_RESERVES_WINDOWS = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])", re.IGNORECASE)
DEBUT_TRAVAIL = re.compile(
    r"\s*(?:(?:peux-tu|pourrais-tu|merci de|je veux que tu|please|can you|could you)\s+)?"
    r"(?:(?P<edition>cr[ée](?:e|er|ez|es)|[ée]cri(?:s|re|vez)|r[ée]par(?:e|er|ez|es)|"
    r"corrig(?:e|er|ez|es)|modifi(?:e|er|ez|es)|am[ée]lior(?:e|er|ez|es)|"
    r"optimis(?:e|er|ez|es)|ajout(?:e|er|ez|es)|impl[ée]ment(?:e|er|ez|es)|"
    r"(?:mets|mettez|mettre) [àa] jour|create|write|fix|repair|edit|update|improve|refactor|implement|add)"
    r"|(?P<lecture>lis|lire|relis|relire|analys(?:e|er|ez)|inspect(?:e|er|ez)?|examin(?:e|er|ez)|"
    r"diagnostiqu(?:e|er|ez)|read|review|examine|diagnose))\b",
    re.IGNORECASE,
)
NATURE_CIBLE = r"fichier|programme|document|script|dossier|projet|tableur|file|program|folder|directory|project|spreadsheet"
CIBLE_NOMMEE = re.compile(
    rf"\b({NATURE_CIBLE})\s+" r"(?:«\s*([^»\r\n]+?)\s*»|\"([^\"\r\n]+)\"|`([^`\r\n]+)`|'([^'\r\n]+)')",
    re.IGNORECASE,
)
REFERENCE_ACTIVE = re.compile(
    rf"\b(?:(?:ce|cet|cette|this)\s+({NATURE_CIBLE})|(?:le|the)\s+({NATURE_CIBLE})\s+(?:actif|s[ée]lectionn[ée]|selected))\b",
    re.IGNORECASE,
)
CIBLE_SIMPLE = re.compile(
    rf"\s*(?:-?moi\s+|me\s+)?(?:(?:le|la|the)\s+)?(?:(?P<nature>{NATURE_CIBLE})\s+)?"
    r"(?P<chemin>[^\s<>!?`\"'«»]+\.[\w-]+)\s*[.!?]?\s*",
    re.IGNORECASE,
)
RESTRICTION_EDITION = re.compile(
    r"\b(?:sauf|except|uniquement si|seulement si|only if|avant confirmation|"
    r"sans (?:y |l['’])?(?:modifier|[ée]crire|toucher|changer|supprimer|[ée]craser|effacer|remplacer)|ne (?:le |la |les |rien )?"
    r"(?:modifie|change|touche|supprime|fais) pas|do not (?:write|edit|change|modify|delete))\b",
    re.IGNORECASE,
)
NOMS_DOSSIER = {"dossier", "projet", "folder", "directory", "project"}
NOMS_PROGRAMME = {"programme", "program"}
DOSSIERS_TECHNIQUES = {".git", ".hg", ".svn"}


def _chemin_travail(racine: Path, valeur: str | Path) -> Path | None:
    if not isinstance(valeur, (str, Path)):
        return None
    texte = os.fspath(valeur)
    if not texte or len(texte) > 4_096 or "\0" in texte or texte.startswith(("\\\\", "//")):
        return None

    chemin = Path(texte)
    if chemin.drive and not chemin.is_absolute():
        return None
    absolu = Path(os.path.normpath(racine / chemin))
    if not absolu.is_relative_to(racine):
        return None

    courant = racine
    for morceau in absolu.relative_to(racine).parts:
        if morceau.casefold() in DOSSIERS_TECHNIQUES:
            return None
        if os.name == "nt":
            if morceau.endswith((".", " ")) or any(ord(c) < 32 or c in '<>:"|?*' for c in morceau):
                return None
            if NOMS_RESERVES_WINDOWS.fullmatch(morceau.partition(".")[0].rstrip()):
                return None
        courant /= morceau
        try:
            metadonnees = courant.lstat()
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return None
        if stat.S_ISLNK(metadonnees.st_mode) or getattr(metadonnees, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return None
        if not stat.S_ISDIR(metadonnees.st_mode) and (courant != absolu or not stat.S_ISREG(metadonnees.st_mode)):
            return None
    return absolu


@dataclass(frozen=True)
class PorteeTravail:
    """Cibles approuvées par l’hôte et droit de les modifier pendant la mission."""

    fichiers: tuple[str | Path, ...] = ()
    dossiers: tuple[str | Path, ...] = ()
    ecriture: bool = False

    def ancrer(self, racine: Path) -> "PorteeTravail":
        fichiers = tuple(_chemin_travail(racine, cible) for cible in self.fichiers)
        dossiers = tuple(_chemin_travail(racine, cible) for cible in self.dossiers)
        if any(cible is None or cible.is_dir() for cible in fichiers):
            raise ValueError("Le fichier sélectionné doit appartenir à l’espace de travail.")
        if any(cible is None or (cible.exists() and not cible.is_dir()) for cible in dossiers):
            raise ValueError("Le dossier sélectionné doit appartenir à l’espace de travail.")
        return PorteeTravail(fichiers, dossiers, ecriture=self.ecriture is True)

    def chemin_autorise(self, racine: Path, valeur: str, acces: AccesTravail) -> Path | None:
        if acces is AccesTravail.ECRITURE and not self.ecriture:
            return None
        cible = _chemin_travail(racine, valeur)
        if cible is None:
            return None
        if acces is AccesTravail.ECRITURE:
            try:
                metadonnees = cible.lstat()
            except FileNotFoundError:
                pass
            except OSError:
                return None
            else:
                if stat.S_ISREG(metadonnees.st_mode) and metadonnees.st_nlink > 1:
                    return None
        if cible in self.fichiers or any(cible.is_relative_to(dossier) for dossier in self.dossiers):
            return cible
        return None


def portee_depuis_demande(
    demande: str | None, *, fichier_actif: str | Path | None = None, projet_actif: str | Path | None = None,
) -> PorteeTravail | None:
    """Reconnaît une demande directe et une cible explicite ou sélectionnée par l’hôte."""
    if not isinstance(demande, str) or len(demande) > 4_096:
        return None
    debut = DEBUT_TRAVAIL.match(demande)
    if debut is None:
        return None
    ecriture = debut.group("edition") is not None
    if ecriture and RESTRICTION_EDITION.search(demande):
        return None

    suite = demande[debut.end():]
    nommees = list(CIBLE_NOMMEE.finditer(suite))
    actives = list(REFERENCE_ACTIVE.finditer(suite))
    if not nommees and not actives:
        simple = CIBLE_SIMPLE.fullmatch(suite)
        if simple is None:
            return None
        if (simple.group("nature") or "").casefold() in NOMS_DOSSIER:
            return PorteeTravail(dossiers=(simple.group("chemin"),), ecriture=ecriture)
        return PorteeTravail(fichiers=(simple.group("chemin"),), ecriture=ecriture)
    if len(nommees) + len(actives) != 1:
        return None
    if nommees:
        nature, *formes = nommees[0].groups()
        cible = next(forme for forme in formes if forme is not None)
        dossier = nature.casefold() in NOMS_DOSSIER
    else:
        nature = next(groupe for groupe in actives[0].groups() if groupe is not None).casefold()
        if nature in NOMS_PROGRAMME and fichier_actif is not None and projet_actif is not None:
            return None
        dossier = nature in NOMS_DOSSIER or (nature in NOMS_PROGRAMME and fichier_actif is None)
        cible = projet_actif if dossier else fichier_actif
        if cible is None:
            return None

    if dossier:
        return PorteeTravail(dossiers=(cible,), ecriture=ecriture)
    return PorteeTravail(fichiers=(cible,), ecriture=ecriture)


def lire_fichier(chemin: str) -> str:
    with Path(chemin).open(encoding="utf-8", newline="") as flux:
        contenu = flux.read(TAILLE_CONTENU_MAX + 1)
    if len(contenu) > TAILLE_CONTENU_MAX:
        raise ValueError("Le fichier dépasse la taille de lecture de cet outil.")
    return contenu


def ecrire_fichier(chemin: str, contenu: str) -> dict[str, object]:
    """Remplace le fichier approuvé une fois que l’écriture du contenu est terminée."""
    fichier = Path(chemin)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(fichier.stat().st_mode) if fichier.exists() else None
    temporaire = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=fichier.parent, delete=False) as flux:
            temporaire = Path(flux.name)
            flux.write(contenu)
        if mode is not None and os.name != "nt":
            temporaire.chmod(mode)
        os.replace(temporaire, fichier)
    finally:
        if temporaire is not None:
            temporaire.unlink(missing_ok=True)
    return {"chemin": str(fichier), "caracteres": len(contenu)}
