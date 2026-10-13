# Serveur MCP Everything pour Claude Code : recherche, contenu, copie

Date : 2026-10-13
Statut : validé (brainstorming), en attente de relecture

## Objectif

Piloter Everything (voidtools) depuis n'importe quel projet Claude Code pour :

1. rechercher des fichiers (nom, chemin, extension, date, taille…) ;
2. filtrer sur le contenu exact des fichiers, y compris Office et PDF ;
3. **dupliquer** les fichiers trouvés vers un dossier.

Exemple cible : `/everything copie dans extract/ tous les .xls contenant exactement "XYZ" et plus récents que le 1er janvier 2020`.

**Garde-fou absolu : aucun déplacement, renommage, suppression ou écrasement de fichier.** Seule la copie vers un nouveau fichier est possible.

## Contexte existant

- `server.py` : serveur FastMCP (Python) avec `everything_search` (via es.exe ou HTTP) et `everything_show` (ouvre la recherche dans la fenêtre d'Everything). Pensé pour Claude Desktop.
- Poste cible : Everything 1.4.1.1032 en service, `es.exe` 1.1.0.38 dans `C:\Program Files (x86)\Everything\` (pas dans le chemin par défaut du code), Python 3.14, paquet `mcp` non installé, serveur non enregistré dans Claude Code.
- Référence de syntaxe Everything 1.4 : `docs/everything-syntax-1.4.md`.

## Contraintes techniques constatées

- `content:`, `ansicontent:`, `utf8content:`, `utf16content:` d'Everything 1.4 comparent les octets bruts : inopérants sur `.xlsx`/`.docx`/`.pptx` (zip), non fiables sur `.xls` (BIFF) et `.pdf`. Ils forcent en outre le téléchargement des fichiers OneDrive « en ligne uniquement ».
- Les expressions régulières d'Everything portent sur le nom (ou le chemin avec `path:`), jamais sur le contenu.
- Dates : `jour/mois/année` est ambigu ; on utilise exclusivement l'ISO `AAAA-MM-JJ`.

## Architecture

On étend le `server.py` existant (Python, FastMCP), découpé en modules :

| Fichier | Responsabilité |
|---|---|
| `server.py` | Déclaration des outils MCP, lecture de la configuration, sérialisation JSON |
| `everything_backend.py` | Exécution des requêtes via es.exe ou HTTP (code existant déplacé) |
| `extractors.py` | Extraction du texte d'un fichier selon son format |
| `copier.py` | Copie sûre (sans écrasement), plafonds, manifeste |

Aucun module n'importe ni n'appelle `os.remove`, `os.unlink`, `os.rename`, `os.replace`, `shutil.move`, `shutil.rmtree` ou `Path.unlink/rename/replace`. Un test le vérifie par analyse du code source.

## Outils MCP

### `everything_search` (existant)
Inchangé fonctionnellement. Docstring mise à jour selon la syntaxe 1.4 (`infolder:`, `count:`, `attrib:`, `type:`, constantes de date, dates ISO).

### `everything_show` (existant)
Inchangé.

### `everything_find_content` (nouveau)

Paramètres :

| Paramètre | Défaut | Rôle |
|---|---|---|
| `query` | — | Requête Everything qui sélectionne les candidats (doit restreindre : `ext:`, `path:`/`infolder:`, `dm:`…) |
| `phrase` | — | Expression exacte recherchée dans le contenu |
| `case_sensitive` | `False` | Respect de la casse |
| `include_cloud` | `False` | Inclure les fichiers OneDrive non présents en local |
| `max_candidates` | `2000` | Plafond de candidats ; au-delà, erreur demandant d'affiner la requête |

Fonctionnement :

1. Si `include_cloud` est faux, ajout de `!attrib:O` à la requête.
2. Récupération des candidats via le backend (fichiers uniquement, `file:` ajouté). Si le nombre de candidats dépasse `max_candidates`, l'appel s'arrête avec une erreur explicite (aucune lecture de fichier).
3. Pour chaque candidat : contrôle de l'attribut Windows (`FILE_ATTRIBUTE_OFFLINE` 0x1000, `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` 0x400000, `FILE_ATTRIBUTE_RECALL_ON_OPEN` 0x40000) quand `include_cloud` est faux, puis extraction du texte et recherche de `phrase`.
4. Comparaison : texte normalisé en Unicode NFC, espaces multiples non fusionnés (expression **exacte**), casse ignorée par défaut via `casefold()`.
5. Un délai global (`EVERYTHING_CONTENT_TIMEOUT`, 300 s par défaut) arrête l'analyse ; les fichiers restants sont listés comme « non analysés ».

Retour JSON :

```json
{
  "query": "ext:xls dm:>=2020-01-01 file: !attrib:O",
  "phrase": "XYZ",
  "candidates": 120,
  "matches": [{"path": "...", "size": 37376, "modified": "2021-05-03T10:12:00"}],
  "not_matching": 112,
  "unverified": [{"path": "...", "reason": "format non pris en charge | fichier protégé par mot de passe | erreur de lecture : … | en ligne uniquement | délai dépassé"}]
}
```

Un fichier non vérifié n'est jamais compté comme correspondant.

### `everything_copy` (nouveau)

Paramètres :

| Paramètre | Rôle |
|---|---|
| `paths` | Liste de chemins absolus de fichiers sources |
| `destination` | Chemin **absolu** du dossier de destination (créé s'il n'existe pas) |

Règles appliquées par le code :

- Sources : fichiers existants uniquement (un dossier ou un chemin introuvable est refusé ligne par ligne, sans bloquer les autres).
- Destination : absolue ; refusée si elle est (ou se trouve sous) `%SystemRoot%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%ProgramData%`, ou la racine d'un lecteur. Une source déjà située directement dans la destination est ignorée (raison : « déjà dans la destination »).
- **Aucun écrasement** : la copie est créée avec `open(dst, "xb")` (création exclusive). En cas de nom existant, essai de `nom (2).ext`, `nom (3).ext`… jusqu'à trouver un nom libre.
- Copie du contenu par `shutil.copyfileobj`, puis des métadonnées (dates) par `shutil.copystat`.
- Copie à plat dans `destination`.
- Plafonds vérifiés **avant** toute copie : `EVERYTHING_COPY_MAX_FILES` (500) et `EVERYTHING_COPY_MAX_BYTES` (2 Go). Dépassement : refus complet, rien n'est copié.
- Manifeste `manifest.csv` dans la destination, complété en mode ajout (en-tête écrit s'il est nouveau), UTF-8 avec BOM pour Excel, séparateur `;` : `date_copie;source;copie;taille`.
- Échec en cours de copie d'un fichier (disque plein, accès refusé…) : le fichier partiel créé par cet appel est conservé tel quel et signalé (pas de suppression, conformément au garde-fou) ; on continue avec les suivants.

Retour JSON : `{"destination", "copied": [{"source", "copy", "size"}], "skipped": [{"source", "reason"}], "errors": [{"source", "error"}], "manifest"}`.

## Skill `/everything` (Claude Code)

Emplacement : `~/.claude/skills/everything/SKILL.md` (niveau utilisateur, disponible dans tous les projets).

Contenu :

1. Traduire la demande en requête Everything (syntaxe anglaise, dates ISO), en consultant `docs/everything-syntax-1.4.md` du dépôt (chemin absolu dans le skill) pour les cas inhabituels.
2. Choisir l'outil : `everything_search`, `everything_show`, ou `everything_find_content` si un critère porte sur le contenu.
3. Recherche avec contenu : exiger une restriction de dossier ; si l'utilisateur n'en donne pas, la demander avant de lancer.
4. **Copie** : résoudre la destination relative par rapport au dossier du projet courant ; présenter un aperçu (nombre de fichiers, taille totale, liste des 20 premiers, fichiers non vérifiés) et **attendre la confirmation explicite** avant d'appeler `everything_copy`.
5. Interdiction explicite de déplacer, renommer, supprimer ou écraser des fichiers, y compris par Bash/PowerShell (`mv`, `rm`, `Move-Item`, `Remove-Item`, `ren`…). Si l'utilisateur le demande, refuser et rappeler que seule la copie est permise.

Le skill synchronisé existant (`anthropic-skills:everything`, lecture seule, Claude Desktop) n'est pas modifié.

## Installation

- Environnement virtuel `.venv` dans le dépôt ; `requirements.txt` : `mcp`, `xlrd`, `openpyxl`, `pypdf`, `pytest`.
- Enregistrement : `claude mcp add --scope user everything -e ES_PATH="C:\Program Files (x86)\Everything\es.exe" -- <dépôt>\.venv\Scripts\python.exe <dépôt>\server.py`.
- README mis à jour pour Claude Code (Claude Desktop reste documenté en annexe).

## Extracteurs de contenu

| Extensions | Méthode |
|---|---|
| `.xls` | `xlrd` : toutes les feuilles, valeurs des cellules converties en texte |
| `.xlsx`, `.xlsm` | `openpyxl` en `read_only=True, data_only=True` : valeurs des cellules |
| `.docx`, `.pptx` | `zipfile` : texte des parties XML (`word/*.xml`, `ppt/slides/*.xml`), balises retirées, paragraphes joints |
| `.pdf` | `pypdf` : texte de chaque page |
| `.txt`, `.csv`, `.md`, `.json`, `.xml`, `.html`, `.log`, `.ini`, `.py`, `.js`, `.ts`, `.sql`… | Lecture avec détection de BOM, puis UTF-8, puis cp1252 |
| autres | « format non pris en charge » |

Pour Excel, le texte extrait place une tabulation entre cellules et un saut de ligne entre lignes : une expression sans tabulation ne peut donc correspondre qu'à l'intérieur d'une seule cellule (pas de faux positif à cheval sur deux cellules). Chaque extraction est limitée à 50 Mo de texte.

## Configuration (variables d'environnement)

Existantes : `ES_PATH`, `EVERYTHING_EXE`, `EVERYTHING_INSTANCE`, `EVERYTHING_MAX_RESULTS`, `EVERYTHING_BACKEND`, `EVERYTHING_HTTP_URL`.
Nouvelles : `EVERYTHING_COPY_MAX_FILES` (500), `EVERYTHING_COPY_MAX_BYTES` (2147483648), `EVERYTHING_CONTENT_TIMEOUT` (300).

## Tests (pytest)

- `extractors` : fichiers générés en test (xlsx via openpyxl, docx/pptx construits en zip, txt dans plusieurs encodages, pdf minimal) ; `.xls` testé sur un fichier de fixture versionné.
- `copier` : copie simple ; collision → suffixe `(2)`, `(3)` ; fichier existant jamais modifié (contenu et date vérifiés) ; plafonds → rien copié ; destination système refusée ; destination relative refusée ; source dossier/introuvable signalée ; manifeste correct.
- Garde-fou statique : aucun appel interdit dans le code source du serveur.
- `find_content` : backend simulé renvoyant des chemins de fixtures ; correspondances, non-correspondances, non vérifiés, plafond de candidats.
- Intégration (marquée `integration`, exécutée manuellement) : es.exe réel, comportement de `!attrib:O` sur un fichier OneDrive en ligne uniquement.

## Hors périmètre

- Recherche par regex dans le contenu.
- Copie de dossiers entiers, recréation de l'arborescence.
- Fichiers chiffrés ou protégés par mot de passe (signalés non vérifiés).
- Formats `.doc`/`.ppt` binaires anciens, `.odt`/`.ods`, `.msg`.
