# Présentation pour le portfolio

Texte de la carte du projet sur mon portfolio (le README reste en anglais car c'est un outil installable).

## Version courte (carte)

**pbip-generator** : un outil Python qui transforme un dossier de fichiers CSV ou Excel en projet Power BI
complet (modèle en étoile, mesures DAX, pages de rapport) en moins d'une seconde. Sur les prix officiels
des carburants en Île-de-France (70 771 prix, 884 stations), il génère 4 tables, 11 mesures et 3 pages
de rapport, là où je compte environ 3 heures de travail à la main.

## Version longue (page projet)

Construire un modèle Power BI propre à partir de fichiers Excel, c'est toujours les mêmes étapes :
typer les colonnes, créer la table calendrier, relier les tables, écrire les mesures, placer les
visuels. J'ai donc écrit un outil qui fait tout ça à partir des données, au format PBIP (du texte, donc
versionnable dans git comme du code).

Le point qui le distingue des outils existants, c'est la séparation des rôles. Claude, via un serveur
MCP, décide du contenu du rapport : la question métier, les mesures, les pages. Il le fait dans une spec
typée, et le code vérifie chaque nom contre les données avant d'écrire le moindre fichier. Le modèle de
langage ne touche jamais aux fichiers Power BI, donc la même spec donne toujours le même projet.

Pour la démo, j'ai pris des données publiques : l'historique des prix des carburants publié par Etalab.
Le rapport montre par exemple qu'un plein de 50 L de E10 coûte 4,80 € de plus dans les Hauts-de-Seine
qu'en Seine-et-Marne, et que le E10 a pris 22,8 % entre septembre 2022 et novembre 2023. Ce projet m'a
aussi obligé à traiter des pièges classiques : une somme de prix au litre ne veut rien dire (l'outil fait
maintenant une moyenne par défaut), et une moyenne qui mélange gazole et SP98 non plus (sélection forcée
d'un seul carburant).

**Compétences** : modélisation en étoile, DAX, Power BI (PBIP, TMDL, PBIR), Python, tests (228 tests,
couverture 98 %, chaque modèle généré chargé par TOM en CI), intégration d'un LLM par MCP.
