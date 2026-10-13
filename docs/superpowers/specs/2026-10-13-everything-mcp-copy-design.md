# Serveur MCP Everything pour Claude Code : recherche, contenu, copie

Date : 2026-10-13
Statut : validé (brainstorming), en attente de relecture

## Objectif

Piloter Everything (voidtools) depuis n'importe quel projet Claude Code pour :

1. rechercher des fichiers et des dossiers (nom, chemin, extension, date, taille…) ;
2. filtrer sur le contenu exact des fichiers, **quel que soit le format** ;
3. explorer un dossier (arborescence, tailles, nombre et types de fichiers) ;
4. **dupliquer** des fichiers ou des dossiers entiers vers une destination, à plat ou en conservant l'arborescence.

Exemple cible : `/everything copie dans extract/ tous les .xls contenant exactement "XYZ" et plus récents que le 1er janvier 2020`.

**Garde-fou absolu : aucun déplacement, renommage, suppression ou écrasement de fichier ou de dossier.** Seule la création de nouvelles copies est possible.

## Contexte existant

- `server.py` : serveur FastMCP (Python) avec `everything_search` (via es.exe ou HTTP) et `everything_show` (ouvre la recherche dans la fenêtre d'Everything). Pensé pour Claude Desktop.
- Poste cible : Everything 1.4.1.1032 en service, `es.exe` 1.1.0.38 dans `C:\Program Files (x86)\Everything\` (pas dans le chemin par défaut du code), Python 3.14, paquet `mcp` non installé, serveur non enregistré dans Claude Code, Java absent.
- IFilters Windows installés (constaté) pour au moins `.pdf`, `.doc`, `.msg`, `.xls`, `.dwg`.
- Référence de syntaxe Everything 1.4 : `docs/everything-syntax-1.4.md`.

## Contraintes techniques constatées

- `content:`, `ansicontent:`, `utf8content:`, `utf16content:` d'Everything 1.4 comparent les octets bruts : inopérants sur `.xlsx`/`.docx`/`.pptx` (zip), non fiables sur `.xls` (BIFF) et `.pdf`. Ils forcent en outre le téléchargement des fichiers OneDrive « en ligne uniquement ». Ils ne sont donc pas utilisés.
- Les expressions régulières d'Everything portent sur le nom (ou le chemin avec `path:`), jamais sur le contenu.
- Dates : `jour/mois/année` est ambigu ; on utilise exclusivement l'ISO `AAAA-MM-JJ`.

## Architecture

On étend le `server.py` existant (Python, FastMCP), découpé en modules :

| Fichier | Responsabilité |
|---|---|
| `server.py` | Déclaration des outils MCP, lecture de la configuration, sérialisation JSON |
| `everything_backend.py` | Exécution des requêtes via es.exe ou HTTP (code existant déplacé) |
| `extractors.py` | Extraction du texte d'un fichier : lecteurs natifs, puis IFilter, puis recherche brute |
| `ifilter.py` | Accès aux IFilters Windows (`LoadIFilter` de `query.dll` via `comtypes`) |
| `copier.py` | Planification et exécution des copies sûres (fichiers, dossiers, arborescence), plafonds, manifeste |
| `folder_info.py` | Résumé d'un dossier à partir de l'index Everything |

Aucun module n'importe ni n'appelle `os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `os.rename`, `os.renames`, `os.replace`, `shutil.move`, `shutil.rmtree`, `shutil.copytree` (qui peut écrire dans un dossier existant avec `dirs_exist_ok`), ni `Path.unlink/rmdir/rename/replace`. Un test le vérifie par analyse du code source.

## Outils MCP

### `everything_search` (existant)
Inchangé fonctionnellement ; trouve aussi les dossiers (`folder:`). Docstring mise à jour selon la syntaxe 1.4 (`infolder:`, `count:`, `attrib:`, `type:`, constantes de date, dates ISO).

### `everything_show` (existant)
Inchangé.

### `everything_find_content` (nouveau)

Paramètres :

| Paramètre | Défaut | Rôle |
|---|---|---|
| `query` | — | Requête Everything qui sélectionne les candidats (doit restreindre : `ext:`, `path:`/`infolder:`, `dm:`…). Pour chercher « dans un dossier », la requête contient ce dossier (`"D:\Chantiers\"`). |
| `phrase` | — | Expression exacte recherchée dans le contenu |
| `case_sensitive` | `False` | Respect de la casse |
| `include_cloud` | `False` | Inclure les fichiers OneDrive non présents en local |
| `allow_raw` | `True` | Autoriser le niveau 3 (recherche brute) pour les formats sans lecteur ni IFilter |
| `max_candidates` | `2000` | Plafond de candidats ; au-delà, erreur demandant d'affiner la requête |

Fonctionnement :

1. `file:` est ajouté à la requête.
2. Récupération des candidats via le backend, avec leurs attributs Windows (colonne `-attributes` de es.exe). Au-delà de `max_candidates` : erreur explicite, aucune lecture de fichier.
3. Pour chaque candidat : si `include_cloud` est faux, les fichiers dont les attributs contiennent `FILE_ATTRIBUTE_OFFLINE` 0x1000, `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` 0x400000 ou `FILE_ATTRIBUTE_RECALL_ON_OPEN` 0x40000 sont classés « en ligne uniquement » sans être ouverts. (Constaté : les fichiers OneDrive en ligne uniquement portent 0x400000 et **pas** l'attribut `O` ; `!attrib:O` serait donc inopérant. Si le backend ne fournit pas les attributs — mode HTTP —, ils sont lus par `os.stat`, qui ne déclenche pas de téléchargement.) Puis extraction du texte (voir « Extraction du contenu ») et recherche de `phrase`.
4. Comparaison : texte normalisé en Unicode NFC, expression **exacte** (espaces non fusionnés), casse ignorée par défaut via `casefold()`.
5. Délai global `EVERYTHING_CONTENT_TIMEOUT` (300 s) ; les fichiers restants sont listés « délai dépassé ».

Retour JSON :

```json
{
  "query": "ext:xls dm:>=2020-01-01 file:",
  "phrase": "XYZ",
  "candidates": 120,
  "matches": [{"path": "...", "size": 37376, "modified": "2021-05-03T10:12:00", "method": "native | ifilter | raw"}],
  "not_matching": 112,
  "unverified": [{"path": "...", "reason": "protégé par mot de passe | erreur de lecture : … | en ligne uniquement | délai dépassé | aucun lecteur (recherche brute désactivée)"}]
}
```

Un fichier non vérifié n'est jamais compté comme correspondant. `method: "raw"` signale une fiabilité moindre (voir niveau 3).

### `everything_folder_info` (nouveau)

Paramètres : `path` (dossier absolu), `depth` (défaut 1, max 5).

Utilise l'index Everything (aucun parcours disque) avec la requête `"<path>\"` : renvoie pour le dossier et chaque sous-dossier jusqu'à `depth` le nombre de fichiers, le nombre de sous-dossiers, la taille totale ; plus une répartition par extension (nombre, taille) et la date de modification la plus récente. Au-delà de `EVERYTHING_FOLDER_MAX_ITEMS` (500 000) éléments, le résultat indique qu'il est partiel.

### `everything_copy` (nouveau)

Paramètres :

| Paramètre | Défaut | Rôle |
|---|---|---|
| `paths` | — | Chemins absolus de fichiers **et/ou dossiers** sources |
| `destination` | — | Chemin **absolu** du dossier de destination (créé s'il n'existe pas) |
| `preserve_tree_from` | `""` | Si renseigné : dossier racine dont l'arborescence relative est recréée dans la destination |

Modes :

- **À plat** (`preserve_tree_from` vide) :
  - un fichier est copié dans `destination\nom.ext` ;
  - un dossier est copié entièrement (récursivement) dans `destination\NomDossier\…`.
- **Avec arborescence** (`preserve_tree_from = R`) : chaque source doit se trouver sous `R` (sinon ignorée, raison « hors de la racine ») ; un fichier `R\A\B\f.xls` est copié dans `destination\A\B\f.xls` ; un dossier `R\A\B` est copié récursivement dans `destination\A\B\…`.

Règles appliquées par le code :

- **Planification avant exécution** : le serveur établit la liste complète des fichiers à copier (y compris le contenu récursif des dossiers) et vérifie les plafonds `EVERYTHING_COPY_MAX_FILES` (500) et `EVERYTHING_COPY_MAX_BYTES` (2 Go) **avant** toute écriture. Dépassement : refus complet, rien n'est créé.
- **Aucun écrasement de fichier** : chaque fichier est créé avec `open(dst, "xb")` (création exclusive). Nom pris : `nom (2).ext`, `nom (3).ext`… jusqu'à un nom libre.
- **Aucune fusion de dossier copié en mode à plat** : si `destination\NomDossier` existe déjà, le dossier copié devient `NomDossier (2)`, `NomDossier (3)`… En mode arborescence, les dossiers intermédiaires existants sont réutilisés (on y ajoute des fichiers, on n'en modifie aucun) ; les collisions de fichiers suivent la règle du suffixe.
- Les dossiers sont créés par `os.mkdir` (ou `os.makedirs(exist_ok=True)` pour les intermédiaires du mode arborescence) — jamais d'autre opération sur l'existant.
- Liens symboliques et jonctions (points d'analyse) rencontrés dans un dossier source : non suivis, signalés dans `skipped` (évite les boucles et les copies hors périmètre).
- Fichiers OneDrive « en ligne uniquement » dans un dossier source : copiés (cela déclenche leur téléchargement) ; ils sont comptés dans les plafonds avec leur taille annoncée.
- Destination : absolue ; refusée si elle est (ou se trouve sous) `%SystemRoot%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%ProgramData%`, ou si c'est la racine d'un lecteur. Refusée si elle se trouve **à l'intérieur d'un dossier source** (copie récursive sans fin). Une source fichier déjà située directement dans la destination est ignorée (« déjà dans la destination »).
- Contenu copié par `shutil.copyfileobj`, puis dates par `shutil.copystat`.
- Manifeste `manifest.csv` à la racine de la destination, en mode ajout (en-tête si nouveau), UTF-8 avec BOM, séparateur `;` : `date_copie;source;copie;taille` — une ligne par fichier copié.
- Échec en cours de copie d'un fichier (disque plein, accès refusé…) : le fichier partiel créé par cet appel est conservé et signalé (pas de suppression, conformément au garde-fou) ; on continue avec les suivants.

Retour JSON : `{"destination", "mode": "flat | tree", "copied_files": n, "copied_bytes": n, "copied": [{"source", "copy", "size"}] (200 premiers), "skipped": [{"source", "reason"}], "errors": [{"source", "error"}], "manifest"}`.

## Extraction du contenu (tous formats)

Trois niveaux, essayés dans l'ordre ; le premier qui produit du texte est retenu et noté dans `method`.

**Niveau 1 — lecteurs natifs** (`method: "native"`) :

| Extensions | Méthode |
|---|---|
| `.xls` | `xlrd` : toutes les feuilles, valeurs des cellules |
| `.xlsx`, `.xlsm` | `openpyxl` (`read_only=True, data_only=True`) |
| `.docx`, `.pptx` | `zipfile` : parties XML (`word/*.xml`, `ppt/slides/*.xml`), balises retirées |
| `.odt`, `.ods`, `.odp` | `zipfile` : `content.xml`, balises retirées |
| `.pdf` | `pypdf` : texte de chaque page |
| texte (`.txt`, `.csv`, `.md`, `.json`, `.xml`, `.html`, `.log`, `.ini`, `.py`, `.js`, `.ts`, `.sql`…) | détection de BOM, puis UTF-8, puis cp1252 |

Pour Excel, le texte extrait place une tabulation entre cellules et un saut de ligne entre lignes : une expression sans tabulation ne peut correspondre qu'à l'intérieur d'une seule cellule.

**Niveau 2 — IFilter Windows** (`method: "ifilter"`) : pour toute extension ayant un `PersistentHandler` enregistré (`.doc`, `.ppt`, `.msg`, `.rtf`, `.dwg`…, selon les logiciels installés). Appel de `LoadIFilter` puis lecture des blocs de texte (`GetChunk`/`GetText`) ; les blocs signalés `FILTER_E_EMBEDDING_UNAVAILABLE` / `FILTER_E_LINK_UNAVAILABLE` (pièce jointe ou lien illisible, fréquent dans les `.msg`) sont sautés sans abandonner le fichier. Constaté sur le poste : `.rtf`, `.doc`, `.xls`, `.msg` lisibles ; filtre `.pdf` non chargeable (pypdf couvre) ; filtre `.dwg` en échec (niveau 3 prend le relais). Aussi utilisé en secours si un lecteur natif échoue. Chaque appel est exécuté dans un processus fils avec délai (30 s par fichier) pour qu'un filtre défaillant ne bloque pas le serveur.

**Niveau 3 — recherche brute** (`method: "raw"`, si `allow_raw`) : recherche de l'expression dans les octets du fichier encodée en UTF-8, UTF-16LE et cp1252 ; si le fichier est une archive zip, même recherche dans chacun de ses membres décompressés. Fiabilité moindre (texte compressé ou fragmenté non trouvé), d'où le marquage.

Chaque extraction est limitée à 50 Mo de texte (niveau 3 : 200 Mo lus). Fichier chiffré ou protégé par mot de passe : `unverified`.

## Skill `/everything` (Claude Code)

Emplacement : `~/.claude/skills/everything/SKILL.md` (niveau utilisateur, disponible dans tous les projets).

1. Traduire la demande en requête Everything (syntaxe anglaise, dates ISO), en consultant `docs/everything-syntax-1.4.md` du dépôt (chemin absolu dans le skill) pour les cas inhabituels.
2. Choisir l'outil : `everything_search`, `everything_show`, `everything_folder_info` (« que contient ce dossier », « taille de… »), `everything_find_content` si un critère porte sur le contenu.
3. Recherche avec contenu : exiger une restriction de dossier ; si l'utilisateur n'en donne pas, la demander.
4. **Copie** : résoudre la destination relative par rapport au dossier du projet courant ; choisir le mode (à plat par défaut, arborescence si l'utilisateur parle de « garder la structure / les sous-dossiers ») ; présenter un aperçu (nombre de fichiers, taille totale, 20 premiers éléments, fichiers non vérifiés, méthodes `raw` signalées) et **attendre la confirmation explicite** avant d'appeler `everything_copy`.
5. Interdiction explicite de déplacer, renommer, supprimer ou écraser des fichiers ou dossiers, y compris par Bash/PowerShell (`mv`, `rm`, `rmdir`, `Move-Item`, `Remove-Item`, `Rename-Item`, `ren`, `robocopy /MOV|/MIR|/PURGE`…). Si l'utilisateur le demande, refuser et rappeler que seule la copie est permise.

Le skill synchronisé existant (`anthropic-skills:everything`, lecture seule, Claude Desktop) n'est pas modifié.

## Installation

- Environnement virtuel `.venv` dans le dépôt ; `requirements.txt` : `mcp`, `xlrd`, `openpyxl`, `pypdf`, `comtypes` ; `requirements-dev.txt` : `pytest`, `xlwt` (génération de `.xls` de test).
- Enregistrement : `claude mcp add --scope user everything -e ES_PATH="C:\Program Files (x86)\Everything\es.exe" -- <dépôt>\.venv\Scripts\python.exe <dépôt>\server.py`.
- README mis à jour pour Claude Code (Claude Desktop reste documenté en annexe).

## Configuration (variables d'environnement)

Existantes : `ES_PATH`, `EVERYTHING_EXE`, `EVERYTHING_INSTANCE`, `EVERYTHING_MAX_RESULTS`, `EVERYTHING_BACKEND`, `EVERYTHING_HTTP_URL`.
Nouvelles : `EVERYTHING_COPY_MAX_FILES` (500), `EVERYTHING_COPY_MAX_BYTES` (2147483648), `EVERYTHING_CONTENT_TIMEOUT` (300), `EVERYTHING_FOLDER_MAX_ITEMS` (500000).

## Tests (pytest)

- `extractors` niveau 1 : fichiers générés en test (xlsx via openpyxl, docx/pptx/odt construits en zip, txt en plusieurs encodages, pdf minimal) ; `.xls` sur une fixture versionnée.
- `extractors` niveau 2 : fichier `.rtf` généré, lu via IFilter (test ignoré si aucun IFilter `.rtf`) ; délai respecté avec un filtre simulé bloquant.
- `extractors` niveau 3 : expression en UTF-16LE dans un binaire ; expression dans un membre d'un zip ; `allow_raw=False` → `unverified`.
- `copier` : fichier simple ; collision → `(2)`, `(3)` ; fichier existant jamais modifié (contenu et date) ; dossier copié récursivement ; dossier homonyme existant → `NomDossier (2)` sans fusion ; mode arborescence (structure relative recréée, source hors racine ignorée) ; plafonds → rien créé ; destination système, relative ou intérieure à une source refusée ; lien symbolique/jonction signalé et non suivi ; manifeste correct.
- `folder_info` : backend simulé, agrégation par sous-dossier et par extension, profondeur.
- Garde-fou statique : aucun appel interdit dans le code source.
- `find_content` : backend simulé renvoyant des fixtures ; correspondances, non-correspondances, non vérifiés, plafond de candidats, champ `method`.
- Intégration (marqueur `integration`, manuelle) : es.exe réel ; attributs renvoyés pour un fichier OneDrive en ligne uniquement ; IFilter `.doc`/`.msg` sur des fichiers réels.

## Hors périmètre

- Recherche par regex dans le contenu.
- Création de dossiers vides isolés (les dossiers ne sont créés que par une copie).
- Fichiers chiffrés ou protégés par mot de passe (signalés non vérifiés).
