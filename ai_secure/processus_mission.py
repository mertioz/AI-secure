"""Arrêt des processus lancés par les outils de confiance de la mission."""

import json
import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from threading import Lock

from .supervision import OutilSupervise, TravailEnCours


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _LimitesDeBase(ctypes.Structure):
        _fields_ = [
            ("temps_processus", ctypes.c_longlong), ("temps_groupe", ctypes.c_longlong),
            ("drapeaux", wintypes.DWORD), ("memoire_min", ctypes.c_size_t), ("memoire_max", ctypes.c_size_t),
            ("processus_max", wintypes.DWORD), ("affinite", ctypes.c_size_t),
            ("priorite", wintypes.DWORD), ("ordonnancement", wintypes.DWORD),
        ]

    class _LimitesEtendues(ctypes.Structure):
        _fields_ = [
            ("base", _LimitesDeBase), ("compteurs_io", ctypes.c_ulonglong * 6),
            ("memoire_processus", ctypes.c_size_t), ("memoire_groupe", ctypes.c_size_t),
            ("pic_processus", ctypes.c_size_t), ("pic_groupe", ctypes.c_size_t),
        ]

    noyau = ctypes.WinDLL("kernel32", use_last_error=True)
    noyau.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    noyau.CreateJobObjectW.restype = wintypes.HANDLE
    noyau.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    noyau.SetInformationJobObject.restype = wintypes.BOOL
    noyau.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    noyau.OpenProcess.restype = wintypes.HANDLE
    noyau.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    noyau.AssignProcessToJobObject.restype = wintypes.BOOL
    noyau.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    noyau.TerminateJobObject.restype = wintypes.BOOL
    noyau.CloseHandle.argtypes = (wintypes.HANDLE,)
    noyau.CloseHandle.restype = wintypes.BOOL

    # Le programme de l’hôte attend son rattachement avant de lancer le travail.
    _AMORCE = (
        "import json, subprocess, sys\n"
        "arguments = json.loads(sys.stdin.readline())\n"
        "raise SystemExit(subprocess.call(arguments, stdin=subprocess.DEVNULL))\n"
    )

    def _lancer_windows(arguments, dossier):
        groupe = noyau.CreateJobObjectW(None, None)
        if not groupe:
            raise ctypes.WinError(ctypes.get_last_error())
        processus = None
        try:
            limites = _LimitesEtendues()
            limites.base.drapeaux = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not noyau.SetInformationJobObject(groupe, 9, ctypes.byref(limites), ctypes.sizeof(limites)):
                raise ctypes.WinError(ctypes.get_last_error())

            processus = subprocess.Popen(
                [sys.executable, "-I", "-S", "-c", _AMORCE], cwd=dossier, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            # PROCESS_SET_QUOTA | PROCESS_TERMINATE
            handle_processus = noyau.OpenProcess(0x0101, False, processus.pid)
            if not handle_processus:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not noyau.AssignProcessToJobObject(groupe, handle_processus):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                noyau.CloseHandle(handle_processus)
            with processus.stdin as flux:
                flux.write((json.dumps(arguments) + "\n").encode("ascii"))
            return processus, groupe
        except Exception:
            noyau.CloseHandle(groupe)
            if processus is not None:
                processus.kill()
                processus.wait()
                processus.stdin.close()
            raise


def processus_suivi(arguments: Sequence[str], *, dossier: Path | str | None = None) -> TravailEnCours:
    """Démarre des arguments définis par l’hôte dans un groupe contrôlé."""
    if isinstance(arguments, (str, bytes)) or not arguments or not all(isinstance(arg, str) for arg in arguments):
        raise ValueError("Une commande suivie exige une séquence d’arguments de l’hôte.")
    if os.name == "nt":
        processus, groupe = _lancer_windows(arguments, dossier)
    else:
        processus = subprocess.Popen(
            arguments, cwd=dossier, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        groupe = None
    verrou = Lock()

    def fermer_groupe():
        nonlocal groupe
        with verrou:
            if groupe is not None:
                noyau.CloseHandle(groupe)
                groupe = None

    def attendre():
        code = processus.wait()
        fermer_groupe()
        return {"code_retour": code}

    def arreter():
        with verrou:
            if groupe is not None:
                if not noyau.TerminateJobObject(groupe, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
            elif os.name != "nt" and processus.poll() is None:
                try:
                    os.killpg(processus.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            processus.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return False
        fermer_groupe()
        return True

    return TravailEnCours(attendre, arreter)


def commande_fixe(arguments: Sequence[str], *, dossier: Path | str | None = None) -> OutilSupervise:
    """Expose une commande prédéfinie à la garde, sans argument contrôlé par le modèle."""
    if isinstance(arguments, (str, bytes)):
        raise ValueError("Les arguments de commande sont une séquence de chaînes.")
    fixes = tuple(arguments)
    return OutilSupervise(lambda: processus_suivi(fixes, dossier=dossier))
