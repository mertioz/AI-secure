"""Interface Python d’AI Secure pour le programme hôte d’un agent."""

from .garde_ia import VERSION as __version__
from .garde_ia import GardeIA, charger_politique, creer_garde_notes, creer_garde_travail, traiter_flux
from .supervision import ContexteReseau, OutilSupervise, TravailEnCours
from .travail import PorteeTravail, portee_depuis_demande

__all__ = [
    "GardeIA", "charger_politique", "creer_garde_notes", "creer_garde_travail", "traiter_flux",
    "ContexteReseau", "OutilSupervise", "TravailEnCours", "PorteeTravail", "portee_depuis_demande",
    "__version__",
]
