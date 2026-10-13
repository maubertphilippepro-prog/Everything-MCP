# Everything ↔ Claude Code

Serveur MCP local qui permet à Claude Code, dans n'importe quel projet, de chercher des fichiers avec Everything (voidtools), d'explorer des dossiers, de chercher une expression dans le contenu des fichiers (tous formats) et de **copier** des fichiers ou dossiers.

**Garde-fou :** aucun outil ne déplace, renomme, supprime ou écrase quoi que ce soit. Les copies sont créées sous un nom libre (`nom (2).ext`) et consignées dans `manifest.csv`.

## Utilisation

Dans Claude Code : `/everything <demande>`, par exemple :

- `/everything les PDF du chantier Martin modifiés cette semaine`
- `/everything que contient D:\Chantiers\Martin ?`
- `/everything les xls de D:\Chantiers qui contiennent exactement "XYZ"`
- `/everything copie dans extract/ tous les .xls de D:\Chantiers contenant "XYZ" plus récents que le 01/01/2020`
- `/everything copie le dossier D:\Chantiers\Martin dans sauvegarde/ en gardant la structure`

Avant toute copie, Claude montre un aperçu et attend votre accord.

## Outils exposés

| Outil | Rôle |
|---|---|
| `everything_search` | Recherche par nom, chemin, extension, date, taille… |
| `everything_show` | Affiche la recherche dans la fenêtre d'Everything |
| `everything_find_content` | Expression exacte dans le contenu (lecteurs natifs, IFilters Windows, recherche brute) |
| `everything_folder_info` | Résumé d'un dossier : sous-dossiers, nombre de fichiers, tailles, extensions |
| `everything_copy` | Copie de fichiers et dossiers, à plat ou en conservant l'arborescence |

## Installation

Prérequis : Everything lancé, `es.exe` (CLI d'Everything) présent dans `C:\Program Files\Everything\` ou `C:\Program Files (x86)\Everything\`, Python 3.12+.

```powershell
cd C:\Users\pmaubert\dev\everything_mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
claude mcp add --scope user everything -- "C:\Users\pmaubert\dev\everything_mcp\.venv\Scripts\python.exe" "C:\Users\pmaubert\dev\everything_mcp\server.py"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills\everything"
Copy-Item skill\SKILL.md "$env:USERPROFILE\.claude\skills\everything\SKILL.md"
```

Claude Code lance le serveur automatiquement à chaque session. Vérification : `/mcp` doit afficher `everything` connecté.

## Options (variables d'environnement, à passer avec `-e NOM=valeur` dans `claude mcp add`)

| Variable | Rôle | Défaut |
|---|---|---|
| `ES_PATH` | Chemin de es.exe | détecté automatiquement |
| `EVERYTHING_EXE` | Chemin d'Everything.exe | détecté automatiquement |
| `EVERYTHING_INSTANCE` | Instance, ex. `1.5a` | vide |
| `EVERYTHING_MAX_RESULTS` | Plafond de résultats par recherche | `500` |
| `EVERYTHING_COPY_MAX_FILES` | Plafond de fichiers par copie | `500` |
| `EVERYTHING_COPY_MAX_BYTES` | Plafond de volume par copie (octets) | `2147483648` |
| `EVERYTHING_CONTENT_TIMEOUT` | Durée max d'une recherche dans le contenu (s) | `300` |
| `EVERYTHING_FOLDER_MAX_ITEMS` | Éléments max analysés par résumé de dossier | `500000` |
| `EVERYTHING_BACKEND` | `es` ou `http` | `es` |
| `EVERYTHING_HTTP_URL` | Serveur HTTP d'Everything | `http://127.0.0.1:8080` |

## Développement

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest                 # tests unitaires
.\.venv\Scripts\python.exe -m pytest -m integration  # tests sur le vrai Everything
```

Le test `tests/test_guardrails.py` échoue si un module du serveur introduit une opération destructrice (suppression, déplacement, renommage, écrasement).

Les résultats d'es.exe sont lus via un fichier d'export propre à chaque processus, `%TEMP%\everything_mcp\es-export-<pid>.csv` (es.exe l'écrase à chaque recherche). Ce passage par un fichier évite la corruption des chemins accentués : la sortie standard d'es.exe utilise la page de code OEM. Le serveur ne supprime jamais ce fichier ; il peut être effacé à la main.

## Dépannage

- **« es.exe a échoué (code 8) »** : Everything n'est pas lancé (ou instance 1.5 alpha : `-e EVERYTHING_INSTANCE=1.5a`).
- **« es.exe introuvable »** : renseigner `ES_PATH`.
- **Fichiers OneDrive ignorés** dans une recherche de contenu : ils ne sont pas en local ; demander explicitement de les inclure (téléchargement).
- **`method: "raw"`** : le format n'a ni lecteur ni IFilter ; correspondance trouvée dans les octets bruts, à vérifier.
- **Copie partielle ou non consignée** : le résultat de `everything_copy` signale alors `errors[].target` (copie incomplète laissée sur le disque), `warnings` (dates ou attributs non conservés) ou `manifest_error` (copie faite mais absente de `manifest.csv`).
- **`%TEMP%\everything_mcp\es-export-<pid>.csv`** : fichier d'export d'es.exe (voir Développement), à ignorer.
