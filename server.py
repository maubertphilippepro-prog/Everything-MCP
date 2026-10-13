"""Serveur MCP entre Claude Code et Everything (voidtools).

Outils : recherche, affichage dans Everything, recherche dans le contenu, résumé de dossier,
copie de fichiers et de dossiers. Garde-fou : aucun outil ne déplace, ne renomme, ne supprime
ni n'écrase quoi que ce soit — seule la création de nouvelles copies est possible.
"""

import json
import subprocess

try:  # SDK MCP v2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # SDK MCP v1
    from mcp.server.fastmcp import FastMCP

import config
import content_search
import copier
import everything_backend
import folder_info as folder_info_module

mcp = FastMCP("everything")

GUI_SORTS = {
    "name": "Name", "path": "Path", "size": "Size", "extension": "Extension",
    "date-modified": "Date Modified", "date-created": "Date Created",
}


def _json(data):
    return json.dumps(data, ensure_ascii=False, indent=1)


def _error(message, **extra):
    return _json({"error": message, **extra})


@mcp.tool()
def everything_search(
    query: str,
    max_results: int = 50,
    offset: int = 0,
    sort: str = "date-modified",
    descending: bool = True,
    match_path: bool = False,
    regex: bool = False,
) -> str:
    """Recherche instantanée de fichiers et dossiers sur le PC Windows via Everything 1.4.

    Traduire la demande en requête Everything. La syntaxe est TOUJOURS en anglais ; les dates
    TOUJOURS au format ISO AAAA-MM-JJ (jamais jour/mois/année, ambigu).

    Opérateurs : espace = ET, | = OU, ! = NON, < > = groupement, "..." = expression exacte.
    Jokers : * (0+ caractères), ? (1 caractère).
    Filtres utiles :
      file:  folder:                       uniquement fichiers / dossiers
      ext:pdf;docx;xlsx                    extensions (séparées par ;)
      "D:\\Projets\\"                      tout ce qui est sous ce dossier (sous-dossiers inclus)
      infolder:"C:\\Docs"  parent:...      dans ce dossier exactement (sans sous-dossiers)
      size:>50mb  size:1mb..10mb  size:huge (16-128 Mo)  size:gigantic (>128 Mo)  size:empty
      dm:>=2020-01-01  dm:2024-01-01..2024-06-30  dm:today  dm:thisweek  dm:last2weeks  dm:thisyear
      dc: (création), da: (accès) — même syntaxe que dm:
      dupe:  sizedupe:  empty:  child:<nom>  childcount:  attrib:<lettres>  type:<type>  count:<n>
      startwith:  endwith:  wholeword:  case:  nodiacritics:  width:  height:  orientation:portrait
    Ne pas utiliser content: (lent et aveugle aux fichiers Office) : utiliser everything_find_content.
    Exemples :
      "les PDF du chantier Martin modifiés cette semaine" -> ext:pdf *martin* dm:thisweek
      "les gros fichiers vidéo sur D:"                    -> "D:\\" ext:mp4;mov;mkv;avi size:>500mb
      "les Excel depuis le 1er janvier 2020"              -> ext:xls;xlsx;xlsm dm:>=2020-01-01
      "dossiers vides dans Documents"                     -> folder: empty: "C:\\Users\\moi\\Documents\\"
    Référence complète : docs/everything-syntax-1.4.md dans le dépôt du serveur.

    Paramètres :
      query        requête Everything
      max_results  nombre de résultats (défaut 50, plafonné)
      offset       décalage pour paginer
      sort         name | path | size | extension | date-modified | date-created
      descending   tri décroissant (défaut True : plus récent / plus gros d'abord)
      match_path   faire porter les termes sur le chemin complet, pas seulement le nom
      regex        interpréter la requête comme une expression régulière (sur le nom)

    Renvoie du JSON : liste de {path, size (octets), modified, type="folder" pour un dossier}.
    Si 0 résultat, essayer une requête moins restrictive avant de conclure.
    """
    max_results = max(1, min(int(max_results), config.MAX_RESULTS))
    offset = max(0, int(offset))
    try:
        entries = everything_backend.search(
            query, max_results=max_results, offset=offset, sort=sort,
            descending=descending, match_path=match_path, regex=regex,
        )
    except everything_backend.EverythingError as e:
        return _error(str(e), query=query)
    out = {"query": query, "returned": len(entries), "offset": offset, "results": [e.to_dict() for e in entries]}
    if len(entries) == max_results:
        out["note"] = "Résultats tronqués : utiliser offset pour la suite ou affiner la requête."
    return _json(out)


@mcp.tool()
def everything_show(
    query: str,
    sort: str = "date-modified",
    descending: bool = True,
    match_path: bool = False,
    regex: bool = False,
    select: str = "",
    new_window: bool = False,
) -> str:
    """Affiche une recherche dans la fenêtre d'Everything sur le PC de l'utilisateur.

    À utiliser quand l'utilisateur veut voir ou manipuler les résultats dans l'interface
    d'Everything (« montre-moi », « ouvre dans Everything », « affiche-les »). Même syntaxe de
    requête qu'everything_search.

    Paramètres :
      query       requête Everything (syntaxe anglaise)
      sort        name | path | size | extension | date-modified | date-created
      descending  tri décroissant
      match_path  faire porter les termes sur le chemin complet
      regex       requête en expression régulière
      select      chemin complet d'un fichier à sélectionner dans les résultats (optionnel)
      new_window  ouvrir une nouvelle fenêtre plutôt que réutiliser celle déjà ouverte
    """
    args = [config.EVERYTHING_EXE]
    if config.INSTANCE:
        args += ["-instance", config.INSTANCE]
    args.append("-newwindow" if new_window else "-nonewwindow")
    args.append("-matchpath" if match_path else "-nomatchpath")
    args.append("-regex" if regex else "-noregex")
    args += ["-sort", GUI_SORTS.get(sort, "Date Modified")]
    args.append("-sort-descending" if descending else "-sort-ascending")
    args += ["-s", query]
    if select:
        args += ["-select", select]
    try:
        subprocess.Popen(args, close_fds=True)
    except FileNotFoundError:
        return _error(f"Everything.exe introuvable : {config.EVERYTHING_EXE}. Renseignez EVERYTHING_EXE.")
    except OSError as e:
        return _error(f"Impossible de lancer Everything : {e}")
    return _json({"shown": True, "query": query})


@mcp.tool()
def everything_find_content(
    query: str,
    phrase: str,
    case_sensitive: bool = False,
    include_cloud: bool = False,
    allow_raw: bool = True,
    max_candidates: int = 2000,
) -> str:
    """Trouve les fichiers dont le CONTENU contient exactement une expression, quel que soit le format.

    Everything sélectionne d'abord les candidats avec `query` (même syntaxe qu'everything_search ;
    file: est ajouté automatiquement), puis le serveur ouvre chaque fichier et cherche `phrase`.
    La requête DOIT être restrictive : un dossier ("D:\\Chantiers\\") et/ou ext:, dm:… Au-delà de
    max_candidates fichiers, l'outil refuse et demande d'affiner.

    Lecture : lecteurs natifs (xls, xlsx, docx, pptx, odt/ods/odp, pdf, texte), puis IFilters
    Windows (doc, msg, rtf…), puis recherche brute dans les octets (method="raw", moins fiable).
    Les fichiers OneDrive « en ligne uniquement » sont ignorés (non téléchargés) sauf include_cloud.

    Paramètres :
      query           requête Everything des candidats, ex. ext:xls dm:>=2020-01-01 "D:\\Chantiers\\"
      phrase          expression exacte à trouver (espaces compris)
      case_sensitive  respecter la casse (défaut non)
      include_cloud   inclure les fichiers OneDrive non présents en local (déclenche leur téléchargement)
      allow_raw       autoriser la recherche brute pour les formats sans lecteur
      max_candidates  plafond de fichiers à examiner (défaut 2000)

    Renvoie du JSON : candidates, matches [{path, size, modified, method}], not_matching (nombre),
    unverified [{path, reason}] — un fichier non vérifié n'est jamais compté comme correspondant.
    """
    try:
        return _json(content_search.find_content(
            query, phrase, case_sensitive=case_sensitive, include_cloud=include_cloud,
            allow_raw=allow_raw, max_candidates=max(1, int(max_candidates)),
        ))
    except (everything_backend.EverythingError, content_search.TooManyCandidates, ValueError) as e:
        return _error(str(e), query=query)


@mcp.tool()
def everything_folder_info(path: str, depth: int = 1) -> str:
    """Résume le contenu d'un dossier depuis l'index Everything (sans parcourir le disque).

    Paramètres :
      path   chemin absolu du dossier
      depth  profondeur des sous-dossiers détaillés (1 à 5, défaut 1)

    Renvoie du JSON : files, folders, size (octets, récursif), latest_modified, subfolders
    [{path, relative, files, folders, size}], by_extension [{extension, files, size}] (30 plus
    volumineuses), truncated (True si le dossier dépasse le plafond d'éléments).
    """
    try:
        return _json(folder_info_module.folder_info(path, depth))
    except (everything_backend.EverythingError, ValueError) as e:
        return _error(str(e), path=path)


@mcp.tool()
def everything_copy(paths: list[str], destination: str, preserve_tree_from: str = "") -> str:
    """COPIE des fichiers et/ou dossiers vers un dossier de destination. Ne déplace, ne renomme,
    ne supprime et n'écrase JAMAIS rien.

    AVANT d'appeler cet outil : montrer à l'utilisateur la liste (nombre, taille totale) et
    obtenir sa confirmation explicite.

    Paramètres :
      paths               chemins ABSOLUS de fichiers et/ou dossiers (un dossier est copié en entier)
      destination         chemin ABSOLU du dossier de destination (créé au besoin). Une destination
                          relative donnée par l'utilisateur (ex. "extract/") se résout depuis le
                          dossier du projet Claude Code courant.
      preserve_tree_from  optionnel : dossier racine dont l'arborescence relative est recréée dans
                          la destination (ex. "D:\\Chantiers" -> extract\\A\\B\\f.xls). Vide = à plat.

    Règles : nom déjà pris -> suffixe " (2)", " (3)"… ; dossier homonyme existant -> "Nom (2)"
    (jamais de fusion) ; plafonds en nombre de fichiers et en volume vérifiés avant toute écriture
    (dépassement = rien n'est copié) ; liens et jonctions non suivis ; dossiers système refusés.
    Chaque copie est consignée dans manifest.csv (date_copie;source;copie;taille) à la racine de
    la destination.

    Renvoie du JSON : copied_files, copied_bytes, copied [{source, copy, size}] (200 premiers),
    skipped [{source, reason}], errors [{source, error}], manifest.
    """
    try:
        return _json(copier.copy_items(paths, destination, preserve_tree_from))
    except copier.CopyRefused as e:
        return _error(str(e), destination=destination)


if __name__ == "__main__":
    mcp.run()
