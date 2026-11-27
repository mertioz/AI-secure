"""Construit le MSIX x64 et vérifie les points d’entrée Windows depuis le paquet extrait."""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


STORE = Path(__file__).resolve().parent
RACINE = STORE.parent
CPYTHON = "3.14.10"
ARCHIVE = f"python-{CPYTHON}-embed-amd64.zip"
URL = f"https://www.python.org/ftp/python/{CPYTHON}/{ARCHIVE}"
SHA256 = "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159"
IDENTITE = "GreatInvention.AISecure"
EDITEUR = "CN=FA4E5D6A-6188-48A3-B369-2B6989768B29"


def empreinte(fichier):
    return hashlib.sha256(fichier.read_bytes()).hexdigest()


def sdk_windows():
    racine = Path(os.environ["ProgramFiles(x86)"]) / "Windows Kits" / "10" / "bin"
    candidats = [p for p in racine.glob("*/x64/makeappx.exe") if re.fullmatch(r"\d+(\.\d+){3}", p.parents[1].name)]
    if not candidats:
        raise RuntimeError("Installez le SDK Windows avec MakeAppx.exe.")
    return max(candidats, key=lambda p: tuple(map(int, p.parents[1].name.split("."))))


def runtime_windows(cache):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / ARCHIVE
    if not archive.is_file() or empreinte(archive) != SHA256:
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as flux:
            nouveau = Path(flux.name)
        try:
            with urllib.request.urlopen(URL, timeout=60) as source, nouveau.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            if empreinte(nouveau) != SHA256:
                raise RuntimeError("Le runtime diffère de l’empreinte publiée par Python.org.")
            os.replace(nouveau, archive)
        finally:
            nouveau.unlink(missing_ok=True)
    return archive


def compiler(csc, nom, dossier, version, *, fenetre=False, icone=None, references=()):
    exe = dossier / (nom + ".exe")
    options = [str(csc), "/nologo", "/optimize+", "/codepage:65001", "/platform:x64",
               "/target:" + ("winexe" if fenetre else "exe"), "/out:" + str(exe),
               "/win32manifest:" + str(STORE / "windows.manifest")]
    if icone:
        options.append("/win32icon:" + str(icone))
    options.extend("/reference:" + r for r in references)
    sources = {"AISecure": "Desktop.cs", "AISecureCli": "Cli.cs", "Artwork": "Artwork.cs"}
    subprocess.run([*options, str(version), str(STORE / sources[nom])], check=True)
    return exe


def image_size(image):
    data = image.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"PNG invalide : {image}")
    return struct.unpack(">II", data[16:24])


def executer_sdk(arguments):
    resultat = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if resultat.returncode:
        raise RuntimeError(resultat.stdout.decode("utf-8", errors="replace")[-5000:])


def verifier(extrait, images, version):
    cli = extrait / "AISecureCli.exe"
    def appel(options, entree=""):
        r = subprocess.run([str(cli), *options], input=entree, capture_output=True, encoding="utf-8", timeout=25, check=True)
        return r.stdout
    if appel(["--version"]).strip() != "Garde IA " + version:
        raise RuntimeError("Version du moteur incorrecte.")
    evenements = [
        {"type": "appel", "proposition": {"action": "ecrire_note", "parametres": {"note": cible, "texte": "Essai éphémère"}}}
        for cible in ("mission", "autre")
    ]
    evenements.append({"type": "fin"})
    decisions = [json.loads(ligne) for ligne in appel(["--hote"], "\n".join(map(json.dumps, evenements))).splitlines()]
    if [d["statut"] for d in decisions] != ["autorisee", "bloquee", "terminee"]:
        raise RuntimeError("Contrôle du périmètre en échec.")
    if "mission_suspendue" not in appel(["--demo"]).splitlines()[-1]:
        raise RuntimeError("Suspension du moteur en échec.")
    subprocess.run([str(extrait / "AISecure.exe"), "--captures-store", str(images)], check=True, timeout=45)
    for nom in ("atelier-lecture.png", "atelier-refus.png"):
        largeur, hauteur = image_size(images / nom)
        if largeur < 1366 or hauteur < 768:
            raise RuntimeError(f"Capture trop petite : {nom} ({largeur} × {hauteur}).")


def construire(sortie):
    if os.name != "nt":
        raise RuntimeError("Le build MSIX utilise le SDK Windows.")
    version = re.search(r'^VERSION = "([\d.]+)"', (RACINE / "ai_secure/garde_ia.py").read_text(encoding="utf-8"), re.M).group(1)
    majeur, mineur, correctif = map(int, version.split("."))
    version_store = f"{majeur + 1}.{mineur}.{correctif}.0"
    makeappx = sdk_windows()
    csc = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    sortie.mkdir(parents=True, exist_ok=True)
    archive = runtime_windows(sortie / "cache")
    livraison = sortie / f"v{version}"
    livraison.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ai-secure-msix-") as temporaire:
        travail = Path(temporaire).resolve()
        paquet = travail / "paquet"
        runtime = paquet / "runtime"
        runtime.mkdir(parents=True)
        with zipfile.ZipFile(archive) as zip_python:
            if any(not (runtime / membre).resolve().is_relative_to(runtime) for membre in zip_python.namelist()):
                raise RuntimeError("Chemin invalide dans le runtime.")
            zip_python.extractall(runtime)
        destination = runtime / "ai_secure"
        destination.mkdir()
        for source in (RACINE / "ai_secure").glob("*.py"):
            shutil.copy2(source, destination / source.name)
        for nom in ("mission.exemple.json", "mission.travail.exemple.json"):
            shutil.copy2(RACINE / nom, destination / nom)
        for nom in ("LICENSE", "PRIVACY.md"):
            shutil.copy2(RACINE / nom, paquet / nom)
        if not (runtime / "LICENSE.txt").is_file():
            raise RuntimeError("Licence du runtime Python introuvable.")
        manifeste = (STORE / "AppxManifest.xml").read_text(encoding="utf-8")
        if f'Name="{IDENTITE}"' not in manifeste or f'Publisher="{EDITEUR}"' not in manifeste:
            raise RuntimeError("Identité du produit inattendue.")
        manifeste, remplacements = re.subn(r'Version="\d+\.\d+\.\d+\.\d+" ProcessorArchitecture=',
                                           f'Version="{version_store}" ProcessorArchitecture=', manifeste, count=1)
        if remplacements != 1:
            raise RuntimeError("Version du manifeste introuvable.")
        (paquet / "AppxManifest.xml").write_text(manifeste, encoding="utf-8")
        metadonnees = travail / "Version.cs"
        metadonnees.write_text(
            'using System.Reflection;\n[assembly: AssemblyCompany("Mertioz")]\n[assembly: AssemblyProduct("AI Secure")]\n'
            f'[assembly: AssemblyVersion("{version_store}")]\n[assembly: AssemblyFileVersion("{version_store}")]\n'
            f'[assembly: AssemblyInformationalVersion("{version}")]\n', encoding="utf-8")
        dessiner = compiler(csc, "Artwork", travail, metadonnees, references=("System.Drawing.dll",))
        images = travail / "images"
        images.mkdir()
        subprocess.run([str(dessiner), str(paquet / "Assets"), str(images / "logo-store.png")], check=True)
        icone = paquet / "Assets/AISecure.ico"
        compiler(csc, "AISecureCli", paquet, metadonnees, icone=icone)
        compiler(csc, "AISecure", paquet, metadonnees, fenetre=True, icone=icone,
                 references=("System.Windows.Forms.dll", "System.Drawing.dll", "System.Web.Extensions.dll"))
        msix = travail / f"AI-Secure_{version_store}_x64.msix"
        executer_sdk([str(makeappx), "pack", "/d", str(paquet), "/p", str(msix), "/o"])
        extrait = travail / "verification"
        executer_sdk([str(makeappx), "unpack", "/p", str(msix), "/d", str(extrait), "/o"])
        verifier(extrait, images, version)
        shutil.copy2(msix, livraison / msix.name)
        for image in images.iterdir():
            shutil.copy2(image, livraison / image.name)
        print(json.dumps({"paquet": str(livraison / msix.name), "version": version_store,
                          "sha256": empreinte(msix), "captures": ["atelier-lecture.png", "atelier-refus.png"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sortie", type=Path, default=RACINE / "dist/store")
    construire(parser.parse_args().sortie.resolve())
